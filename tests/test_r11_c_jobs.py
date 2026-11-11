# tests/test_r11_c_jobs.py -- R11 Part C's clock jobs `nudges` and `activity_check` (plan items 8,
# 9, 11, 12 and the focus nudge of 10): every nudge through `ctx.sender` with a `nudge_*` kind, in
# the first run at or after its due time, never early, never twice (claims), a send no channel took
# retried next run (`SendResult.retry`), dropped at night by the policy, inside the gate's caps.
from __future__ import annotations

from datetime import date, datetime, timedelta

from r11_fakes import UID
from r11_fakes_c import FakeCalendar, FakePending, FakeRain, Planned, Rig, at_ist, part, run_tool

from jarvis.helpers.gate import GateStore
from jarvis.helpers.nudges import activity, focus, freetime, hydrate, standup
from jarvis.helpers.nudges.models import Idea
from jarvis.helpers.ports import PendingItem
from jarvis.notify.ports import Delivery

TUESDAY = date(2026, 11, 10)
SUNDAY = date(2026, 11, 15)


async def switch_on(rig: Rig, kind: str, **changes: object) -> None:
    svc = rig.part.services["service"]
    await svc.store.change(UID, lambda s: s.changed(kind, {"on": True, **changes}))


async def tick(rig: Rig, at: datetime, job: str = "nudges") -> dict[str, int]:
    rig.clock.at = at
    return await rig.job(job).run(("someone-else",))


def sent(rig: Rig) -> list[tuple[str, str]]:
    return [(kind, text) for _, kind, text, _ in rig.notifier.calls]


# ---- stand-up and water -------------------------------------------------------------------------
async def test_every_nudge_is_off_until_he_switches_it_on() -> None:
    rig = part()
    for hhmm in ("10:30", "11:00", "15:00", "18:00"):
        await tick(rig, at_ist(TUESDAY, hhmm))
    assert sent(rig) == []


async def test_water_goes_in_the_first_run_at_or_after_due_and_never_twice() -> None:
    rig = part()
    await switch_on(rig, "nudge_hydrate")
    await tick(rig, at_ist(TUESDAY, "10:58"))
    assert sent(rig) == []  # never early
    out = await tick(rig, at_ist(TUESDAY, "11:00") + timedelta(seconds=23))
    assert sent(rig) == [("nudge_hydrate", hydrate.TEXT)] and out == {"rang": 1}
    await tick(rig, at_ist(TUESDAY, "11:05"))
    again = rig.rebuilt()  # a restart: new caches, the same documents
    await tick(again, at_ist(TUESDAY, "11:05"))
    assert len(rig.notifier.calls) == 1


async def test_stand_up_comes_every_hour_after_sitting_down_and_not_on_sunday() -> None:
    rig = part()
    await switch_on(rig, "nudge_standup")
    for h in range(9, 19):
        for m in range(0, 60, 5):
            await tick(rig, at_ist(TUESDAY, f"{h:02d}:{m:02d}"))
    assert sent(rig) == [("nudge_standup", standup.MOVE_TEXT)] * 8
    await tick(rig, at_ist(SUNDAY, "10:30"))
    assert len(rig.notifier.calls) == 8


async def test_the_nudge_goes_only_through_the_parts_sender_with_a_nudge_kind() -> None:
    rig = part()
    await switch_on(rig, "nudge_hydrate")
    await tick(rig, at_ist(TUESDAY, "11:00"))
    sig = rig.notifier.signals[0]
    assert (sig.source, sig.kind) == ("nudge", "nudge_hydrate")
    sends = await GateStore(rig.docs).sends(UID, "2026-11-10")
    assert [e["o"] for e in sends] == ["rang"] and "water" not in str(sends).lower()


async def test_a_send_no_channel_took_is_released_and_retried_next_run() -> None:
    rig = part(policy=False)
    rig.notifier.delivery = Delivery(action="ring", reason="test")  # nobody took it
    await switch_on(rig, "nudge_hydrate")
    await tick(rig, at_ist(TUESDAY, "11:00"))
    rig.notifier.delivery = Delivery(action="ring", reason="test", telegram=True)
    await tick(rig, at_ist(TUESDAY, "11:05"))
    await tick(rig, at_ist(TUESDAY, "11:10"))
    outcomes = [e["o"] for e in await GateStore(rig.docs).sends(UID, "2026-11-10")]
    assert outcomes == ["undelivered", "rang"]


async def test_a_notifier_that_is_down_is_retried_too() -> None:
    rig = part()
    await switch_on(rig, "nudge_hydrate")
    rig.notifier.fail = True
    await tick(rig, at_ist(TUESDAY, "11:00"))
    rig.notifier.fail = False
    await tick(rig, at_ist(TUESDAY, "11:05"))
    assert len(rig.notifier.calls) == 1


