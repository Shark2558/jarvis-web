# tests/test_r11_a_reminders.py -- R11 Part A (D3, D7): the `bills_due` job on the 5-minute clock.
# A bill due on the 13th: one `bill_due` at 09:00 his time 3 days, 1 day and the day before, and one
# "overdue" the day after if it isn't marked paid; never early, never twice (claims survive a
# restart), released when no channel took it; held at night by the one policy; only through the
# part's own sender; the alert text is JARVIS's template with his own label.
from __future__ import annotations

from datetime import timedelta

from r11_fakes import UID, Clock, FakeNotifier
from r11_fakes_a import FAKE_UPI, at, today_ctx

from jarvis.helpers.today.bills import BillsService
from jarvis.helpers.today.jobs import BillsDueJob
from jarvis.helpers.today.store import BillStore, Claims
from jarvis.notify.ports import Delivery


def _rig(clock: Clock, notifier: FakeNotifier | None = None):  # type: ignore[no-untyped-def]
    c, n, docs, _ = today_ctx(clock=clock, notifier=notifier)
    store = BillStore(docs, c.keyring, prefix=c.prefix)
    svc = BillsService(store, tz=c.tz, now=c.now)
    claims = Claims(docs, "bills_told", prefix=c.prefix, keep_days=60)
    job = BillsDueJob(svc, claims, c.sender, owners=c.owners, tz=c.tz, now=c.now)
    return svc, job, n, docs


async def _add(svc: BillsService) -> None:
    await svc.add(UID, label="Electricity", payee="Power Co", upi=FAKE_UPI, amount="1240", day=13)


async def _tick_days(job: BillsDueJob, clock: Clock, first: int, last: int) -> None:
    """Every 5 minutes from 00:00 on Nov `first` to 23:55 on Nov `last` (IST)."""
    clock.at = at(2026, 11, first, 0, 0)
    end = at(2026, 11, last, 23, 55)
    while clock.at <= end:
        await job.run(())
        clock.at += timedelta(minutes=5)


async def test_three_one_and_zero_days_before_at_nine_then_overdue_once() -> None:
    clock = Clock(at(2026, 11, 10, 8, 0))
    svc, job, notifier, _ = _rig(clock)
    await _add(svc)
    sent: list[tuple[object, str]] = []
    notifier.calls.clear()
    clock.at = at(2026, 11, 10, 0, 0)
    while clock.at <= at(2026, 11, 15, 23, 55):
        before = len(notifier.calls)
        await job.run(())
        if len(notifier.calls) > before:
            sent.append((clock.at, notifier.calls[-1][2]))
        clock.at += timedelta(minutes=5)
    assert [when for when, _ in sent] == [
        at(2026, 11, 10, 9, 0),
        at(2026, 11, 12, 9, 0),
        at(2026, 11, 13, 9, 0),
        at(2026, 11, 14, 9, 0),
    ]
    texts = [t for _, t in sent]
    assert texts[0] == (
        "Bill reminder, Sir: Electricity ₹1,240 is due in 3 days (Fri 13 Nov). Open JARVIS to get "
        "the payment ready."
    )
    assert "due tomorrow" in texts[1] and "due today" in texts[2]
    assert "was due yesterday" in texts[3] and "isn't marked paid" in texts[3]
    assert all(k == "bill_due" for _, k, _, _ in notifier.calls)
    assert all(FAKE_UPI not in t for t in texts)


async def test_never_twice_across_a_restart() -> None:
    clock = Clock(at(2026, 11, 10, 9, 0))
    svc, job, notifier, docs = _rig(clock)
    await _add(svc)
    await job.run(())
    c2, n2, _, _ = today_ctx(clock=clock)
    store2 = BillStore(docs, c2.keyring, prefix=c2.prefix)
    job2 = BillsDueJob(
        BillsService(store2, tz=c2.tz, now=clock),
        Claims(docs, "bills_told", prefix=c2.prefix, keep_days=60),
        c2.sender,
        owners=c2.owners,
        tz=c2.tz,
        now=clock,
    )
    clock.at += timedelta(minutes=5)
    await job2.run(())
    assert len(notifier.calls) == 1 and n2.calls == []


async def test_a_send_no_channel_took_is_tried_again_next_run() -> None:
    clock = Clock(at(2026, 11, 10, 9, 0))
    notifier = FakeNotifier(clock=clock, delivery=Delivery(action="ring", reason="none"))
    svc, job, _, _ = _rig(clock, notifier)
    await _add(svc)
    await job.run(())
    assert len(notifier.calls) == 1  # undelivered: the claim is released
    notifier.delivery = Delivery(action="ring", reason="ok", telegram=True)
    clock.at += timedelta(minutes=5)
    await job.run(())
    clock.at += timedelta(minutes=5)
    await job.run(())
    assert len(notifier.calls) == 2


async def test_held_at_night_by_the_policy() -> None:
    clock = Clock(at(2026, 11, 10, 8, 0))
    notifier = FakeNotifier(clock=clock, policy=True)
    svc, job, _, docs = _rig(clock, notifier)
    await _add(svc)
    await svc.set_prefs(UID, bills_at="23:30")
    clock.at = at(2026, 11, 10, 23, 30)
    got = await job.run(())
    assert got["held"] == 1 and got["sent"] == 0
    clock.at += timedelta(minutes=5)
    assert (await job.run(()))["held"] == 0  # held once, not again


async def test_nothing_without_bills_or_before_the_time() -> None:
    clock = Clock(at(2026, 11, 10, 8, 55))
    svc, job, notifier, _ = _rig(clock)
    assert (await job.run(()))["sent"] == 0
    await _add(svc)
    await job.run(())
    assert notifier.calls == []  # 08:55 < 09:00: never early


async def test_a_failed_claim_sweep_is_retried_on_the_next_run() -> None:
    clock = Clock(at(2026, 11, 10, 9, 0))
    svc, job, notifier, docs = _rig(clock)
    await _add(svc)
    calls: list[int] = []
    sweep = job._claims.sweep  # noqa: SLF001 - the job's own claims

    async def flaky(uid: str, now):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("store down")
        return await sweep(uid, now)

    job._claims.sweep = flaky  # type: ignore[method-assign]  # noqa: SLF001
    assert (await job.run(()))["sent"] == 1  # the reminder still went
    clock.at += timedelta(minutes=5)
    await job.run(())
    clock.at += timedelta(minutes=5)
    await job.run(())
    assert len(calls) == 2 and len(notifier.calls) == 1
