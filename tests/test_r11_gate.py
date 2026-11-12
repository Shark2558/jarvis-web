# tests/test_r11_gate.py -- R11 I0 (docs/plans/r11-free-helpers.md D4, D6, D21): the one sender
# for every helper message and the nudge limits. Written before helpers/gate.py: only R11 kinds, a
# part only its own kinds, the per-kind / per-day / per-hour caps, snooze and stop (one kind or
# all), fail closed when the state can't be read, only delivered or held sends count, a
# content-free send log, the fortnight's on-time numbers, the sweep and the privacy row.
from __future__ import annotations

from datetime import timedelta

import pytest
from r11_fakes import NOON_IST, TWO_AM_IST, UID, Clock, FakeNotifier, sender

from jarvis.helpers.gate import ALL, KEEP_DAYS, NudgeState, fortnight
from jarvis.helpers.kinds import DEFAULT_CAPS, NUDGE_KINDS
from jarvis.helpers.privacy import nudge_privacy
from jarvis.notify.ports import Delivery
from jarvis.storage.docs import Set

DAY = "2026-11-10"  # NOON_IST's local date


async def test_only_r11_kinds_and_a_part_only_its_own() -> None:
    send, _, _, _ = sender()
    with pytest.raises(ValueError):
        await send.send(UID, "home_intruder", "x", due=NOON_IST)
    with pytest.raises(ValueError):  # Part A (today) may not send Part B's disaster alert
        await send.for_part("today").send(UID, "disaster_alert", "x", due=NOON_IST)
    with pytest.raises(ValueError):  # the kitchen sends no alerts at all
        await send.for_part("kitchen").send(UID, "bill_due", "x", due=NOON_IST)
    got = await send.for_part("today").send(UID, "bill_due", "Electricity due.", due=NOON_IST)
    assert got.delivered and got.counted and got.outcome == "rang"


async def test_a_reminder_goes_through_the_policy_port_and_the_log_has_no_words() -> None:
    send, notifier, _, _ = sender()
    await send.send(UID, "bill_due", "Electricity ₹1,240 due\n tomorrow.", due=NOON_IST)
    assert notifier.calls == [(UID, "bill_due", "Electricity ₹1,240 due tomorrow.", None)]
    assert notifier.signals[0].source == "nudge"
    (entry,) = await send.store.sends(UID, DAY)
    assert entry == {"k": "bill_due", "due": "2026-11-10T06:30:00+00:00",
                     "at": "2026-11-10T06:30:00+00:00", "o": "rang"}  # fmt: skip
    with pytest.raises(ValueError):
        await send.send(UID, "bill_due", "  \n ", due=NOON_IST)


async def test_the_per_kind_cap_holds_and_refusals_never_reach_the_notifier() -> None:
    clock = Clock()
    send, notifier, _, _ = sender(clock=clock, nudges_max_per_hour=8, nudges_max_per_day=40)
    outcomes = []
    for i in range(DEFAULT_CAPS["nudge_hydrate"] + 1):
        clock.at = NOON_IST + timedelta(minutes=10 * i)
        outcomes.append((await send.send(UID, "nudge_hydrate", "Water.", due=clock.at)).outcome)
    assert outcomes[:-1] == ["rang"] * DEFAULT_CAPS["nudge_hydrate"] and outcomes[-1] == "capped"
    assert len(notifier.calls) == DEFAULT_CAPS["nudge_hydrate"]


async def test_the_day_and_hour_totals_hold_across_kinds() -> None:
    clock = Clock()
    send, _, _, _ = sender(clock=clock, nudges_max_per_hour=4, nudges_max_per_day=5)
    kinds = ["nudge_standup", "nudge_hydrate"] * 4
    got = [(await send.send(UID, k, "Nudge.", due=clock.at)).outcome for k in kinds[:5]]
    assert got == ["rang"] * 4 + ["capped"]  # 4 an hour
    clock.at = NOON_IST + timedelta(hours=2)
    got = [(await send.send(UID, k, "Nudge.", due=clock.at)).outcome for k in kinds[:2]]
    assert got == ["rang", "capped"]  # 5 a day in all


