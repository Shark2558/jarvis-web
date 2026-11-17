# tests/test_r131_a_privacy.py -- R13.1 Part A, D16 (OPS-05's server half): Part A's Privacy rows,
# on `WardrobePart.privacy` (never `data`, M4): `tryon_figure` "Your measurements and your 3D
# figure" (count, export, delete with a confirm), `tryon_all` "All your try-on data" (passkey;
# OPS-05, through the existing PrivacyService and its IRREVERSIBLE audit line) and `tryon_device`
# (nothing kept on this device). `erase_all`: C's pictures, garment photos, his photo and his YES
# through C's `seeme` service (else by path), then `tryon/{uid}` LAST; the spend stays; the
# wardrobe catalog is untouched. Off (no key): I0's stand-ins, found and deleted by path.
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from r131_fakes_a import UID, AWorld, T, a_world, build_tryon, seeme_docs, seeme_paths

from jarvis.core.guardrails import ActionRisk
from jarvis.keyring import Keyring
from jarvis.privacy.ports import PrivacyRegistry
from jarvis.privacy.service import CONFIRM_WORD, PrivacyService
from jarvis.tools.audit import AuditLog
from jarvis.wardrobe.catalog.store import WardrobeUnavailable as WardrobeDown
from jarvis.wardrobe.kept import WardrobeUnavailable
from jarvis.wardrobe.tryon import erase, kept
from jarvis.wardrobe.tryon.http import AssetChoice, ConfirmSlot, SavedIn, SavedLook

PREFIX = "jarvis_"
FIGURE = f"{PREFIX}tryon/{UID}"
SPEND = f"{PREFIX}tryon_spend/{UID}_2026-11"


def _rows(a: AWorld) -> dict[str, Any]:
    return {r.id: r for r in a.part.privacy}


async def _figure(a: AWorld) -> None:
    """His measurements (two versions and a draft), one figure choice, one saved comparison."""
    s = a.service
    await s.put_body(UID, {"height": 172})
    await s.use_body(UID)
    await s.put_body(UID, {"height": 178, "waist": 84})
    await s.choose(UID, T.striped, AssetChoice(piece=T.striped, template="shirt"))
    look = SavedLook(slots=(ConfirmSlot(slot="top", piece=T.white),))
    await s.save(UID, SavedIn(looks=(look,)))


def _service(a: AWorld, audit: AuditLog | None = None) -> PrivacyService:
    reg = PrivacyRegistry()
    for r in a.part.privacy:
        reg.register(r)
    return PrivacyService(reg, audit=audit)


async def _delete(svc: PrivacyService, rid: str, **kw: Any) -> Any:
    view = next(c for c in (await svc.view(UID)).categories if c.id == rid)
    return await svc.delete(UID, rid, rev=view.rev, confirm=kw.get("confirm", CONFIRM_WORD),
                            proof=None, fresh_left_s=60)  # fmt: skip


async def test_a_offers_its_three_rows_in_the_try_on_section_on_privacy_only() -> None:
    a = await a_world()
    assert [r.id for r in a.part.privacy] == [kept.FIGURE_ID, kept.ALL_ID, kept.DEVICE_ID]
    assert {r.section for r in a.part.privacy} == {kept.SECTION} and a.part.data == ()
    labels = {r.id: r.label for r in a.part.privacy}
    assert labels[kept.FIGURE_ID] == kept.SPECS[kept.FIGURE_ID].label
    assert labels[kept.ALL_ID] == kept.SPECS[kept.ALL_ID].label
    assert isinstance(_rows(a)[kept.DEVICE_ID], kept.DeviceRow)


async def test_the_figure_row_says_nothing_kept_yet_and_offers_no_delete() -> None:
    a = await a_world()
    seen = await _rows(a)[kept.FIGURE_ID].describe(UID)
    assert seen.count == 0 and seen.note == kept.NOTHING_YET and seen.delete == "none"


async def test_the_figure_row_counts_exports_and_deletes_with_a_confirm() -> None:
    a = await a_world()
    await _figure(a)
    row = _rows(a)[kept.FIGURE_ID]
    seen = await row.describe(UID)
    assert seen.count == 4 and seen.delete == "confirm" and seen.encrypted_by_jarvis
    got = await row.export(UID)
    assert got["measurements"]["current"]["height"] == 172  # his own export: his own numbers
    assert got["measurements"]["draft"]["typed"] == ["height", "waist"]
    assert got["figure_choices"] == {T.striped: {"template": "shirt", "texture_view": None,
                                                 "card_only": False}}  # fmt: skip
    assert [s["looks"][0]["slots"] for s in got["saved"]] == [[{"slot": "top", "piece": T.white}]]
    deleted = await _delete(_service(a), kept.FIGURE_ID, confirm=None)
    assert deleted.deleted == 1 and await a.docs.get(FIGURE) is None


async def test_the_figure_rows_count_and_export_skip_choices_of_pieces_gone_or_private() -> None:
    a = await a_world()
    await _figure(a)
    row = _rows(a)[kept.FIGURE_ID]
    await a.w.edit(T.striped, private=True)  # made private since his figure choice (review F9)
    seen = await row.describe(UID)
    assert seen.count == 3  # the current one, the draft and a saved comparison: no choice
    assert (await row.export(UID))["figure_choices"] == {}
    assert T.striped in (await a.service.store.read(UID)).assets  # kept, only not counted

    async def down(uid: str) -> Any:
        raise WardrobeDown("R13's store is down")

    a.store.view = down  # R13 can't be read: the entries as stored
    assert (await row.describe(UID)).count == 4
    assert T.striped in (await row.export(UID))["figure_choices"]


