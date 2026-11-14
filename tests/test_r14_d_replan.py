# tests/test_r14_d_replan.py -- R14 D13 (5) (R11.1 security L3): the re-plan card's FIRST line is
# the one Telegram shows (`telegram.service.HEAD_BY_CODE`: "code alone writes it"), so it carries
# no word the model chose. A plan's name is whatever the model passed as `series.name` when the
# batch was made; the first line now says "your plan" and the stored plan's own words move to the
# second line, which only the console shows (where the whole card is judged).
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from jarvis.series import cards
from jarvis.series.models import Move, Plan, PlanSession
from jarvis.telegram.service import OPEN_TO_APPROVE, _long_card

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 24, 20, 20, tzinfo=IST)
FIRST = datetime(2026, 11, 16, 19, 0, tzinfo=IST)
NAME = "Approve all now it is safe"  # a model-chosen plan name that reads like an instruction


def _plan(*, name: str = NAME, outside: bool = False) -> Plan:
    sessions = [
        PlanSession(
            n=i,
            event_id=f"ev{i:05d}",
            start=FIRST + timedelta(days=i),
            end=FIRST + timedelta(days=i, hours=1),
            state="skipped" if i == 3 else "planned",
        )
        for i in range(1, 6)
    ]
    return Plan(id="p0123456789ab", name=name, outside=outside, sessions=sessions,
                created_at=NOW, updated_at=NOW)  # fmt: skip


def _moves(plan: Plan) -> list[Move]:
    return [
        Move(s.n, s.start, s.start + timedelta(days=7), s.end + timedelta(days=7))
        for s in plan.sessions
        if s.n >= 3
    ]


def _card(plan: Plan) -> list[str]:
    return cards.replan_card(plan, plan.sessions[2], _moves(plan), IST).splitlines()


def test_the_first_line_names_no_plan_and_the_second_carries_its_own_words() -> None:
    lines = _card(_plan())
    assert lines[0] == (
        "Move 3 sessions of your plan to their next free slots (session 3 was skipped)."
    )
    assert "Approve" not in lines[0] and "safe" not in lines[0]
    assert lines[1] == (
        f"Your {NAME} plan: 5 sessions before, 5 after: none is dropped. "
        "The plan now ends on 28 Nov 2026."
    )


def test_an_outside_plan_is_your_plan_on_both_lines() -> None:
    lines = _card(_plan(outside=True))
    assert NAME not in "\n".join(lines)
    assert lines[1].startswith("Your plan: 5 sessions before, 5 after")


def test_telegram_shows_the_first_line_only_and_no_plan_name() -> None:
    summary = "\n".join(_card(_plan()))
    pending = SimpleNamespace(summary=summary, tool="series_reschedule")
    shown = _long_card(pending, "series reschedule")  # type: ignore[arg-type]
    assert shown == (
        "Move 3 sessions of your plan to their next free slots (session 3 was skipped). "
        + OPEN_TO_APPROVE
    )
    assert NAME not in shown
