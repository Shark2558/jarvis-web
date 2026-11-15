# tests/test_r13_b_jobs.py -- R13 Part B's `laundry_daily` on the morning tick
# (docs/plans/r13-wardrobe.md D19, D11, data model): `laundry_overdue` once a batch a day when a
# batch is past its `due` or came back short; `wardrobe_review` (info) once a day for checks opened
# before today; claims written before the send and released when the send fails; closed loads and
# batches after 90 days, resolved checks after `wardrobe_review_keep_days`, B's claims after 30
# days. Fixed words only: never his label, the shop's label or a private piece. "Today" is his local
# day (23:30 and 00:30 IST both tested).
from __future__ import annotations

from datetime import date

from r13_fakes import UID, ev, ist
from r13_fakes_b import BLAZER, JACKET, TROUSERS, VEST_A, rig

from jarvis.wardrobe.laundry.holds import admit
from jarvis.wardrobe.laundry.jobs import LaundryDaily


def _job(r) -> LaundryDaily:  # type: ignore[no-untyped-def]
    (job,) = r.part.daily_jobs
    assert isinstance(job, LaundryDaily) and job.name == "laundry_daily" and job.budget_s > 0
    return job


async def _overdue_rig():  # type: ignore[no-untyped-def]
    r = await rig()
    got = await r.desk.send_out(
        UID, (BLAZER, TROUSERS), "Corner dry cleaner", due=date(2026, 11, 18)
    )
    return r, got.batch


async def test_an_overdue_batch_is_told_once_a_day_in_fixed_words() -> None:
    r, _ = await _overdue_rig()
    job = _job(r)
    r.clock.set(ist(2026, 11, 18, 23, 30))  # due today, his time: not overdue yet
    assert (await job.run([UID])).get("overdue", 0) == 0
    r.clock.set(ist(2026, 11, 19, 0, 30))  # past midnight IST (18 Nov, 19:00 UTC): overdue
    counts = await job.run([UID])
    assert counts["overdue"] == 1 and r.notifier.sent == [
        (UID, "laundry_overdue", "2 pieces at an outside laundry are a day overdue: details in "
         "Helpers, Wardrobe."),
    ]  # fmt: skip
    r.clock.advance(hours=6)
    await job.run([UID])
    assert len(r.notifier.sent) == 1  # once a batch a day
    r.clock.set(ist(2026, 11, 20, 7, 0))
    await job.run([UID])
    assert r.notifier.sent[-1][2] == (
        "2 pieces at an outside laundry are 2 days overdue: details in Helpers, Wardrobe."
    )


async def test_a_short_batch_is_told_and_a_batch_without_a_due_date_is_never_overdue() -> None:
    r = await rig()
    batch = (await r.desk.send_out(UID, (BLAZER, JACKET), "Laundry shop")).batch
    r.clock.advance(days=1)
    await r.desk.receive(UID, batch, (BLAZER,))
    r.clock.set(ist(2026, 12, 30, 7, 0))
    await _job(r).run([UID])
    r.clock.set(ist(2026, 12, 31, 7, 0))
    await _job(r).run([UID])  # told once: no due date, so never daily
    assert r.notifier.sent == [
        (UID, "laundry_overdue", "A laundry batch came back short: 1 piece is still out. "
         "Details in Helpers, Wardrobe."),
    ]  # fmt: skip


async def test_open_checks_are_told_the_morning_after_once_a_day() -> None:
    r = await rig()
    await r.commit(admit(ev(VEST_A, "deposited", r.clock(), source="camera")))
    await r.commit(ev(JACKET, "missing", r.clock()))
    job = _job(r)
    r.clock.set(ist(2026, 11, 16, 23, 30))
    await job.run([UID])
    assert r.notifier.sent == []  # opened today: not the morning after yet
    r.clock.set(ist(2026, 11, 17, 0, 30))
    counts = await job.run([UID])
    assert counts["review"] == 1 and r.notifier.sent == [
        (UID, "wardrobe_review", "2 pieces wait for a quick check in Helpers, Wardrobe."),
    ]
    await job.run([UID])
    assert len(r.notifier.sent) == 1
    assert all("private" not in m and "Corner" not in m for _, _, m in r.notifier.sent)


async def test_a_failed_send_releases_its_claim_and_is_tried_again() -> None:
    r, _ = await _overdue_rig()
    r.clock.set(ist(2026, 11, 19, 9, 0))
    r.notifier.fail = True
    counts = await _job(r).run([UID])
    assert counts.get("failed", 0) == 0 and counts["not_sent"] == 1
    r.notifier.fail = False
    await _job(r).run([UID])
    assert [k for _, k, _ in r.notifier.sent] == ["laundry_overdue"]


async def test_without_a_notifier_nothing_is_claimed() -> None:
    r, _ = await _overdue_rig()
    r.notifier.off = True  # the app has no notifier yet
    r.clock.set(ist(2026, 11, 19, 9, 0))
    counts = await _job(r).run([UID])
    assert counts["no_notifier"] == 1
    assert not [p for p in r.docs._data if "wardrobe_told" in p]  # noqa: SLF001


async def test_old_records_and_claims_are_swept() -> None:
    r = await rig()
    batch = (await r.desk.send_out(UID, (BLAZER,), "Dry cleaner")).batch
    await r.desk.receive(UID, batch, (BLAZER,))
    await r.desk.move(UID, "basket", pieces=(JACKET,))
    load = (await r.desk.move(UID, "load", pieces=(JACKET,))).load
    await r.desk.move(UID, "ready", pieces=(JACKET,), load=load)
    await r.commit(ev(TROUSERS, "missing", r.clock()))
    (entry,) = await r.open_entries()
    await r.desk.resolve(UID, entry.id, "these")
    await r.desk.store.claim(UID, "laundry_review_2026-11-16", r.clock())
    job = _job(r)
    r.clock.advance(days=31)
    await job.run([UID])
    assert (await r.review()).entries == ()  # resolved 31 days ago: gone
    assert len((await r.laundry()).loads) == 1  # closed 31 days ago: kept for 90
    assert not [p for p in r.docs._data if p.endswith("laundry_review_2026-11-16")]  # noqa: SLF001
    r.clock.advance(days=60)
    await job.run([UID])
    laundry = await r.laundry()
    assert laundry.loads == () and laundry.batches == ()


async def test_one_owners_failure_stops_no_one_and_no_key_is_off() -> None:
    r = await rig()
    counts = await _job(r).run(["bad/owner", UID])
    assert counts["failed"] == 1
    off = await rig(keyring=False)
    assert await _job(off).run([UID]) == {"off": 1}


def test_the_job_has_a_name_the_wiring_accepts_and_a_bounded_budget() -> None:
    assert LaundryDaily.name == "laundry_daily" and 0 < LaundryDaily.budget_s <= 60