async def test_at_night_a_nudge_is_dropped_by_the_policy_and_not_retried() -> None:
    rig = part()
    await switch_on(rig, "nudge_hydrate", start="05:00", end="23:59", days=(1,))
    await tick(rig, at_ist(TUESDAY, "23:05"))  # the 23:00 slot, inside quiet hours
    await tick(rig, at_ist(TUESDAY, "23:10"))
    outcomes = [e["o"] for e in await GateStore(rig.docs).sends(UID, "2026-11-10")]
    assert outcomes == ["dropped:stale_at_night"]


async def test_the_gates_caps_hold_and_a_capped_nudge_is_not_retried() -> None:
    rig = part()
    await GateStore(rig.docs).set_caps(UID, {"nudge_hydrate": 2})
    await switch_on(rig, "nudge_hydrate")
    for hhmm in ("11:00", "12:30", "12:35", "14:00", "15:30"):
        await tick(rig, at_ist(TUESDAY, hhmm))
    outcomes = [e["o"] for e in await GateStore(rig.docs).sends(UID, "2026-11-10")]
    assert outcomes == ["rang", "rang", "capped", "capped"]


async def test_a_snooze_or_stop_from_the_gate_holds_the_nudge() -> None:
    rig = part()
    gate = GateStore(rig.docs)
    await switch_on(rig, "nudge_standup")
    await gate.snooze(UID, "nudge_standup", 60, at_ist(TUESDAY, "10:00"))
    await tick(rig, at_ist(TUESDAY, "10:30"))
    await gate.stop_today(UID, "*", "2026-11-10")
    await tick(rig, at_ist(TUESDAY, "11:30"))
    assert sent(rig) == []
    assert [e["o"] for e in await gate.sends(UID, "2026-11-10")] == ["snoozed", "stopped"]


# ---- the stand-up meeting (owner decision 1, off by default) ----------------------------------
async def test_the_meeting_variant_says_ten_minutes_before_his_stand_up() -> None:
    cal = FakeCalendar(every_day=[Planned("Team Stand-up", "09:45", "10:00", own=False)])
    rig = part(calendar=cal)
    await switch_on(rig, "nudge_standup")
    await tick(rig, at_ist(TUESDAY, "09:30"))
    assert sent(rig) == []  # the meeting variant is off by default
    await switch_on(rig, "nudge_standup", meeting=True)
    await tick(rig, at_ist(TUESDAY, "09:34"))
    assert sent(rig) == []
    await tick(rig, at_ist(TUESDAY, "09:35"))
    await tick(rig, at_ist(TUESDAY, "09:40"))
    assert sent(rig) == [("nudge_standup", standup.MEETING_TEXT)]
    assert "Team" not in standup.MEETING_TEXT


async def test_the_calendar_is_read_only_when_needed_and_cached() -> None:
    cal = FakeCalendar()
    rig = part(calendar=cal)
    await switch_on(rig, "nudge_hydrate")
    await tick(rig, at_ist(TUESDAY, "11:00"))
    assert cal.fetches == 0  # water needs no calendar
    await switch_on(rig, "nudge_standup", meeting=True)
    for m in range(0, 30, 5):
        await tick(rig, at_ist(TUESDAY, f"09:{m:02d}"))
    assert cal.fetches == 1


# ---- focus (item 10's nudge) ---------------------------------------------------------------------
async def test_the_focus_nudge_says_the_top_pending_item() -> None:
    items = [
        PendingItem("today", "Water the plants", "later"),
        PendingItem("today", "Electricity due", "overdue"),
        PendingItem("house", "Change the filter", "today", weight=3),
    ]
    rig = part(pending=FakePending(items))
    await switch_on(rig, "nudge_focus")
    await tick(rig, at_ist(TUESDAY, "10:00"))
    assert sent(rig) == [("nudge_focus", "Top priority now, Sir: Electricity due.")]


async def test_nothing_pending_sends_no_focus_nudge_and_a_failing_source_is_skipped() -> None:
    rig = part(pending=FakePending(fail=True))
    await switch_on(rig, "nudge_focus")
    await tick(rig, at_ist(TUESDAY, "10:00"))
    await tick(rig, at_ist(TUESDAY, "10:05"))
    assert sent(rig) == []


def test_focus_ranking_is_overdue_today_urgency_pin_then_due() -> None:
    t = datetime(2026, 11, 10, 9, 0)
    items = [
        PendingItem("a", "later", "later"),
        PendingItem("a", "soon late", "soon", due=t + timedelta(hours=2)),
        PendingItem("a", "soon early", "soon", due=t),
        PendingItem("a", "today pinned", "today", weight=5),
        PendingItem("a", "today", "today"),
        PendingItem("a", "overdue", "overdue"),
    ]
    assert [i.label for i in focus.rank(items)] == [
        "overdue",
        "today pinned",
        "today",
        "soon early",
        "soon late",
        "later",
    ]


# ---- free time (item 12) -------------------------------------------------------------------------
IDEAS = (
    Idea(id="0000000a", text="Read a novel", minutes=45, place="indoor"),
    Idea(id="0000000b", text="Cycle by the lake", minutes=60, place="outdoor"),
    Idea(id="0000000c", text="Long hike", minutes=240, place="outdoor"),
)


