# tests/test_r63_b_vault.py -- R6.3 D11, D12 (plan review M4, H3): the AI pages sealed one file a
# release in their OWN index beside R6's (`book_pages/{uid}`, purpose book_index, AAD
# book/pages/{uid}/v1), attach or replace in one transaction (the old chunk set orphaned, then
# swept), R6's Privacy hold checked in the same transaction, the storage limit counting R6's total,
# R6's index never touched (a copy of 47ee8fc's BookIndex still opens it), the free carry and the
# changed pages, the sweep.
from __future__ import annotations

from typing import Any, Literal

import pytest
from r63_fake_brains import GOOD_DRAFT
from r63_fakes import FIXTURE_FACTS, NOW, RING, UID, FakeSource, FixedClock, source_zip
from r63_fakes_b import files

from jarvis.buildbook.model import SealedRelease
from jarvis.buildbook.ports import BookOff, VaultTampered
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.seal_index import BookCrypto, Part
from jarvis.buildbook.seal_state import SealHeld, SealState
from jarvis.buildbook.sections import Frozen
from jarvis.buildbook.writer import carry, checks, pages, sweep
from jarvis.buildbook.writer.model import (
    CHANGED_WAITING,
    PAGES_FILE_CAP_BYTES,
    PageMeta,
    PagesFile,
    Skipped,
)
from jarvis.buildbook.writer.vault import PagesVault
from jarvis.storage.docs import MemoryDocs

RID, RID2, RID3 = "6363636", "7070707", "7171717"
KNOWN = tuple(p.id for p in FIXTURE_FACTS.pages)
META = PageMeta(
    brain="anthropic", brain_label="Claude", model="m-balanced", provider="anthropic",
    release=RID, written_at=NOW.isoformat(), attempt=1, tokens_in=1, tokens_out=1, inr=1.0,
)  # fmt: skip


def _vault(docs: MemoryDocs | None = None) -> tuple[PagesVault, MemoryDocs]:
    d = docs or MemoryDocs()
    return PagesVault(d, RING, prefix="jarvis_", clock=FixedClock()), d


def _chunks(docs: MemoryDocs) -> list[str]:
    return sorted(p for p in docs._data if "/book_chunks/" in p and "book_pages" in p)


async def _put(v: PagesVault, rid: str, data: bytes, **kw: Any) -> Any:
    args: dict[str, Any] = dict(counts=(1, 0, 0), limit_bytes=60 * 1024 * 1024, others_bytes=0)
    args.update(kw)
    return await v.put(UID, rid, data, **args)


async def test_attach_then_replace_keeps_one_file_a_release_and_sweeps_the_old_chunks() -> None:
    v, docs = _vault()
    await _put(v, RID, b"first pages")
    old = _chunks(docs)
    await _put(v, RID, b"fuller pages")
    assert await v.read(UID, RID) == b"fuller pages"
    ix = await v.index(UID)
    assert [f.release for f in ix.files] == [RID] and ix.orphans == () and ix.pending == ()
    assert not set(old) & set(_chunks(docs)) and len(_chunks(docs)) == 1


async def test_without_replace_the_continue_case_would_keep_the_old_file() -> None:
    v, _ = _vault()
    await _put(v, RID, b"a")
    await _put(v, RID2, b"b")
    assert {f.release for f in (await v.index(UID)).files} == {RID, RID2}
    with pytest.raises(LookupError):
        await v.read(UID, RID3)


async def test_the_pages_index_never_touches_r6s_and_47ee8fcs_book_index_still_opens_it() -> None:
    docs = MemoryDocs()
    r6 = DocsBookVault(docs, RING, prefix="jarvis_", clock=FixedClock())
    src = FakeSource()
    rel = src.current()
    assert rel is not None
    await r6.seal(UID, rel, {"book": src.read("source"), "source": src.read("source")}, now=NOW)
    before = dict(docs._data[f"jarvis_book/{UID}"])
    v, _ = _vault(docs)
    await _put(v, rel.id, b"pages")
    after = docs._data[f"jarvis_book/{UID}"]
    assert after == before
    assert OldBookIndex.model_validate_json(BookCrypto(RING).open_index(UID, after["blob"]))


class OldBookIndex(Frozen):
    """A copy of 47ee8fc's `BookIndex` (the rollback reader, M4): extra keys refused."""

    v: Literal[1] = 1
    releases: tuple[SealedRelease, ...] = ()
    pending: tuple[Part, ...] = ()
    orphans: tuple[Part, ...] = ()


async def test_an_attach_in_flight_when_privacy_delete_lands_is_refused_and_its_chunks_go() -> None:
    v, docs = _vault()
    real = v._chunks.put

    async def put_then_delete(uid: str, fid: str, blobs: list[str], at: str) -> None:
        await real(uid, fid, blobs, at)
        await SealState(docs, prefix="jarvis_", clock=FixedClock()).set(UID, "held", RID)

    v._chunks.put = put_then_delete  # type: ignore[method-assign]
    with pytest.raises(SealHeld):
        await _put(v, RID, b"pages")
    assert _chunks(docs) == [] and (await v.index(UID)).files == ()


