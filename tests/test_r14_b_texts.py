# tests/test_r14_b_texts.py -- R14 Part B (D5, D6): every alert is a fixed template (no logger
# name, no vendor text, no amount but the spike's rupees, at most 300 characters), and the teller
# claims before it sends, with `SENDING` set, and never fails on a failed send.
from __future__ import annotations

import pytest
from r14_fakes_b import NOON, OTHER, UID, Clock, RingCounter

from jarvis.selfwatch import texts
from jarvis.selfwatch.ledger import Told
from jarvis.selfwatch.ports import SENDING
from jarvis.storage.docs import MemoryDocs

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
    assert (sent, again) == (2, 0)
    assert [s.uid for s in ring.sent] == [UID, OTHER]
    assert all(s.sending for s in ring.sent) and SENDING.get() is False


async def test_a_failed_send_is_not_retried_and_never_raises() -> None:
    clock = Clock()
    ring = RingCounter(clock, fail=True)
    teller = texts.Teller(lambda: ring, Told(MemoryDocs()))
    assert await teller.tell((UID,), "errors_piling", "d", "x", NOON) == 0
    ring.fail = False
    assert await teller.tell((UID,), "errors_piling", "d", "x", NOON) == 0  # claimed: once
    assert SENDING.get() is False


async def test_no_notifier_means_nothing_is_claimed() -> None:
    docs = MemoryDocs()
    teller = texts.Teller(lambda: None, Told(docs))
    assert await teller.tell((UID,), "brief_missed", "d", "x", NOON) == 0
    assert docs.sets == 0


async def test_the_subject_reaches_the_storm() -> None:
    ring = RingCounter(Clock())
    teller = texts.Teller(lambda: ring, Told(MemoryDocs()))
    await teller.tell((UID,), "job_failing", "c", "x", NOON, subject="jobs")
    assert ring.sent[0].subject == "jobs" and ring.sent[0].rang
