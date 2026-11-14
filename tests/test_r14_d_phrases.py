# tests/test_r14_d_phrases.py -- R14 D12, No-AI pass 2 (`offline/phrases_r14.py`): every row of
# the plan's table routes to its ONE tool (or its fixed line) with no model; the phrases are
# anchored (a request inside a longer sentence falls through to pass 1 and its generative check);
# disarm never routes; what a phrase hands a tool passes that tool's own checks.
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from r14_fakes_d import D12_ROWS

from jarvis.belongings.service import clean_fields
from jarvis.groceries.tools import parse_items, parse_names
from jarvis.hardening.ports import HardeningContext
from jarvis.helpers.house.service_request import CONTACT_REFUSAL, check_request
from jarvis.offline import phrases_r14 as p14
from jarvis.offline.r14_part import build
from jarvis.offline.rules import NO_AI_LINE, NoAIRoute, route_no_ai
from jarvis.skills.ids import SKILL_LABELS

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 14, 16, 5, tzinfo=IST)  # a Saturday


def _route(text: str) -> NoAIRoute:
    return route_no_ai(text, NOW, p14.ROUTERS)


def _tool(text: str) -> tuple[str | None, dict[str, Any]]:
    route = _route(text)
    if not route.calls:
        return None, {}
    [call] = route.calls
    return call.tool, call.arguments


ROWS = D12_ROWS


@pytest.mark.parametrize(("text", "tool", "args"), ROWS)
def test_every_row_of_the_table_routes_to_its_tool(
    text: str, tool: str, args: dict[str, Any]
) -> None:
    assert _tool(text) == (tool, args)


def test_the_grocery_quantities_are_read_and_pass_the_tools_checks() -> None:
    tool, args = _tool("add milk, 2 kg rice and 3 onions to my grocery list")
    assert tool == "grocery_add"
    assert args["items"] == [
        {"name": "milk"},
        {"name": "rice", "qty": "2", "unit": "kg"},
        {"name": "onions", "qty": "3"},
    ]
    assert [i.name for i in parse_items(args["items"])] == ["milk", "rice", "onions"]
    _, removed = _tool("remove 2 kg rice, milk & eggs from my grocery list")
    assert parse_names(removed["items"]) == ["rice", "milk", "eggs"]


def test_too_many_or_too_long_items_get_a_fixed_line() -> None:
    many = ", ".join(f"item{i}" for i in range(21))
    assert _route(f"add {many} to my grocery list") == NoAIRoute(reply=p14.TOO_MANY)
    assert _route(f"add {'x' * 81} to my grocery list") == NoAIRoute(reply=p14.TOO_LONG)


def test_the_belongings_and_service_arguments_pass_their_tools_checks() -> None:
    _, put = _tool("I put my reading glasses on top of the fridge")
    assert put == {"item": "reading glasses", "place": "on top of the fridge"}
    clean_fields(put["item"], put["place"])
    for text in ("book a plumber for tomorrow morning", "hire a pest control service this week"):
        _, args = _tool(text)
        check_request(args)


@pytest.mark.parametrize(
    "text",
    [
        "disarm the alarm",
        "Jarvis, disarm the house",
        "disarm",
        "turn off the burglar alarm",
        "switch off the alarm please",
    ],
)
def test_disarm_never_routes(text: str) -> None:
    assert _route(text) == NoAIRoute(reply=p14.DISARM_LINE)


def test_the_time_and_the_date_come_from_the_clock() -> None:
    for text in ("what time is it", "what's the time?", "the time", "current time", "time now"):
        assert _route(text) == NoAIRoute(reply="It's 16:05 (IST), Sir.")
    for text in ("what's the date", "what day is it today?", "today's date", "date today"):
        assert _route(text) == NoAIRoute(reply="Today is Saturday, 14 November 2026, Sir.")


class _Foreign(datetime):
    """A clock whose day and month names come out in another language (a server locale)."""

    def strftime(self, fmt: str) -> str:
        return super().strftime(fmt.replace("%A", "Samstag").replace("%B", "Novembre"))

    def __format__(self, fmt: str) -> str:
        return self.strftime(fmt) if fmt else str(self)


def test_the_day_and_month_words_do_not_depend_on_the_locale() -> None:
    now = _Foreign(2026, 11, 14, 16, 5, tzinfo=IST)
    assert p14.clock("what's the date", now) == NoAIRoute(
        reply="Today is Saturday, 14 November 2026, Sir."
    )


@pytest.mark.parametrize("text", ["time", "date", "Time.", "date?"])
def test_a_bare_time_or_date_word_is_not_a_question(text: str) -> None:
    assert p14.clock(text, NOW) is None  # python review M3 (a): a topic, not the clock


