# tests/test_vitals_job_brief.py -- R4 D14 (tick job) and the brief's Vitals section.
from __future__ import annotations

import pytest
from vitals_fakes import OTHER, UID, FakeBilling, Rig, key, usage_view

from jarvis.config import Settings
from jarvis.ticks import TickJob, run_jobs
from jarvis.vitals.brief import MAX_LINES, vitals_lines
from jarvis.vitals.job import JOB_NAME, VitalsJob


async def test_job_is_a_tick_job_with_a_bounded_budget() -> None:
    job = VitalsJob(Rig().svc, Rig().notifier)

    assert isinstance(job, TickJob) and job.name == JOB_NAME and 0 < job.budget_s <= 60


async def test_job_alerts_every_owner_once_per_crossing() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("a", limit=10, used=10))
    await rig.svc.set_key(OTHER, key("b", limit=10, used=9))
    job = VitalsJob(rig.svc, rig.notifier)

    first = await job.run([UID, OTHER])
    second = await job.run([UID, OTHER])

    assert first == {"owners": 2, "alerts": 2, "failed": 0}
    assert second["alerts"] == 0
    assert sorted(rig.notifier.kinds) == ["vitals_critical", "vitals_warn"]


async def test_one_owners_failure_does_not_stop_the_next() -> None:
    rig = Rig()
    await rig.svc.set_key(OTHER, key("b", limit=10, used=10))
    job = VitalsJob(rig.svc, rig.notifier)

    counts = await job.run(["../bad", OTHER])

    assert counts["failed"] == 1 and counts["alerts"] == 1


async def test_disabled_setting_makes_the_job_a_no_op() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("a", limit=10, used=10))
    job = VitalsJob(rig.svc, rig.notifier, settings=Settings(vitals_enabled=False))

    assert await job.run([UID]) == {"owners": 0, "alerts": 0, "failed": 0}
    assert rig.notifier.sent == []


async def test_tick_runs_the_job_and_reports_ok() -> None:
    rig = Rig()

    assert await run_jobs([VitalsJob(rig.svc, rig.notifier)], [UID]) == {JOB_NAME: "ok"}


async def test_tick_reports_failed_when_an_owner_fails() -> None:
    rig = Rig()

    assert await run_jobs([VitalsJob(rig.svc, rig.notifier)], ["../bad"]) == {JOB_NAME: "failed"}


# ---- brief --------------------------------------------------------------------------------


async def test_brief_lists_amber_and_red_then_the_spend_in_rupees() -> None:
    rig = Rig(billing=FakeBilling(usage_view(120, 500)))
    await rig.svc.set_key(UID, key("a", label="Alpha key", limit=10, used=9))
    await rig.svc.set_key(UID, key("b", label="Beta key", expires_in_days=-1))

    lines = await vitals_lines(rig.svc, UID)

    assert lines[0].startswith("Red: Beta key") and lines[1].startswith("Amber: Alpha key")
    assert lines[-1] == "AI spend: ₹120 of ₹500 this month"
    assert all("$" not in x for x in lines)


async def test_brief_with_everything_fine_is_just_the_spend_line() -> None:
    rig = Rig()

    assert await vitals_lines(rig.svc, UID) == ["AI spend: ₹100 of ₹500 this month"]


async def test_brief_is_empty_when_nothing_is_readable() -> None:
    rig = Rig(billing=FakeBilling(down=True))

    assert await vitals_lines(rig.svc, UID) == []


async def test_brief_caps_the_number_of_lines() -> None:
    rig = Rig()
    for i in range(MAX_LINES + 4):
        await rig.svc.set_key(UID, key(f"k{i}", limit=10, used=10))

    lines = await vitals_lines(rig.svc, UID)

    assert len(lines) <= MAX_LINES + 2  # + "and N more" + spend
    assert any("more" in x for x in lines)


async def test_brief_swallows_storage_trouble() -> None:
    rig = Rig()

    async def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("x")

    rig.store.list_manual = boom  # type: ignore[method-assign]

    assert await vitals_lines(rig.svc, UID) == []


@pytest.mark.parametrize("uid", ["../x", ""])
async def test_brief_bad_owner_is_empty(uid: str) -> None:
    assert await vitals_lines(Rig().svc, uid) == []
