# tests/test_r14_d_phrases.py -- R14 D12, No-AI pass 2 (`offline/phrases_r14.py`): every row of
# the plan's table routes to its ONE tool (or its fixed line) with no model; the phrases are
# anchored (a request inside a longer sentence falls through to pass 1 and its generative check);
# disarm never routes; what a phrase hands a tool passes that tool's own checks.
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from jarvis.belongings.service import clean_fields
from jarvis.groceries.tools import parse_items, parse_names
from jarvis.hardening.ports import HardeningContext
from jarvis.helpers.house.service_request import check_request
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


ROWS: list[tuple[str, str, dict[str, Any]]] = [
    ("add milk and eggs to my grocery list", "grocery_add",
     {"items": [{"name": "milk"}, {"name": "eggs"}]}),
    ("Jarvis, put bread on the shopping list please", "grocery_add",
     {"items": [{"name": "bread"}]}),
    ("what's on my shopping list?", "grocery_list", {}),
    ("show me my grocery list", "grocery_list", {}),
    ("remove milk from my grocery list", "grocery_remove", {"items": ["milk"]}),
    ("tick off 2 kg rice and eggs from the groceries", "grocery_remove",
     {"items": ["rice", "eggs"]}),
    ("what's expiring in my vault", "vault_expiring", {}),
    ("which documents expire soon?", "vault_expiring", {}),
    ("where did I put my passport", "belongings_where", {"item": "passport"}),
    ("where are my spare keys?", "belongings_where", {"item": "spare keys"}),
    ("I kept the keys in the drawer", "belongings_put", {"item": "keys", "place": "the drawer"}),
    ("I've put my passport under the blue file.", "belongings_put",
     {"item": "passport", "place": "under the blue file"}),
    ("is the house armed", "home_status", {}),
    ("home status", "home_status", {}),
    ("arm the alarm", "home_arm", {"mode": "away"}),
    ("arm the house for the night", "home_arm", {"mode": "night"}),
    ("where's my parcel", "gmail_track_packages", {}),
    ("where are my orders?", "gmail_track_packages", {}),
    ("check my email", "gmail_inbox_summary", {}),
    ("any new mail?", "gmail_inbox_summary", {}),
    ("what did I delete", "deleted_list", {}),
    ("show recently deleted", "deleted_list", {}),
    ("what do you remember about Lekha", "memory_search", {"query": "Lekha"}),
    ("search your memory for the plumber's visit", "memory_search",
     {"query": "the plumber's visit"}),
    ("when was my last backup", "vitals_backups", {}),
    ("are my backups ok?", "vitals_backups", {}),
    ("test my backup", "vitals_drill_start", {}),
    ("run a restore drill", "vitals_drill_start", {}),
    ("book a plumber for tomorrow morning", "maint_service_request",
     {"job": "plumber", "when": "tomorrow morning"}),
    ("get an electrician to fix the fan on Saturday", "maint_service_request",
     {"job": "electrician", "problem": "fix the fan", "when": "Saturday"}),
    ("I need an AC repair to look at the bedroom AC", "maint_service_request",
     {"job": "ac", "problem": "look at the bedroom AC"}),
]  # fmt: skip


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
    _, put = _tool("I left my reading glasses on top of the fridge")
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
    for text in ("what time is it", "what's the time?", "time"):
        assert _route(text) == NoAIRoute(reply="It's 16:05 (IST), Sir.")
    for text in ("what's the date", "what day is it today?", "today's date"):
        assert _route(text) == NoAIRoute(reply="Today is Saturday, 14 November 2026, Sir.")


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
    ],
)
def test_near_misses_are_left_alone(text: str) -> None:
    assert all(router(text, NOW) is None for router in p14.ROUTERS)


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