async def test_a_reminder_kind_is_never_capped_by_the_nudge_limits() -> None:
    send, _, _, _ = sender(nudges_max_per_day=1, nudges_max_per_hour=1)
    for _ in range(5):
        assert (await send.send(UID, "chore_due", "Chore.", due=NOON_IST)).delivered


async def test_snooze_stop_and_resume_one_kind_or_all() -> None:
    clock = Clock()
    send, notifier, _, _ = sender(clock=clock)
    await send.store.snooze(UID, "nudge_standup", 60, clock.at)
    assert (await send.send(UID, "nudge_standup", "Up.", due=clock.at)).outcome == "snoozed"
    assert (await send.send(UID, "nudge_hydrate", "Water.", due=clock.at)).outcome == "rang"
    clock.at += timedelta(minutes=61)
    assert (await send.send(UID, "nudge_standup", "Up.", due=clock.at)).outcome == "rang"
    await send.store.stop_today(UID, ALL, DAY)
    for kind in NUDGE_KINDS:
        assert (await send.send(UID, kind, "Nudge.", due=clock.at)).outcome == "stopped"
    clock.at += timedelta(days=1)  # tomorrow: the stop is over by itself
    assert (await send.send(UID, "nudge_focus", "Focus.", due=clock.at)).outcome == "rang"
    await send.store.stop_today(UID, "nudge_focus", send.today())
    await send.store.resume(UID, "nudge_focus")
    clock.at += timedelta(minutes=30)
    assert (await send.send(UID, "nudge_focus", "Focus.", due=clock.at)).outcome == "rang"
    assert len(notifier.calls) == 4


async def test_bad_changes_are_refused_in_plain_words() -> None:
    send, _, _, _ = sender()
    for bad in ({"nudge_hydrate": 25}, {"nudge_hydrate": -1}, {"bill_due": 3}, {"x": 1}):
        with pytest.raises(ValueError):
            await send.store.set_caps(UID, bad)
    with pytest.raises(ValueError):
        await send.store.set_caps(UID, {"nudge_hydrate": True})  # type: ignore[dict-item]
    for minutes in (5, 721):
        with pytest.raises(ValueError):
            await send.store.snooze(UID, "nudge_hydrate", minutes, NOON_IST)
    with pytest.raises(ValueError):
        await send.store.stop_today(UID, "bill_due", DAY)
    state = await send.store.set_caps(UID, {"nudge_hydrate": 2})
    assert state.cap("nudge_hydrate") == 2 and state.cap("nudge_standup") == 8 and state.rev == 1


async def test_an_unreadable_state_means_no_nudge() -> None:
    send, notifier, docs, _ = sender()
    await docs.write([Set(f"jarvis_helpers_nudge/{UID}", {"state": {"caps": "broken"}})])
    got = await send.send(UID, "nudge_hydrate", "Water.", due=NOON_IST)
    assert got.outcome == "unavailable" and got.retry and notifier.calls == []
    # a reminder doesn't read the nudge state at all
    assert (await send.send(UID, "bill_due", "Bill.", due=NOON_IST)).delivered


@pytest.mark.parametrize(
    ("delivery", "outcome", "counted", "retry"),
    [
        (Delivery(action="ring", reason="x", telegram=True), "rang", True, False),
        (Delivery(action="silent", reason="x", push=1), "silent", True, False),
        (Delivery(action="hold", reason="quiet_hours"), "held", True, False),
        (Delivery(action="drop", reason="switched_off"), "dropped:switched_off", False, False),
        (Delivery(action="ring", reason="x"), "undelivered", False, True),
    ],
)
async def test_what_counts_and_what_is_retried(
    delivery: Delivery, outcome: str, counted: bool, retry: bool
) -> None:
    send, _, _, clock = sender(notifier=FakeNotifier(delivery=delivery))
    got = await send.send(UID, "bill_due", "Bill.", due=clock.at)
    assert (got.outcome, got.counted, got.retry) == (outcome, counted, retry)