async def free_rig(rain: FakeRain | None = None) -> Rig:
    cal = FakeCalendar(every_day=[Planned("Dinner with friends", "19:30", "21:00", own=False)])
    rig = part(calendar=cal, rain=rain or FakeRain())
    svc = rig.part.services["service"]
    await svc.store.change(UID, lambda s: s.with_ideas(IDEAS))
    await switch_on(rig, "nudge_free_time")
    return rig


async def test_the_free_time_pick_fits_the_gap_and_avoids_rain() -> None:
    dry, wet = await free_rig(), await free_rig(FakeRain(rainy={TUESDAY}))
    for rig in (dry, wet):
        await tick(rig, at_ist(TUESDAY, "18:00"))
    (_, dry_text), (_, wet_text) = sent(dry)[0], sent(wet)[0]
    assert "about an hour and 30 minutes" in dry_text and "Long hike" not in dry_text
    assert "Read a novel (45 min)" in wet_text


async def test_no_free_gap_or_no_calendar_sends_no_free_time_nudge() -> None:
    busy = FakeCalendar(every_day=[Planned("Workshop", "17:30", "20:00", own=False)])
    rig = part(calendar=busy)
    svc = rig.part.services["service"]
    await svc.store.change(UID, lambda s: s.with_ideas(IDEAS))
    await switch_on(rig, "nudge_free_time")
    await tick(rig, at_ist(TUESDAY, "18:00"))
    assert sent(rig) == []
    unlinked = await free_rig()
    service = unlinked.part.services["service"]
    service.agenda._source = None  # noqa: SLF001 - Google not linked
    await tick(unlinked, at_ist(TUESDAY, "18:00"))
    assert sent(unlinked) == []


async def test_a_calendar_that_did_not_answer_is_retried_next_run() -> None:
    rig = await free_rig()
    rig.calendar.fail = True
    await tick(rig, at_ist(TUESDAY, "18:00"))
    rig.calendar.fail = False
    rig.part.services["service"].agenda.forget(UID)
    await tick(rig, at_ist(TUESDAY, "18:05"))
    assert len(sent(rig)) == 1


def test_an_idea_done_in_the_last_three_days_is_not_picked() -> None:
    done = IDEAS[0].model_copy(update={"last_done": "2026-11-08"})
    assert freetime.pick((done,), 60, None, TUESDAY) is None
    older = done.model_copy(update={"last_done": "2026-11-07"})
    assert freetime.pick((older,), 60, None, TUESDAY) is not None
    assert freetime.pick(IDEAS, 10, None, TUESDAY) is None


# ---- a planned activity that didn't happen (item 11) ---------------------------------------------
async def walk_rig(*, sealed: bool = True, own: bool = True) -> Rig:
    cal = FakeCalendar(every_day=[Planned("Evening walk", "17:00", "17:45", own=own)])
    rig = part(calendar=cal, sealed=sealed)
    await switch_on(rig, "nudge_activity")
    return rig


async def test_a_planned_walk_without_a_check_in_is_asked_about_once() -> None:
    rig = await walk_rig()
    await tick(rig, at_ist(TUESDAY, "17:55"), "activity_check")
    assert sent(rig) == []  # never before end + 15 minutes
    for hhmm in ("18:00", "18:05", "18:30"):
        await tick(rig, at_ist(TUESDAY, hhmm), "activity_check")
    await tick(rig.rebuilt(), at_ist(TUESDAY, "18:10"), "activity_check")
    assert sent(rig) == [("nudge_activity", activity.TEXT.format(word="walk", at="17:00"))]
    assert "Evening" not in sent(rig)[0][1]


async def test_a_walk_he_checked_in_is_not_asked_about() -> None:
    rig = await walk_rig()
    rig.clock.at = at_ist(TUESDAY, "17:50")
    out = await run_tool(rig, "nudge_activity_checkin", word="walk", outcome="done")
    assert "walk" in out["spoken"]
    await tick(rig, at_ist(TUESDAY, "18:00"), "activity_check")
    assert sent(rig) == []


async def test_someone_elses_event_or_no_keyring_asks_nothing() -> None:
    for rig in (await walk_rig(own=False), await walk_rig(sealed=False)):
        await tick(rig, at_ist(TUESDAY, "18:00"), "activity_check")
        assert sent(rig) == []


async def test_a_failing_owner_is_counted_and_never_stops_the_job() -> None:
    rig = await walk_rig()
    rig.calendar.fail = True
    out = await tick(rig, at_ist(TUESDAY, "18:00"), "activity_check")
    assert sent(rig) == [] and "failed" not in out  # no calendar: nothing to ask, no failure
    svc = rig.part.services["service"]

    async def broken(uid: str) -> None:
        raise RuntimeError("store down")

    svc.settings = broken  # type: ignore[method-assign]
    assert (await tick(rig, at_ist(TUESDAY, "18:05"), "activity_check"))["failed"] == 1