async def test_a_present_but_empty_figure_document_can_still_be_deleted() -> None:
    a = await a_world()
    await a.service.put_body(UID, {"height": 172})
    await a.service.drop_draft(UID)  # a draft dropped with no current one: an empty document
    assert await a.docs.get(FIGURE) is not None
    seen = await _rows(a)[kept.FIGURE_ID].describe(UID)
    assert seen.count == 0 and seen.delete == "confirm"  # not "none": it is on disk
    deleted = await _delete(_service(a), kept.FIGURE_ID, confirm=None)
    assert deleted.deleted == 1 and await a.docs.get(FIGURE) is None


async def test_the_figure_rows_rev_moves_when_the_data_does() -> None:
    a = await a_world()
    await _figure(a)
    row = _rows(a)[kept.FIGURE_ID]
    before = (await row.describe(UID)).rev
    await a.service.drop_draft(UID)
    assert (await row.describe(UID)).rev != before


async def test_a_figure_that_cant_be_opened_cant_be_checked_but_can_be_deleted() -> None:
    a = await a_world()
    await _figure(a)
    other = build_tryon(replace(a.ctx, keyring=Keyring(bytes(range(1, 33)))))  # the key changed
    row = {r.id: r for r in other.privacy}[kept.FIGURE_ID]
    seen = await row.describe(UID)
    assert seen.note == kept.CANT_OPEN and seen.count is None and seen.delete == "confirm"
    with pytest.raises(WardrobeUnavailable):
        await row.export(UID)
    assert await row.delete(UID) == 1 and await a.docs.get(FIGURE) is None


async def test_ops05_all_counts_every_try_on_document_but_the_spend() -> None:
    a = await a_world(seeme=True)
    await _figure(a)
    await seeme_docs(a.docs)
    seen = await _rows(a)[kept.ALL_ID].describe(UID)
    assert seen.count == 5 and seen.delete == "passkey" and seen.delete_count == 5
    assert kept.BACKUP_WORDS in seen.retention


async def test_ops05_the_privacy_delete_erases_cs_half_first_then_the_figure_last() -> None:
    a = await a_world(seeme=True)
    await _figure(a)
    paths = await seeme_docs(a.docs)
    assert a.seeme is not None
    figure_then: list[bool] = []
    real = a.seeme.erase

    async def watched(uid: str) -> int:
        figure_then.append(await a.docs.get(FIGURE) is not None)
        return await real(uid)

    a.seeme.erase = watched  # type: ignore[method-assign]
    view_before, crops_before = await a.view(), dict(a.vault.crops)
    audit = AuditLog()
    got = await _delete(_service(a, audit), kept.ALL_ID)
    assert got.deleted == 5 and got.remaining == 0
    assert figure_then == [True]  # C's half went while the figure was still there: it went last
    for p in paths:
        assert (await a.docs.get(p) is None) is (p != SPEND), p  # the spend stays (his cap)
    assert await a.docs.get(FIGURE) is None
    after = await a.view()
    assert after.rev == view_before.rev and after.pieces == view_before.pieces  # the catalog
    assert a.vault.crops == crops_before  # the wardrobe's photos untouched
    entry = [e for e in (await audit.tail(50)).entries if e.tool == "privacy_delete"][-1]
    assert entry.risk is ActionRisk.IRREVERSIBLE and "tryon_all" in entry.detail


async def test_ops05_without_cs_service_its_half_goes_by_path() -> None:
    a = await a_world(seeme=False)
    await _figure(a)
    paths = await seeme_docs(a.docs)
    assert await erase.erase_all(a.ctx, a.service.store, UID) == 5
    assert [p for p in paths if await a.docs.get(p) is not None] == [SPEND]
    assert await a.docs.get(FIGURE) is None


async def test_ops05_a_failing_c_still_has_its_half_erased_by_path() -> None:
    a = await a_world(seeme=True)
    assert a.seeme is not None
    a.seeme.fail = True
    await _figure(a)
    paths = await seeme_docs(a.docs)
    await erase.erase_all(a.ctx, a.service.store, UID)
    assert a.seeme.calls == [UID]
    assert [p for p in paths if await a.docs.get(p) is not None] == [SPEND]
    assert await a.docs.get(FIGURE) is None


async def test_ops05_all_with_nothing_kept_says_so() -> None:
    a = await a_world()
    seen = await _rows(a)[kept.ALL_ID].describe(UID)
    assert seen.count == 0 and seen.note == kept.NOTHING_YET and seen.delete == "none"


async def test_off_with_no_key_the_rows_are_the_stand_ins_and_still_delete_by_path() -> None:
    a = await a_world()
    await _figure(a)
    await seeme_docs(a.docs)
    off = build_tryon(replace(a.ctx, keyring=None))  # the same disk, no key
    assert off.ready.startswith("Off") and off.services == {}
    rows = {r.id: r for r in off.privacy}
    assert list(rows) == [kept.FIGURE_ID, kept.ALL_ID, kept.DEVICE_ID]
    assert (await rows[kept.FIGURE_ID].describe(UID)).note == kept.CANT_OPEN
    assert await rows[kept.ALL_ID].delete(UID) == 5
    assert [p for p in seeme_paths() if await a.docs.get(p) is not None] == [SPEND]


async def test_no_storage_offers_no_rows() -> None:
    a = await a_world(docs_off=True)
    assert a.part.privacy == () and a.part.ready.startswith("Off")
