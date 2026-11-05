# tests/test_vault_inbox_job.py -- R2 D9: InboxJob as a tick job: imports for owners with a folder,
# nothing (no Drive call) for others, one owner's failure never stops the next, runs under run_jobs.
from __future__ import annotations

from drive_fakes import PDF
from inbox_fakes import OWNER, PDF_BYTES, UID, rig

from jarvis.ticks import TickJob, run_jobs
from jarvis.vault_inbox.job import JOB_NAME, InboxJob

SWEEPS = {
    "memory",
    "documents",
    "undo",
    "outside_tasks",
    "permissions",
    "telegram",
    "activity",
    "web",
}


async def test_job_is_a_tick_job_with_a_unique_name() -> None:
    job = InboxJob(rig().inbox)
    assert isinstance(job, TickJob) and job.name == JOB_NAME and job.name not in SWEEPS
    assert 0 < job.budget_s <= 60


async def test_job_imports_for_an_owner_with_a_folder() -> None:
    r = rig()
    await r.inbox.pick(UID, OWNER, "inbox1")
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    out = await run_jobs([InboxJob(r.inbox)], [UID])
    assert out == {JOB_NAME: "ok"} and len(r.intake.calls) == 1


async def test_job_makes_no_drive_call_without_a_folder() -> None:
    r = rig()
    counts = await InboxJob(r.inbox).run([UID, "u_other"])
    assert counts["imported"] == 0 and r.drive.requests == []


async def test_one_owner_failing_does_not_stop_the_next() -> None:
    r = rig()
    await r.inbox.pick(UID, OWNER, "inbox1")
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    counts = await InboxJob(r.inbox).run(["../bad", UID])
    assert counts["failed"] == 1 and counts["imported"] == 1


async def test_allowed_gate_skips_owners_whose_drive_row_is_never() -> None:
    r = rig()
    await r.inbox.pick(UID, OWNER, "inbox1")
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)

    async def no(_: str) -> bool:
        return False

    counts = await InboxJob(r.inbox, allowed=no).run([UID])
    assert counts["owners"] == 0 and r.intake.calls == []
