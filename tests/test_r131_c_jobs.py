# tests/test_r131_c_jobs.py -- R13.1 Part C: `seeme_daily` on the morning tick
# (docs/plans/r13-1-try-on.md D14, D18): pictures past their 30 days (unless Keep) and of pieces
# now private or gone, garment photos past their time and shown by no kept picture, holds older
# than an hour, spend months past 13; by path, so it needs no key. Tested at 23:30 and 00:30 IST
# and across 28 May 2027 (no date bombs: every clock is fixed).
from __future__ import annotations

from datetime import timedelta

from r131_fakes import UID, T, ist
from r131_fakes_c import ask, ready_world

from jarvis.storage.docs import Set
from jarvis.wardrobe.seeme.jobs import SeeMeDaily, months_back
from jarvis.wardrobe.seeme.part import build


def _job(sw) -> SeeMeDaily:  # type: ignore[no-untyped-def]
    [job] = build(sw.ctx).daily_jobs
    assert isinstance(job, SeeMeDaily)
    return job


async def _picture(svc, g, pieces=(), n: int = 1):  # type: ignore[no-untyped-def]
    shown = (await svc.estimate(UID, g.id, list(pieces))).typical_inr
    return await svc.press(UID, ask(g.id, tuple(pieces), inr=shown, n=n))


async def test_a_picture_goes_after_30_days_at_2330_and_0030_ist() -> None:
    made = ist(2026, 11, 17, 23, 30)
    sw, svc, g = await ready_world(at=made)
    pic = await _picture(svc, g)
    sw.w.clock.set(ist(2026, 12, 17, 23, 29))  # 30 days less a minute: kept
    assert (await _job(sw).run([UID]))["pictures"] == 0
    sw.w.clock.set(ist(2026, 12, 18, 0, 30))  # past its 30 days, the next IST day
    counts = await _job(sw).run([UID])
    assert counts["pictures"] == 1 and await svc.picture(UID, pic.id) is None
    assert counts["garments"] == 1  # its garment photo is past its time too, and shown by none


async def test_keep_keeps_the_picture_and_its_garment_photo() -> None:
    sw, svc, g = await ready_world()
    pic = await _picture(svc, g)
    await svc.keep(UID, pic.id, True)
    sw.w.clock.set(ist(2027, 3, 1, 9, 0))
    counts = await _job(sw).run([UID])
    assert counts["pictures"] == 0 and counts["garments"] == 0
    assert await svc.picture(UID, pic.id) is not None
    assert await svc.garment_photo(UID, g.id) is not None


async def test_a_piece_made_private_or_gone_takes_its_pictures_with_it() -> None:
    sw, svc, g = await ready_world()
    pic = await _picture(svc, g, (T.jeans,))
    await svc.keep(UID, pic.id, True)  # even a kept one
    await sw.w.edit(T.jeans, private=True)
    assert (await _job(sw).run([UID]))["pictures"] == 1
    assert await svc.picture(UID, pic.id) is None


async def test_a_picture_of_a_piece_made_private_is_gone_at_once_not_the_next_morning() -> None:
    # integrated security review finding 4: until the morning job it stayed listed, served and in
    # the Privacy export, naming the piece in fixed words (D14: "when a piece in it is later made
    # private"); now the overview, the picture route and the export drop it first
    from jarvis.wardrobe.seeme.privacy import rows

    sw, svc, g = await ready_world()
    pic = await _picture(svc, g, (T.jeans,))
    other = await _picture(svc, g, (), n=2)  # a picture of the new garment alone stays
    await sw.w.edit(T.jeans, private=True)
    assert [p.id for p in (await svc.overview(UID)).pictures] == [other.id]
    assert await svc.picture(UID, pic.id) is None and await svc.picture(UID, other.id)
    [row] = [r for r in rows(svc) if r.spec.id == "tryon_pictures"]
    exported = await row.export(UID)
    assert [p["id"] for p in exported["pictures"]] == [other.id]
    assert [i for i, _ in await svc.kit.pictures.rows(UID)] == [other.id]  # deleted by path


async def test_an_old_hold_is_settled_at_its_hold() -> None:
    sw, svc, g = await ready_world()
    hold = await svc.kit.cap.reserve(UID, "tq_00000000000000aa", 11.22, 300)
    assert hold is not None
    sw.w.clock.set(sw.w.clock() + timedelta(hours=1, minutes=1))
    assert (await _job(sw).run([UID]))["holds"] == 1
    assert (await svc.kit.cap.month(UID)).spent_inr == 11.22


async def test_spend_months_past_13_are_forgotten() -> None:
    sw, svc, g = await ready_world()
    prefix = sw.ctx.s.firestore_prefix
    for month in ("2025-09", "2025-10", "2025-11"):
        await sw.docs.write([Set(f"{prefix}tryon_spend/{UID}_{month}",
                                 {"owner": UID, "month": month, "spent_inr": 1.0})])  # fmt: skip
    assert months_back("2026-11", 13) == "2025-10" and months_back("2027-01", 13) == "2025-12"
    assert (await _job(sw).run([UID]))["months"] == 1  # 2025-09 only
    assert await sw.docs.get(f"{prefix}tryon_spend/{UID}_2025-10") is not None
    assert await sw.docs.get(f"{prefix}tryon_spend/{UID}_prefs") is None  # never his settings


async def test_across_28_may_2027_the_job_still_forgets_on_time() -> None:
    sw, svc, g = await ready_world(at=ist(2027, 5, 1, 9, 0))
    pic = await _picture(svc, g)
    sw.w.clock.set(ist(2027, 5, 28, 0, 30))  # the model's end: pictures still forgotten
    view = await svc.overview(UID)
    assert not view.on and view.notice == "Google may retire this image model on 28 May 2027."
    sw.w.clock.set(ist(2027, 6, 1, 0, 30))
    assert (await _job(sw).run([UID]))["pictures"] == 1
    assert await svc.picture(UID, pic.id) is None


async def test_one_owner_failing_never_stops_the_others() -> None:
    sw, svc, g = await ready_world()
    job = _job(sw)

    async def broken(uid: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    real = job.owner
    job.owner = broken  # type: ignore[method-assign]
    assert (await job.run([UID, "other"]))["failed"] == 2
    job.owner = real  # type: ignore[method-assign]
    assert job.name == "seeme_daily" and 0 < job.budget_s <= 30
