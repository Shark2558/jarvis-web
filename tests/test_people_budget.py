# tests/test_people_budget.py
"""One owner message may research at most 2 people (R4 D-D5)."""

from __future__ import annotations

import pytest

from jarvis.tools.budget import MAX_PEOPLE_CALLS, PEOPLE_LIMIT, take_people_call, turn_budget


def test_a_message_may_research_two_people_then_stops() -> None:
    with turn_budget():
        for _ in range(MAX_PEOPLE_CALLS):
            take_people_call()

        with pytest.raises(RuntimeError, match="people"):
            take_people_call()

    assert MAX_PEOPLE_CALLS == 2 and "people" in PEOPLE_LIMIT.lower()


def test_outside_a_turn_there_is_no_budget() -> None:
    for _ in range(5):
        take_people_call()
