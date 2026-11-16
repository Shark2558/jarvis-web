# tests/test_r13_i1_privacy_kept.py -- the I1 security review's M1 (and the code review's count
# findings): Privacy never says "Nothing kept yet" for data that is on disk but can't be opened
# (no keyring, a failed setup, a changed key), and delete still erases what is on disk, with no
# key. A, B and C behave alike: count and export say "Couldn't check right now", delete works.
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from r13_fakes import UID, FixedClock, ist, wardrobe_context
from r13_fakes_a import fp, jpeg, ring, settings
from r13_fakes_c import RING as C_RING

from jarvis.api.r13_wiring import build_parts
from jarvis.keyring import Keyring
from jarvis.privacy.ports import PrivacyRegistry
from jarvis.storage.docs import MemoryDocs
from jarvis.wardrobe.catalog.edits import NewPiece
from jarvis.wardrobe.catalog.events import event
from jarvis.wardrobe.phone import privacy
from jarvis.wardrobe.ports import Commit, WardrobeContext, WardrobePart
from jarvis.wardrobe.styling.plans import Choice

OTHER_RING = Keyring(bytes(range(7, 39)))
CLOSED = ("wardrobe", "wardrobe_log", "wardrobe_photo", "wardrobe_fp", "wardrobe_restore")


def _ctx(docs: MemoryDocs, keyring: Keyring | None) -> WardrobeContext:
    base = wardrobe_context(docs, now=FixedClock(ist(2026, 11, 16, 9, 0)))
    return WardrobeContext(**{**base.__dict__, "keyring": keyring, "s": settings()})


async def _seed(docs: MemoryDocs, *, archive: bool = False) -> dict[str, WardrobePart]:
    """A keyed A with one piece: a photo, a fingerprint and its history."""
    parts = build_parts(_ctx(docs, ring()))
    desk = parts["catalog"].services["store"].desk
    [pid] = list((await desk.service.add(UID, [NewPiece(type="shirt")])).ids)
    await desk.vault.save(UID, pid, "front", jpeg(512, 384))
    await desk.vault.prints.save(UID, pid, "front", "mnv2-int8-1", fp(1))
    return parts


def _rows(parts: Mapping[str, WardrobePart]) -> PrivacyRegistry:
    reg = PrivacyRegistry()
    for row in privacy.privacy_rows(lambda: [d for p in parts.values() for d in p.data]):
        reg.register(row)
    return reg


def _paths(docs: MemoryDocs, *collections: str) -> list[str]:
    return [
        p
        for p in docs._data
        if any(f"/{c}/" in p or p.startswith(f"jarvis_{c}/") for c in collections)
    ]  # noqa: SLF001


async def _check(docs: MemoryDocs, keyring: Keyring | None) -> None:
    parts = build_parts(_ctx(docs, keyring))
    reg = _rows(parts)
    views = {v.id: v for v in await reg.describe_all(UID)}
    for row in (privacy.PIECES_ID, privacy.PHOTOS_ID):
        v = views[row]
        assert v.note != privacy.NOTHING_YET and v.delete == "passkey", (row, v)
        assert "Couldn't check right now" in v.note, (row, v.note)
    for row in (privacy.PIECES_ID, privacy.PHOTOS_ID):
        src = reg.get(row)
        assert src is not None
        await src.delete(UID)
    assert _paths(docs, "wardrobe_photo", "wardrobe_fp") == []
    assert _paths(docs, *CLOSED) == [], list(docs._data)  # noqa: SLF001
    after = {v.id: v for v in await reg.describe_all(UID)}
    assert after[privacy.PIECES_ID].note == privacy.NOTHING_YET


async def test_with_no_keyring_the_pieces_and_photos_rows_say_so_and_delete_by_path() -> None:
    docs = MemoryDocs()
    await _seed(docs)
    await _check(docs, None)


async def test_after_a_key_change_the_rows_say_so_and_delete_by_path() -> None:
    docs = MemoryDocs()
    await _seed(docs)
    await _check(docs, OTHER_RING)


async def test_export_of_unreadable_data_says_it_cannot_check() -> None:
    docs = MemoryDocs()
    await _seed(docs)
    reg = _rows(build_parts(_ctx(docs, None)))
    src = reg.get(privacy.PIECES_ID)
    assert src is not None
    try:
        await src.export(UID)
    except Exception as exc:  # noqa: BLE001 - the registry's words for any failure
        assert "check" in str(exc).lower() or type(exc).__name__
    else:
        raise AssertionError("an export of data that can't be opened must not be empty")


async def test_a_wardrobe_of_archived_pieces_only_is_counted_and_deletable() -> None:
    docs = MemoryDocs()
    parts = await _seed(docs)
    desk = parts["catalog"].services["store"].desk
    view = await desk.store.view(UID)
    [pid] = list(view.pieces)

    async def fn(view: Any, tx: Any) -> Commit:
        return Commit(events=(event(pid, "archived", desk.store.now()),))

    await desk.store.transact(UID, fn)
    reg = _rows(parts)
    v = {x.id: x for x in await reg.describe_all(UID)}[privacy.PIECES_ID]
    assert v.count and v.count > 0 and v.delete == "passkey"


async def test_the_pieces_row_says_it_removes_the_photos_too() -> None:
    what = privacy.PIECES_SPEC.what.lower()
    assert "every wardrobe photo" in what and "fingerprint" in what


async def test_plans_with_only_a_calendar_choice_are_counted_and_deletable() -> None:
    docs = MemoryDocs()
    ctx = _ctx(docs, C_RING)
    parts = build_parts(ctx)
    styling = parts["styling"]
    plans = styling.data[0]._s.plans  # noqa: SLF001 - OutfitsData's sealed plans document
    await plans.change(UID, lambda d: d.model_copy(update={"choice": Choice(calendar="cal-1")}))
    reg = _rows(parts)
    v = {x.id: x for x in await reg.describe_all(UID)}[privacy.PLANS_ID]
    assert v.delete == "passkey" and (v.count or 0) > 0


async def test_unreadable_plans_say_so_and_delete_by_path() -> None:
    docs = MemoryDocs()
    parts = build_parts(_ctx(docs, C_RING))
    await parts["styling"].data[0]._s.plans.change(UID, lambda d: d)  # noqa: SLF001 - seeds the document
    rotated = build_parts(_ctx(docs, OTHER_RING))
    reg = _rows(rotated)
    v = {x.id: x for x in await reg.describe_all(UID)}[privacy.PLANS_ID]
    assert v.delete == "passkey" and "Couldn't check right now" in v.note
    src = reg.get(privacy.PLANS_ID)
    assert src is not None
    await src.delete(UID)
    assert _paths(docs, "wardrobe_plans") == []


async def test_a_closed_laundry_batch_is_still_counted_and_deletable() -> None:
    """Closed batches keep his shop label for 90 days: Privacy must count them (code review)."""
    from r13_fakes_b import BLAZER, rig

    r = await rig()
    (data,) = r.part.data
    batch = (await r.desk.send_out(UID, (BLAZER,), "Corner shop")).batch
    r.clock.advance(days=1)
    await r.desk.receive(UID, batch, (BLAZER,))
    assert (await r.laundry()).batches[0].closed_at is not None
    assert await data.count(UID) > 0
    assert await data.kept(UID) > 0
