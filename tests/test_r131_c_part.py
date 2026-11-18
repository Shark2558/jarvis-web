# tests/test_r131_c_part.py -- R13.1 Part C's join, its three Privacy rows and its half of OPS-05
# (docs/plans/r13-1-try-on.md D16, "Part split" C; BRIEF-C "The join", "Privacy rows"). The part
# passes I0's contract (`api.r13_wiring.check_part`); `erase` removes his pictures, the garment
# photos, his photo and his YES in that order and never the spend. Fixed clocks only.
from __future__ import annotations

import pytest
from r131_fakes import UID, T
from r131_fakes_c import NEW_SHIRT, PERSON, ask, ready_world

from jarvis.api import r13_wiring as wiring
from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs, Set
from jarvis.wardrobe.seeme.part import build
from jarvis.wardrobe.tryon import kept
from jarvis.wardrobe.tryon.ports import SeeMeErase, seeme_service


def _ctx(**kw):  # type: ignore[no-untyped-def]
    from r131_fakes import tryon_context

    return tryon_context(**kw)


# ---- the join -----------------------------------------------------------------------------------
def test_the_part_keeps_the_contract_with_its_job_rows_and_service() -> None:
    part = wiring.check_part("seeme", build(_ctx()))
    assert part.tools == () and part.data == () and part.clock_jobs == ()
    assert [j.name for j in part.daily_jobs] == ["seeme_daily"]
    assert [r.id for r in part.privacy] == ["tryon_photo", "tryon_pictures", "tryon_spend"]
    assert {r.section for r in part.privacy} == {"Try-on"}
    assert set(part.services) == {"seeme"} and isinstance(part.services["seeme"], SeeMeErase)
    assert part.ready == "Ready: See it on me stays off until pictures are set up on this server."
    on = build(_ctx(settings=Settings(_env_file=None, tryon_pictures=True)))  # type: ignore[call-arg]
    assert on.ready == "Ready: See it on me."


def test_without_a_key_only_the_job_and_i0s_stand_ins() -> None:
    ctx = _ctx(keyring=None)
    part = wiring.check_part("seeme", build(ctx))
    assert [j.name for j in part.daily_jobs] == ["seeme_daily"] and part.services == {}
    assert part.privacy == () and part.ready.startswith("off: ")
    joined = wiring._with_kept(part, ctx)  # noqa: SLF001 - the wiring's own branch for C
    assert [r.id for r in joined.privacy] == ["tryon_photo", "tryon_pictures", "tryon_spend"]


def test_without_storage_nothing_is_offered() -> None:
    from dataclasses import replace

    part = build(replace(_ctx(), docs=None))
    assert part.daily_jobs == () and part.privacy == () and part.services == {}


def test_a_service_is_read_late_by_its_one_owner() -> None:
    ctx = _ctx()
    part = build(ctx)
    ctx.state("r13_parts")["seeme"] = part  # type: ignore[index]
    assert seeme_service(ctx) is part.services["seeme"]


# ---- Privacy rows (D16) -----------------------------------------------------------------------
async def test_the_photo_row_exports_when_and_how_big_never_the_photo() -> None:
    sw, svc, g = await ready_world()
    rows = {r.id: r for r in build(sw.ctx).privacy}
    seen = await rows["tryon_photo"].describe(UID)
    assert (
        seen.count == 2
        and seen.delete == "passkey"
        and seen.label == kept.SPECS["tryon_photo"].label
    )
    out = await rows["tryon_photo"].export(UID)
    assert out is not None and out["photo"]["kept"] and out["yes"]["given"]
    assert "blob" not in str(out) and PERSON not in str(out).encode()
    assert await rows["tryon_photo"].delete(UID) == 2
    assert (await svc.overview(UID)).photo.kept is False
    assert (await rows["tryon_photo"].describe(UID)).count == 0


async def test_the_pictures_row_lists_pictures_and_garment_photos_never_their_bytes() -> None:
    sw, svc, g = await ready_world()
    shown = (await svc.estimate(UID, g.id, [])).typical_inr
    pic = await svc.press(UID, ask(g.id, (), inr=shown))
    rows = {r.id: r for r in build(sw.ctx).privacy}
    seen = await rows["tryon_pictures"].describe(UID)
    assert seen.count == 2 and seen.delete == "passkey"
    out = await rows["tryon_pictures"].export(UID)
    assert out is not None and [p["id"] for p in out["pictures"]] == [pic.id]
    assert out["garments"][0]["words"] == "a new navy shirt, not in your wardrobe"
    assert "blob" not in str(out)
    assert await rows["tryon_pictures"].delete(UID) == 2
    assert (await svc.overview(UID)).pictures == ()


async def test_the_spend_row_is_numbers_per_month_and_never_deletable() -> None:
    sw, svc, g = await ready_world()
    shown = (await svc.estimate(UID, g.id, [])).typical_inr
    await svc.press(UID, ask(g.id, (), inr=shown))
    row = {r.id: r for r in build(sw.ctx).privacy}["tryon_spend"]
    seen = await row.describe(UID)
    assert seen.count == 1 and seen.delete == "none"
    out = await row.export(UID)
    assert out is not None and out["months"][0]["month"] == "2026-11"
    assert out["months"][0]["pictures"] == 1
    with pytest.raises(PermissionError):
        await row.delete(UID)


# ---- OPS-05's half: erase (A owns the named test) ---------------------------------------------
async def test_ops05_seeme_erase_removes_pictures_garments_photo_and_yes_in_that_order() -> None:
    sw, svc, g = await ready_world()
    shown = (await svc.estimate(UID, g.id, [T.jeans])).typical_inr
    await svc.press(UID, ask(g.id, (T.jeans,), inr=shown))
    before = await sw.rev()
    log_at = len(sw.docs.log)
    assert await svc.erase(UID) == 4  # a picture, a garment photo, his photo, his YES
    gone = [op.path.split("/")[0].removeprefix("jarvis_") for op in sw.docs.log[log_at:]]
    assert gone == ["tryon_picture", "tryon_garment", "tryon_person", "tryon_consent"]
    assert (await svc.kit.cap.month(UID)).spent_inr > 0  # the spend stays (his cap's record)
    assert await sw.rev() == before  # the wardrobe catalog untouched


async def test_ops05_seeme_after_erase_see_it_on_me_asks_for_a_photo_again() -> None:
    sw, svc, g = await ready_world()
    await svc.erase(UID)
    view = await svc.overview(UID)
    assert view.photo.kept is False and view.consent.given is False and view.pictures == ()
    g2 = await svc.add_garment(UID, "shirt", "navy", NEW_SHIRT)
    from jarvis.wardrobe.seeme.texts import SeeMeRefused

    with pytest.raises(SeeMeRefused) as err:
        await svc.press(UID, ask(g2.id, (), inr=9.0, n=7))
    assert err.value.code == "consent_needed"  # then his photo: nothing goes without both


async def test_ops05_seeme_erase_is_what_kept_erase_seeme_does_by_path() -> None:
    sw, svc, g = await ready_world()
    await svc.press(UID, ask(g.id, (), inr=(await svc.estimate(UID, g.id, [])).typical_inr))
    prefix = sw.ctx.s.firestore_prefix
    copy = MemoryDocs()
    for path, doc in sw.docs._data.items():  # noqa: SLF001 - the same documents, twice
        await copy.write([Set(path, doc)])
    assert await kept.erase_seeme(copy, prefix, UID) == await svc.erase(UID)