def test_what_can_you_do_lists_the_eleven_skills_and_what_works_with_the_ai_off() -> None:
    for text in ("what can you do", "what can you do without the AI?", "help"):
        route = _route(text)
        assert not route.calls and route.reply == p14.ABILITIES_LINE
    assert all(label in p14.ABILITIES_LINE for label in SKILL_LABELS.values())
    assert len(SKILL_LABELS) == 11 and "groceries" in p14.ABILITIES_LINE
    assert "needs the AI" in p14.ABILITIES_LINE  # what needs writing says so plainly


@pytest.mark.parametrize(
    "text",
    [
        "draft an email to the plumber",
        "summarise my inbox",
        "write me a poem about my grocery list",
        "explain what's expiring in my vault",
        "translate my shopping list into Hindi",
    ],
)
def test_generative_asks_keep_the_fixed_line(text: str) -> None:
    assert _route(text) == NoAIRoute()
    assert _route(text).reply == NO_AI_LINE


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("remind me to add milk to my grocery list in 30 minutes", "reminder_add"),
        ("where is my meeting today", "calendar_list_events"),
        ("what's on my calendar", "calendar_list_events"),
        ("run a systems check", "systems_check"),
    ],
)
def test_a_longer_sentence_falls_through_to_pass_one(text: str, tool: str) -> None:
    assert _tool(text)[0] == tool


@pytest.mark.parametrize(
    "text",
    [
        "add milk",
        "my mother is in the hospital",
        "book a table for two",
        "the alarm went off at 3",
        "what time is my train",
        "backup my phone",
        "where should I go for dinner",
        # code review: "left" and "moved" are about more than things
        "I left the house at 9",
        "I left my job in March",
        "I left my reading glasses on the fridge",
        "I moved the sofa in March",
        "I put the kids in the car",
        "I kept the meeting at 5 pm",
        # code review / python review M3 (b): a person, a place, a ride or money is not a thing
        "where's the toilet",
        "where is my bus",
        "where are the kids",
        "where is my wife",
        "where is my refund",
        "where's my salary",
        "where is my train",
        "where is my cab",
        "where is my money",
    ],
)
def test_near_misses_are_left_alone(text: str) -> None:
    assert all(router(text, NOW) is None for router in p14.ROUTERS)


@pytest.mark.parametrize(
    ("text", "item"),
    [
        ("where are my car keys", "car keys"),
        ("where's my bus pass", "bus pass"),
        ("where is my wife's phone", "wife's phone"),
        ("where did I put the kids' school bags", "kids' school bags"),
    ],
)
def test_a_thing_named_after_a_person_or_a_ride_is_still_a_thing(text: str, item: str) -> None:
    assert _tool(text) == ("belongings_where", {"item": item})


@pytest.mark.parametrize(
    ("text", "args"),
    [
        ("book a handyman for 5 pm", {"job": "other", "when": "5 pm"}),
        ("get a plumber for Saturday morning", {"job": "plumber", "when": "Saturday morning"}),
        ("book a carpenter on tuesday", {"job": "carpenter", "when": "tuesday"}),
        ("book a plumber for 2 leaking taps", {"job": "plumber", "problem": "2 leaking taps"}),
    ],
)
def test_a_service_time_is_never_read_as_the_problem(text: str, args: dict[str, Any]) -> None:
    assert _tool(text) == ("maint_service_request", args)  # code review LOW: "5 pm"


@pytest.mark.parametrize(
    "text",
    [
        "book a plumber to call 9876543210",
        "get an electrician to ring me on 98765 43210 tomorrow",
        "book a cleaner for bit.ly/x",
    ],
)
def test_a_service_ask_with_a_contact_is_refused_with_no_call(text: str) -> None:
    assert _route(text) == NoAIRoute(reply=CONTACT_REFUSAL)  # nothing reaches the gateway


@pytest.mark.parametrize(
    "text", ["", " ", "‮" * 50, "add " + "x, " * 5000 + "y to my grocery list", "🛒" * 900]
)
def test_odd_input_never_breaks_a_router(text: str) -> None:
    for router in p14.ROUTERS:
        out = router(text, NOW)
        assert out is None or isinstance(out, NoAIRoute)


def test_the_part_hands_its_routers_to_the_wiring_one_by_one() -> None:
    from jarvis.config import Settings

    ctx = HardeningContext(s=Settings(_env_file=None), docs=None, audit=None, state=lambda n: None)
    part = build(ctx)
    assert part.name == "noai" and part.tools == () and part.ready == "ready"
    assert part.services["phrases"] == p14.ROUTERS
    assert len(p14.ROUTERS) == len(set(p14.ROUTERS)) == 13
    assert len({r.__name__ for r in p14.ROUTERS}) == 13
