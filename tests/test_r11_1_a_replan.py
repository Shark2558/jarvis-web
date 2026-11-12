# tests/test_r11_1_a_replan.py -- R11.1 Part A, O2b (plan D6): the re-plan after a skipped session.
# Pure: the plan's own rhythm, the sessions that move, busy slots avoided, and the check that no
# session is ever lost (a re-plan that would lose one is refused in code).
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from jarvis.series import replan
from jarvis.series.models import Move, Plan, PlanSession, ReplanRefused, plan_id

IST = ZoneInfo("Asia/Kolkata")
MON = datetime(2026, 11, 16, 19, 0, tzinfo=IST)  # a Monday
NOW = datetime(2026, 11, 24, 20, 20, tzinfo=IST)  # Tue: session 7 ended twenty minutes ago


def weekdays(n: int = 60, *, first: datetime = MON, minutes: int = 60) -> Plan:
    """`n` sessions, Monday to Friday at 19:00, from 16 Nov 2026."""
    sessions, day = [], first
    while len(sessions) < n:
        if day.weekday() < 5:
            k = len(sessions) + 1
            sessions.append(
                PlanSession(
                    n=k,
                    event_id=f"ev{k:05d}",
                    title=f"CCA - Topic {k}",
                    start=day,
                    end=day + timedelta(minutes=minutes),
                    batch="b" + "1" * 16,
                )
            )
        day += timedelta(days=1)
    return Plan(
        id=plan_id("CCA"),
        name="CCA",
        prefix="CCA",
        sessions=sessions,
        created_at=MON,
        updated_at=MON,
    )


def far(plan: Plan) -> datetime:
    return plan.sessions[-1].end + timedelta(days=60)


def test_the_rhythm_is_the_plan_s_own_weekdays_and_time() -> None:
    slots = replan.rhythm(weekdays(), IST)
    assert [(s.weekday, s.at.hour, s.at.minute, s.minutes) for s in slots] == [
        (d, 19, 0, 60) for d in range(5)
    ]


def test_skipping_session_seven_of_sixty_moves_fifty_four_and_keeps_sixty() -> None:
    plan = weekdays()
    assert plan.sessions[6].start == datetime(2026, 11, 24, 19, 0, tzinfo=IST)  # session 7: Tue
    moves = replan.build(plan, 7, [], now=NOW, tz=IST, until=far(plan))
    assert len(moves) == 54 and [m.n for m in moves] == list(range(7, 61))
    replan.verify(plan, 7, moves, now=NOW)  # does not raise
    after = replan.applied(plan, moves, NOW)
    assert len(after.sessions) == len(plan.sessions) == 60
    assert [s.n for s in after.sessions] == list(range(1, 61))
    # every session moves exactly one slot: 7 takes 8's evening, ..., 60 a new Monday
    assert moves[0].start == plan.sessions[7].start == datetime(2026, 11, 25, 19, 0, tzinfo=IST)
    assert moves[0].was == plan.sessions[6].start
    assert all(m.start == plan.sessions[m.n].start for m in moves[:-1])
    assert plan.sessions[-1].start == datetime(2027, 2, 5, 19, 0, tzinfo=IST)  # was a Friday
    assert moves[-1].start == datetime(2027, 2, 8, 19, 0, tzinfo=IST)  # the plan ends later
    assert all(m.end - m.start == timedelta(minutes=60) for m in moves)
    assert [s.state for s in after.sessions[:6]] == ["planned"] * 6
    assert {s.state for s in after.sessions[6:]} == {"moved"}
    starts = [s.start for s in after.sessions]
    assert len(set(starts)) == 60 and starts == sorted(starts)


def test_a_busy_slot_is_avoided_and_nothing_is_lost() -> None:
    plan = weekdays()
    dinner = (
        datetime(2026, 11, 26, 19, 30, tzinfo=IST),
        datetime(2026, 11, 26, 21, 0, tzinfo=IST),
    )  # Thursday evening
    moves = replan.build(plan, 7, [dinner], now=NOW, tz=IST, until=far(plan))
    assert len(moves) == 54
    used = [m.start for m in moves]
    assert datetime(2026, 11, 26, 19, 0, tzinfo=IST) not in used
    assert used[:3] == [
        datetime(2026, 11, 25, 19, 0, tzinfo=IST),
        datetime(2026, 11, 27, 19, 0, tzinfo=IST),  # Thursday skipped
        datetime(2026, 11, 30, 19, 0, tzinfo=IST),
    ]
    assert moves[-1].start == datetime(2027, 2, 9, 19, 0, tzinfo=IST)  # one more day later
    replan.verify(plan, 7, moves, now=NOW)
    assert len(replan.applied(plan, moves, NOW).sessions) == 60


