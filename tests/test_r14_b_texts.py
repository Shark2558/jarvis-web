# tests/test_r14_b_texts.py -- R14 Part B (D5, D6): every alert is a fixed template (no logger
# name, no vendor text, no amount but the spike's rupees, at most 300 characters), and the teller
# claims before it sends, with `SENDING` set, and never fails on a failed send.
from __future__ import annotations

import asyncio
import logging

import pytest
from r14_fakes_b import NOON, OTHER, TWO_AM, UID, Clock, RingCounter

from jarvis.selfwatch import texts
from jarvis.selfwatch.ledger import Told
from jarvis.selfwatch.ports import SENDING
from jarvis.storage.docs import MemoryDocs, Query

ALL = [
    texts.job_failing(["vault_reminders"]),
    texts.job_failing([f"job_{i:02d}" for i in range(40)]),
    texts.jobs_back(),
    texts.clock_stopped("watchdog", "14:10"),
    texts.clock_stopped("tick", "05:00"),
    texts.clock_back("watchdog"),
    texts.clock_back("tick"),
    texts.brief_missed("08:00"),
    texts.errors_piling(30),
    texts.spend_spike(1234.4, 3.0),
    texts.deploy_changed("14.0.0"),
]


@pytest.mark.parametrize("text", ALL)
def test_every_alert_fits_one_message_and_names_no_logger(text: str) -> None:
    assert 0 < len(text) <= texts.MAX_TEXT
    assert "jarvis." not in text and "Error" not in text and "Exception" not in text


def test_the_failing_jobs_are_named_in_one_message() -> None:
    one = texts.job_failing(["memory"])
    assert one == "1 background job keeps failing: memory. JARVIS will say when it works again."
    three = texts.job_failing(["a", "b", "c"])
    assert three.startswith("3 background jobs keep failing: a, b, c.")
    many = texts.job_failing([f"job_{i:02d}" for i in range(40)])
    assert many.startswith("40 background jobs keep failing:") and "more" in many


def test_only_the_spike_carries_an_amount() -> None:
    assert "₹1,234" in texts.spend_spike(1234.4, 3.0)
    assert all("₹" not in t for t in ALL if t != texts.spend_spike(1234.4, 3.0))


def test_the_update_notice_says_the_version() -> None:
    assert "14.0.0" in texts.deploy_changed("14.0.0")


async def test_the_teller_claims_first_and_tells_each_owner_once() -> None:
    clock = Clock()
    ring = RingCounter(clock)
    teller = texts.Teller(lambda: ring, Told(MemoryDocs()))
    sent = await teller.tell((UID, OTHER), "brief_missed", "2026-11-16", "x", NOON)
    again = await teller.tell((UID, OTHER), "brief_missed", "2026-11-16", "x", NOON)
    assert sent == texts.Said(2, settled=True) and again == texts.Said(0, settled=True)
    assert [s.uid for s in ring.sent] == [UID, OTHER]
    assert all(s.sending for s in ring.sent) and SENDING.get() is False


async def test_the_subject_reaches_the_storm() -> None:
    ring = RingCounter(Clock())
    teller = texts.Teller(lambda: ring, Told(MemoryDocs()))
    await teller.tell((UID,), "job_failing", "c", "x", NOON, subject="jobs")
    assert ring.sent[0].subject == "jobs" and ring.sent[0].rang


# ---- H1: a send that reached nobody is not "sent" (silent review H1, code review M1, M2) --------
def _teller(ring: RingCounter, docs: MemoryDocs | None = None) -> tuple[texts.Teller, Told]:
    told = Told(docs if docs is not None else MemoryDocs())
    return texts.Teller(lambda: ring, told), told


async def test_a_send_the_cap_dropped_gives_its_claim_back_and_is_tried_again_later() -> None:
    clock = Clock()
    ring = RingCounter(clock)
    docs = MemoryDocs()
    teller, _ = _teller(ring, docs)
    for kind in ("job_failing", "brief_missed", "errors_piling"):  # the self-health cap: 3 an hour
        assert (await teller.tell((UID,), kind, "c", "x", clock())).settled
    got = await teller.tell((UID,), "deploy_changed", "c", "x", clock())
    assert got == texts.Said(0, settled=False)  # the 4th in the hour: dropped by the cap
    assert len(await docs.query(Query("jarvis_selfwatch_told"))) == 3  # its claim given back
    clock.advance(minutes=5)
    assert not (await teller.tell((UID,), "deploy_changed", "c", "x", clock())).settled
    assert len(ring.sent) == 4  # not before its retry time: nothing sent
    clock.advance(minutes=56)  # an hour after the first three: the cap has room again
    got = await teller.tell((UID,), "deploy_changed", "c", "x", clock())
    assert got == texts.Said(1, settled=True) and ring.sent[-1].rang  # deferred, not lost


