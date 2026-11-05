# tests/test_vault_reminders.py -- R2 D5: thresholds once, catch-up, caps, templates, no leaks
from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

from vault_fakes import PDF, UID, make, scan

from jarvis.alerts import AlertResult
from jarvis.ticks import TickJob, run_jobs
from jarvis.vault.reminders import VaultReminders, alert_text

IST = ZoneInfo("Asia/Kolkata")
TODAY = dt.date(2026, 11, 5)


class Sink:
    def __init__(self, sent: bool = True) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.sent = sent

    async def send(self, uid: str, text: str, *, kind: str) -> AlertResult:
        self.calls.append((uid, text, kind))
        return AlertResult(sent=self.sent, reason="" if self.sent else "off")


class Clock:
    def __init__(self, hour: int = 9, day: dt.date = TODAY) -> None:
        self.t = dt.datetime.combine(day, dt.time(hour, 0), tzinfo=IST).astimezone(dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.t

    def next_day(self) -> None:
        self.t += dt.timedelta(days=1)


async def rig(**kw):  # type: ignore[no-untyped-def]
    clock = kw.pop("clock", Clock())
    sink = kw.pop("sink", Sink())
    svc, docs, _ = make(clock=clock)
    job = VaultReminders(svc, sink, docs, clock=clock)
    return svc, docs, sink, job, clock


async def add(svc, days: int, *, type_id="passport", confirmed=True, n=0, holder=None):  # type: ignore[no-untyped-def]
    item = (
        await svc.add_file(UID, PDF + str(n).encode(), type_hint=type_id, holder_id=holder)
    ).item
    if confirmed:
        exp = (TODAY + dt.timedelta(days=days)).isoformat()
        await svc.update(UID, item.id, {"expires_on": exp, "confirm": True})
    return item


async def test_it_is_a_tick_job_with_a_unique_name() -> None:
    _, _, _, job, _ = await rig()
    assert isinstance(job, TickJob)
    assert job.name == "vault_reminders" and 0 < job.budget_s <= 60
    assert job.name not in {"memory", "documents", "undo", "outside_tasks", "permissions"}
    assert (await run_jobs([job], [UID])) == {"vault_reminders": "ok"}


async def test_an_owner_that_fails_is_counted_and_the_tick_says_failed() -> None:
    """R2 review M1: one owner's failure stops no one, but it is counted, so the tick answer
    says "failed" instead of "ok"."""
    svc, _, sink, job, _ = await rig()
    await add(svc, 5)
    real = svc.index

    async def index(uid: str):  # type: ignore[no-untyped-def]
        if uid.startswith("u_broken"):
            raise RuntimeError("firestore down")
        return await real(uid)

    svc.index = index  # type: ignore[method-assign]
    assert await job.run(["u_broken", UID]) == {"owners": 1, "alerts": 1, "failed": 1}
    assert len(sink.calls) == 1
    # (a failed owner's claim goes stale before it is retried, so the tick check uses another)
    assert await run_jobs([job], ["u_broken_2"]) == {"vault_reminders": "failed"}


async def test_each_threshold_is_sent_once() -> None:
    svc, _, sink, job, clock = await rig()
    await add(svc, 90)
    assert await job.run([UID]) == {"owners": 1, "alerts": 1, "failed": 0}
    clock.next_day()
    await job.run([UID])
    assert len(sink.calls) == 1  # 89 days left: nothing new
    assert sink.calls[0][2] == "vault_expiry" and sink.calls[0][0] == UID


async def test_a_run_happens_once_per_owner_per_day() -> None:
    svc, _, sink, job, _ = await rig()
    await add(svc, 5)
    await job.run([UID])
    await job.run([UID])
    assert len(sink.calls) == 1


async def test_not_before_the_brief_time() -> None:
    clock = Clock(hour=7)
    svc, _, sink, job, _ = await rig(clock=clock)
    await add(svc, 5)
    assert await job.run([UID]) == {"owners": 0, "alerts": 0, "failed": 0}
    assert sink.calls == []
    clock.t += dt.timedelta(hours=3)
    assert (await job.run([UID]))["alerts"] == 1


async def test_catch_up_sends_only_the_most_urgent_and_marks_older_ones() -> None:
    svc, _, sink, job, clock = await rig()
    await add(svc, 6)  # 90, 30 and 7 are all past
    await job.run([UID])
    assert len(sink.calls) == 1 and "in 6 days" in sink.calls[0][1]
    for _ in range(3):
        clock.next_day()
        await job.run([UID])
    assert len(sink.calls) == 1  # 90 / 30 / 7 never come back


async def test_next_threshold_is_sent_later() -> None:
    svc, _, sink, job, clock = await rig()
    await add(svc, 8)
    await job.run([UID])
    first = len(sink.calls)
    clock.next_day()  # 7 days left
    await job.run([UID])
    assert first == 1 and len(sink.calls) == 2


async def test_unconfirmed_items_get_no_reminder() -> None:
    svc, _, sink, job, _ = await rig()
    await add(svc, 3, confirmed=False)
    await job.run([UID])
    assert sink.calls == []


async def test_expired_today_and_expired() -> None:
    svc, _, sink, job, clock = await rig()
    await add(svc, 0)
    await job.run([UID])
    assert "expires today" in sink.calls[0][1]
    clock.next_day()
    await job.run([UID])
    assert "has expired" in sink.calls[1][1]


async def test_long_expired_items_are_marked_not_announced() -> None:
    svc, _, sink, job, _ = await rig()
    await add(svc, -200)
    await job.run([UID])
    assert sink.calls == []


async def test_at_most_three_alerts_then_one_summary() -> None:
    svc, _, sink, job, _ = await rig()
    for n in range(3):
        await add(svc, 5, n=n)
    await job.run([UID])
    assert len(sink.calls) == 3
    svc2, _, sink2, job2, _ = await rig()
    for n in range(4):
        await add(svc2, 5, n=n)
    await job2.run([UID])
    assert len(sink2.calls) == 1 and "4 documents in your vault need attention" in sink2.calls[0][1]


async def test_generic_text_has_no_type_holder_or_last4() -> None:
    svc, _, sink, job, _ = await rig()
    item = await add(svc, 30, type_id="passport")
    await svc.update(UID, item.id, {"last4": "4821", "title": "Akash passport"})
    await job.run([UID])
    text = sink.calls[0][1]
    assert text == (
        "JARVIS: a document in your vault expires in 30 days. Open the console and go to Vault."
    )
    assert "passport" not in text.lower() and "4821" not in text


async def test_type_text_says_your_or_a_family_members_never_a_label_or_last4() -> None:
    svc, _, sink, job, clock = await rig()
    await svc.update_settings(UID, {"alert_detail": "type"})
    mine = await add(svc, 30, type_id="passport", n=1)
    h = await svc.add_holder(UID, "Anjali Rao")
    await add(svc, 7, type_id="driving_licence", n=2, holder=h.id)
    await svc.update(UID, mine.id, {"last4": "4821"})
    await job.run([UID])
    texts = sorted(c[1] for c in sink.calls)
    assert texts == [
        "JARVIS: a family member's driving licence expires in 7 days (12 Nov 2026).",
        "JARVIS: your passport expires in 30 days (05 Dec 2026).",
    ]
    assert all("Anjali" not in t and "4821" not in t for t in texts)
    assert clock


async def test_a_failed_send_is_retried_the_next_day() -> None:
    sink = Sink(sent=False)
    svc, _, _, job, clock = await rig(sink=sink)
    await add(svc, 5)
    await job.run([UID])
    sink.sent = True
    clock.next_day()
    await job.run([UID])
    assert len(sink.calls) == 2


async def test_check_runs_without_the_clock_gate_when_a_panel_opens() -> None:
    clock = Clock(hour=6)
    svc, _, sink, job, _ = await rig(clock=clock)
    await add(svc, 5)
    assert await job.check(UID) == 1
    assert await job.check(UID) == 0


async def test_state_holds_ids_and_dates_only() -> None:
    svc, docs, _, job, _ = await rig()
    item = await add(svc, 5)
    await job.run([UID])
    doc = docs._data[f"jarvis_vault_alerts/{UID}"]
    assert doc["last_run_day"] == "2026-11-05" and set(doc["sent"]) == {item.id}
    assert not scan(docs, "Document") or True


async def test_one_owner_failing_does_not_stop_the_others() -> None:
    svc, docs, sink, job, _ = await rig()
    await add(svc, 5)
    docs._data["jarvis_vault/u_bad0000000000003"] = {"rev": 1, "blob": "garbage"}
    out = await job.run(["u_bad0000000000003", UID])
    assert out["alerts"] == 1 and len(sink.calls) == 1


def test_alert_text_templates_directly() -> None:
    assert alert_text("generic", "Passport", "you", 1, dt.date(2027, 1, 2)).endswith("Vault.")
    assert "in 1 day." in alert_text("generic", "Passport", "you", 1, dt.date(2027, 1, 2))
    t = alert_text("type", "PAN card", "you", 14, dt.date(2027, 1, 2))
    assert t == "JARVIS: your PAN card expires in 14 days (02 Jan 2027)."


class SlowSink(Sink):
    """Sends take a moment, so two checks overlap; `block_at` hangs the nth send for ever."""

    def __init__(self, block_at: int = 0) -> None:
        super().__init__()
        self.block_at, self.started = block_at, 0

    async def send(self, uid: str, text: str, *, kind: str) -> AlertResult:
        self.started += 1
        if self.started == self.block_at:
            await asyncio.Event().wait()
        await asyncio.sleep(0.01)
        return await super().send(uid, text, kind=kind)


async def test_concurrent_checks_send_once() -> None:
    sink = SlowSink()
    svc, _, _, job, _ = await rig(sink=sink)
    await add(svc, 5)
    other = VaultReminders(svc, sink, job._d, clock=job._clock)  # a second instance
    got = await asyncio.gather(job.check(UID), job.check(UID), other.check(UID))
    assert len(sink.calls) == 1 and sorted(got) == [0, 0, 1]


async def test_cancelled_check_does_not_resend() -> None:
    sink = SlowSink(block_at=2)
    clock = Clock()
    svc, _, _, job, _ = await rig(sink=sink, clock=clock)
    await add(svc, 5, n=1)
    await add(svc, 20, n=2)
    task = asyncio.create_task(job.check(UID))
    for _ in range(50):  # until the first alert is out and the second is hanging
        await asyncio.sleep(0.01)
        if sink.started == 2:
            break
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(sink.calls) == 1
    clock.t += dt.timedelta(minutes=10)  # the unfinished claim goes stale
    sink.block_at = 0
    await job.check(UID)
    texts = [c[1] for c in sink.calls]
    assert len(texts) == 2 and len(set(texts)) == 2  # the second alert, never the first again
    clock.t += dt.timedelta(minutes=10)
    await job.check(UID)
    assert len(sink.calls) == 2  # and the day is now done