async def test_an_attach_past_the_storage_limit_counts_r6s_total_and_the_pages_files() -> None:
    v, _ = _vault()
    await _put(v, RID, b"x" * 400, limit_bytes=1_000, others_bytes=500)
    with pytest.raises(BookOff):
        await _put(v, RID2, b"y" * 200, limit_bytes=1_000, others_bytes=500)
    await _put(v, RID, b"z" * 450, limit_bytes=1_000, others_bytes=500)  # a replace frees its own


async def test_a_tampered_pages_index_fails_closed_and_delete_all_removes_everything() -> None:
    v, docs = _vault()
    await _put(v, RID, b"pages")
    path = f"jarvis_book_pages/{UID}"
    good = dict(docs._data[path])
    docs._data[path] = {**good, "blob": good["blob"][:-4] + "AAAA"}
    with pytest.raises(VaultTampered):
        await v.read(UID, RID)
    docs._data[path] = good
    assert await v.delete_all(UID) == 1
    assert _chunks(docs) == [] and path not in docs._data


# ---- the pages file (D11) ------------------------------------------------------------------------
def _written(page_id: str, text: str = GOOD_DRAFT) -> Any:
    ip = FIXTURE_FACTS.page(page_id)
    assert ip is not None
    parsed = checks.parse(text)
    assert parsed is not None
    return pages.written(ip, parsed, META)


def test_a_pages_file_round_trips_gzipped_under_its_cap() -> None:
    f = PagesFile(
        release=RID,
        pages=(_written("pg_card_c01"),),
        skipped=(Skipped(page="pg_card_c02", why="cap"),),
    )
    data = pages.encode_file(f)
    assert data[:2] == b"\x1f\x8b" and len(data) <= PAGES_FILE_CAP_BYTES
    assert pages.decode_file(data) == f and pages.encode_file(f) == data
    with pytest.raises(ValueError):
        pages.decode_file(b"not gzip")


def test_a_written_page_has_the_six_sections_and_its_code_refs() -> None:
    page = _written("pg_card_c01")
    assert [s.id for s in page.sections] == ["plain", "example", "how", "costs", "fails", "code"]
    assert page.sections[1].heading == "Example (made up)"
    assert page.sections[-1].refs == ("src/jarvis/demo/router.py",) and page.meta == META


# ---- the free carry and the changed pages (D11, D12, H3) ----------------------------------------
def test_a_page_is_changed_when_a_file_it_cites_or_its_card_changes_or_it_is_new() -> None:
    old = carry.tree_of(source_zip())
    same = carry.tree_of(source_zip())
    store = carry.tree_of(source_zip(files({"src/jarvis/demo/store.py": '"""Changed."""\n'})))
    assert carry.changed_ids(FIXTURE_FACTS, KNOWN, old, same) == ()
    moved = carry.changed_ids(FIXTURE_FACTS, KNOWN, old, store)
    assert "pg_card_c02" in moved and "pg_card_c01" not in moved and "pg_module_demo" in moved
    guide = files()["docs/architecture/JARVIS-Architecture.md"].replace("Keeps the demo's", "Keeps")
    card = carry.tree_of(source_zip(files({"docs/architecture/JARVIS-Architecture.md": guide})))
    assert "pg_card_c02" in carry.changed_ids(FIXTURE_FACTS, KNOWN, old, card)
    assert carry.changed_ids(FIXTURE_FACTS, KNOWN[:-1], old, same) == ("pg_service_anthropic",)


def test_the_free_carry_refills_unchanged_pages_and_marks_changed_ones_waiting() -> None:
    template = _written(
        "pg_card_c01", GOOD_DRAFT.replace("Nothing:", "{{fact:cards.count}} cards:")
    )
    filled = pages.fill_page(template, FIXTURE_FACTS)
    old = PagesFile(
        release=RID,
        pages=(filled, _written("pg_card_c02")),
        templates=(template, _written("pg_card_c02")),
    )
    newer = FIXTURE_FACTS.model_copy(
        update={
            "values": {
                **FIXTURE_FACTS.values,
                "cards.count": FIXTURE_FACTS.values["cards.count"].model_copy(update={"value": 4}),
            }
        }
    )
    out = carry.carry(RID2, newer, old, changed={"pg_card_c02"})
    by = {p.id: p for p in out.pages}
    assert out.release == RID2 and "4 cards:" in by["pg_card_c01"].sections[3].text
    assert by["pg_card_c01"].meta == META and not by["pg_card_c01"].changed
    assert by["pg_card_c02"].changed and by["pg_card_c02"].meta is None
    assert CHANGED_WAITING in by["pg_card_c02"].sections[0].text
    assert [t.id for t in out.templates] == ["pg_card_c01"]


# ---- the sweep (D11) -----------------------------------------------------------------------------
async def test_the_sweep_drops_files_whose_release_left_r6s_index_but_keeps_the_carry_source() -> (
    None
):
    v, _ = _vault()
    for rid in (RID, RID2, RID3):
        await _put(v, rid, rid.encode())
    assert await sweep.sweep(v, UID, kept={RID3}) == 2
    assert {f.release for f in (await v.index(UID)).files} == {RID3}
    assert await sweep.sweep(v, UID, kept={"8080808"}) == 0  # the newest: the next carry's source
    assert await sweep.sweep(v, UID, kept=set()) == 1  # R6's index is empty: every one goes
    assert (await v.index(UID)).files == ()