async def test_retries_never_ring_past_the_self_health_cap() -> None:
    clock = Clock()
    ring = RingCounter(clock)
    teller, _ = _teller(ring)
    kinds = ("job_failing", "brief_missed", "errors_piling", "deploy_changed", "spend_spike")
    per_run: list[int] = []
    for _ in range(36):  # three hours of 5-minute runs, every kind owed until it is said
        before = len(ring.rings())
        for kind in kinds:
            await teller.tell((UID,), kind, "c", "x", clock(), subject=kind)
        per_run.append(len(ring.rings()) - before)
        clock.advance(minutes=5)
    assert sorted(s.kind for s in ring.rings()) == sorted(kinds)  # each said once, none lost
    assert all(sum(per_run[i : i + 12]) <= 3 for i in range(len(per_run)))  # 3 in any hour


async def test_a_ring_no_channel_took_is_tried_a_bounded_number_of_times() -> None:
    clock = Clock()
    ring = RingCounter(clock, dead=True)
    teller, told = _teller(ring)
    results = []
    for _ in range(int(texts.MAX_TRIES * texts.RETRY_EVERY.total_seconds() // 300) + 24):
        results.append(await teller.tell((UID,), "job_failing", "c", "x", clock()))
        clock.advance(minutes=5)
    assert len(ring.sent) == texts.MAX_TRIES  # never every 5 minutes for ever
    assert results[-1] == texts.Said(0, settled=True)  # given up: the claim stands
    assert not await told.claim(UID, "job_failing", "c", clock())


async def test_a_held_alert_and_one_he_switched_off_are_settled() -> None:
    from jarvis.notify.models import NotifySettings

    night = Clock(TWO_AM)
    teller, _ = _teller(RingCounter(night))
    assert await teller.tell((UID,), "job_failing", "c", "x", night()) == texts.Said(1, True)
    off = NotifySettings().model_copy(update={"kinds": {"brief_missed": "off"}})
    teller, _ = _teller(RingCounter(night, settings=off))
    got = await teller.tell((UID,), "brief_missed", "c", "x", night())
    assert got.settled and got.sent == 0
    quiet_info = await _teller(RingCounter(night))[0].tell(
        (UID,), "selfwatch_ok", "c", "x", night()
    )
    assert quiet_info.settled  # info at night: the feed only, by the policy


async def test_a_send_that_raises_gives_its_claim_back_and_never_raises() -> None:
    clock = Clock()
    ring = RingCounter(clock, fail=True)
    teller, _ = _teller(ring)
    assert await teller.tell((UID,), "errors_piling", "d", "x", NOON) == texts.Said(0, False)
    ring.fail = False
    clock.advance(minutes=30)
    assert await teller.tell((UID,), "errors_piling", "d", "x", clock()) == texts.Said(1, True)
    assert SENDING.get() is False


async def test_a_cancelled_send_gives_its_claim_back() -> None:
    class Hangs:
        async def notify(self, *a: object, **k: object) -> None:
            await asyncio.sleep(10)

    told = Told(MemoryDocs())
    teller = texts.Teller(lambda: Hangs(), told)  # type: ignore[arg-type, return-value]
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await teller.tell((UID,), "job_failing", "c", "x", NOON)
    assert await told.claim(UID, "job_failing", "c", NOON)  # given back: made again


async def test_one_owner_reached_and_one_not_tries_only_the_other_again() -> None:
    clock = Clock()

    class Half(RingCounter):
        down: set[str] = set()  # noqa: RUF012 - one test's fake

        async def notify(self, uid, signal, message, **kw):  # type: ignore[no-untyped-def]
            self.dead = uid in self.down
            return await super().notify(uid, signal, message, **kw)

    ring = Half(clock)
    ring.down = {OTHER}
    teller, _ = _teller(ring)
    got = await teller.tell((UID, OTHER), "job_failing", "c", "x", clock())
    assert got == texts.Said(1, False)
    clock.advance(minutes=30)
    ring.down = set()
    again = await teller.tell((UID, OTHER), "job_failing", "c", "x", clock())
    assert again.settled and [s.uid for s in ring.sent] == [UID, OTHER, OTHER]


async def test_no_notifier_claims_nothing_is_not_sent_and_is_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    docs = MemoryDocs()
    teller = texts.Teller(lambda: None, Told(docs))
    caplog.set_level(logging.WARNING, logger="jarvis.selfwatch.texts")
    for _ in range(3):
        assert await teller.tell((UID,), "brief_missed", "d", "x", NOON) == texts.Said(0, False)
    assert docs.sets == 0
    assert len([r for r in caplog.records if "no notifier" in r.getMessage()]) == 1


async def test_no_owner_is_nobody_told() -> None:
    teller, _ = _teller(RingCounter(Clock()))
    assert await teller.tell((), "job_failing", "c", "x", NOON) == texts.Said(0, settled=False)


def test_settled_drops_are_the_ones_home_settles_too() -> None:
    from jarvis.home.watchdog import OWNER_SETTLED

    assert texts.SETTLED == OWNER_SETTLED