async def test_uncounted_sends_leave_the_caps_alone_and_a_failing_notifier_is_a_result() -> None:
    drop = FakeNotifier(delivery=Delivery(action="drop", reason="nudge_gap"))
    send, _, _, _ = sender(notifier=drop, nudges_max_per_day=1)
    for _ in range(3):
        assert (await send.send(UID, "nudge_hydrate", "W.", due=NOON_IST)).outcome.startswith(
            "dropped"
        )
    send2, _, _, _ = sender(notifier=FakeNotifier(fail=True))
    assert (await send2.send(UID, "bill_due", "Bill.", due=NOON_IST)).outcome == "unavailable"


async def test_the_real_policy_drops_a_nudge_at_night_and_holds_a_reminder() -> None:
    clock = Clock(TWO_AM_IST)
    send, _, _, _ = sender(clock=clock, notifier=FakeNotifier(clock=clock, policy=True))
    assert (await send.send(UID, "nudge_hydrate", "W.", due=clock.at)).outcome == (
        "dropped:stale_at_night"
    )
    assert (await send.send(UID, "bill_due", "B.", due=clock.at)).outcome == "held"
    assert (await send.send(UID, "disaster_alert", "D.", due=clock.at)).outcome == "rang"


def test_the_fortnight_counts_on_time_late_and_early_reminders() -> None:
    def e(k: str, due: str, at: str, o: str = "rang") -> dict[str, str]:
        return {"k": k, "due": due, "at": at, "o": o}

    t = "2026-11-10T03:30:00+00:00"
    days = [
        ("2026-10-20", [e("bill_due", t, t)]),  # older than 14 days: not counted
        ("2026-11-01", [e("bill_due", t, "2026-11-10T03:35:00+00:00")]),  # 5 min: on time
        ("2026-11-05", [e("chore_due", t, "2026-11-10T03:50:00+00:00")]),  # 20 min: late
        ("2026-11-09", [e("chore_due", t, "2026-11-10T03:29:00+00:00")]),  # early
        ("2026-11-10", [e("nudge_hydrate", t, t)] * 3 + [e("bill_due", t, t, "capped")]),
    ]
    got = fortnight(days, "2026-11-10", max_per_day=2)
    assert got == {
        "reminders_on_time": 1,
        "reminders_late": 1,
        "reminders_early": 1,
        "nudge_days_within_limits": 3,  # 11-01, 11-05, 11-09 (11-10 had 3 nudges > 2)
    }


async def test_the_sweep_keeps_fifteen_days_and_the_privacy_row_exports_and_deletes() -> None:
    clock = Clock()
    send, _, _, _ = sender(clock=clock)
    for back in (0, 3, KEEP_DAYS + 2):
        clock.at = NOON_IST - timedelta(days=back)
        await send.send(UID, "bill_due", "Electricity due.", due=clock.at)
    await send.store.snooze(UID, "nudge_hydrate", 30, NOON_IST)
    assert await send.store.sweep((UID,), DAY) == 1
    assert [d for d, _ in await send.store.days(UID)] == ["2026-11-07", DAY]
    row = nudge_privacy(send.store)
    view = await row.describe(UID)
    assert view.id == "helpers_nudge" and view.section == "Helpers" and view.count == 3
    exported = await row.export(UID)
    assert "Electricity" not in str(exported) and exported is not None
    assert await row.delete(UID) == 3 and (await row.describe(UID)).count == 0


def test_the_state_model_is_strict() -> None:
    with pytest.raises(ValueError):
        NudgeState.model_validate({"caps": {}, "extra": 1})
    s = NudgeState(snoozed={ALL: "2026-11-10T08:00:00+00:00", "nudge_hydrate": "bad"})
    assert s.snoozed_until("nudge_hydrate") is not None and s.cap("nudge_activity") == 3