def test_done_and_past_sessions_stay_where_they_are() -> None:
    plan = weekdays()
    sessions = list(plan.sessions)
    sessions[9] = sessions[9].model_copy(update={"state": "done"})  # he did session 10 early
    plan = plan.model_copy(update={"sessions": sessions})
    moves = replan.build(plan, 7, [], now=NOW, tz=IST, until=far(plan))
    moved = [m.n for m in moves]
    assert 10 not in moved and all(n >= 7 for n in moved) and len(moves) == 53
    # an unanswered session that already started is never moved by someone else's skip
    late = NOW + timedelta(days=2)  # Thursday night: 8 and 9 have passed, unanswered
    later = replan.build(plan, 7, [], now=late, tz=IST, until=far(plan))
    assert [m.n for m in later][:2] == [7, 11] and 8 not in [m.n for m in later]


def test_a_re_plan_that_would_lose_a_session_is_refused() -> None:
    plan = weekdays()
    moves = replan.build(plan, 7, [], now=NOW, tz=IST, until=far(plan))
    with pytest.raises(ReplanRefused, match="lose"):
        replan.verify(plan, 7, moves[:-1], now=NOW)  # the last session dropped
    twice = [*moves[:-1], Move(60, moves[-1].was, moves[-2].start, moves[-2].end)]
    with pytest.raises(ReplanRefused, match="same time"):
        replan.verify(plan, 7, twice, now=NOW)  # two sessions in one slot is one lost
    stranger = [
        *moves,
        Move(99, NOW, NOW + timedelta(days=400), NOW + timedelta(days=400, hours=1)),
    ]
    with pytest.raises(ReplanRefused):
        replan.verify(plan, 7, stranger, now=NOW)
    past = [
        Move(m.n, m.was, m.start - timedelta(days=30), m.end - timedelta(days=30)) for m in moves
    ]
    with pytest.raises(ReplanRefused, match="past"):
        replan.verify(plan, 7, past, now=NOW)


def test_when_the_free_slots_run_out_it_says_so_and_moves_nothing() -> None:
    plan = weekdays(10)
    wall = [(NOW, NOW + timedelta(days=400))]  # nothing is free for a year
    with pytest.raises(ReplanRefused, match="free"):
        replan.build(plan, 7, wall, now=NOW, tz=IST, until=far(plan))
    with pytest.raises(ReplanRefused, match="session 99"):
        replan.build(plan, 99, [], now=NOW, tz=IST, until=far(plan))
    done = plan.model_copy(
        update={"sessions": [s.model_copy(update={"state": "done"}) for s in plan.sessions]}
    )
    with pytest.raises(ReplanRefused, match="already done"):
        replan.build(done, 7, [], now=NOW, tz=IST, until=far(done))


def test_two_sessions_a_day_keep_their_own_lengths() -> None:
    sat = datetime(2026, 11, 21, 10, 0, tzinfo=IST)  # a Saturday
    sessions = []
    for week in range(3):
        for k, (hour, minutes) in enumerate([(10, 90), (15, 45)]):
            start = sat.replace(hour=hour) + timedelta(weeks=week)
            n = week * 2 + k + 1
            sessions.append(
                PlanSession(
                    n=n,
                    event_id=f"ev{n:05d}",
                    title=f"S{n}",
                    start=start,
                    end=start + timedelta(minutes=minutes),
                )
            )
    plan = Plan(id="p1", name="Weekend", sessions=sessions, created_at=sat, updated_at=sat)
    now = sat + timedelta(hours=2)  # the first morning session just ended
    moves = replan.build(plan, 1, [], now=now, tz=IST, until=far(plan))
    assert [m.n for m in moves] == [1, 2, 3, 4, 5, 6]
    assert moves[0].start == sat.replace(hour=15) and moves[0].end - moves[0].start == timedelta(
        minutes=90
    )  # the long session keeps its ninety minutes in the afternoon slot
    assert moves[1].start == sat.replace(hour=10) + timedelta(weeks=1)
    replan.verify(plan, 1, moves, now=now)
