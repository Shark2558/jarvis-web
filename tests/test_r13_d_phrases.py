# tests/test_r13_d_phrases.py -- R13 Part D, No-AI pass 3 (docs/plans/r13-wardrobe.md D6, D20):
# `offline/phrases_r13.py`, anchored like R14's (the whole message is the phrase), installed FIRST.
#   - every row of D20's table routes to its tool calls (gateway calls only; no model)
#   - "where is my <wardrobe word>" makes TWO calls, the wardrobe's then Things' (a "Never" on
#     Things is kept: each call has its own row); R14's PUT form for a wardrobe word is the
#     wardrobe's move; the laundry's "put ... in the wash" wins over R14's PUT
#   - never a possessive, never R14's not-a-thing words, never the accessory words that are Things
#     (bag, glasses, spectacles, keys, wallet, umbrella); a longer sentence is not taken
#   - every R14 phrase test still routes as before with R13's routers installed first; only the two
#     moves D6 names change (a belt's "where" and a watch's "put")
#   - the routers reach No-AI mode first and in their order through I0's wiring
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from r14_fakes_d import D12_ROWS

from jarvis.api.r13_wiring import install_r13_phrases
from jarvis.config import Settings
from jarvis.offline import phrases_r13 as p13
from jarvis.offline import phrases_r14 as p14
from jarvis.offline.mode import BrainMode
from jarvis.offline.rules import NoAIRoute, route_no_ai
from jarvis.wardrobe.ports import NO_AI_TOOLS, WardrobePart

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 16, 23, 30, tzinfo=IST)  # a fixed clock; the day words are the tool's
BOTH = (*p13.ROUTERS, *p14.ROUTERS)


def _calls(text: str, routers: tuple[Any, ...] = BOTH) -> list[tuple[str, dict[str, Any]]]:
    return [(c.tool, c.arguments) for c in route_no_ai(text, NOW, routers).calls]


Calls = list[tuple[str, dict[str, Any]]]


def _find(q: str) -> Calls:
    return [("wardrobe_find", {"query": q}), ("belongings_where", {"item": q})]


def _move(step: str, q: str) -> Calls:
    return [("laundry_move", {"step": step, "query": q})]


def _wear(action: str, q: str | None = None, **more: str) -> Calls:
    return [("wear_log", {"action": action, **({"query": q} if q else {}), **more})]


def _edit(q: str, place: str) -> Calls:
    return [("wardrobe_edit", {"query": q, "place": place})]


ROWS: list[tuple[str, Calls]] = [
    ("what should I wear tomorrow", [("outfit_suggest", {"day": "tomorrow"})]),
    ("What should I wear today?", [("outfit_suggest", {"day": "today"})]),
    ("Jarvis, what do I wear tonight", [("outfit_suggest", {"day": "today"})]),
    ("what should I wear for Diwali", [("outfit_suggest", {"occasion": "Diwali"})]),
    ("what should I wear for the meeting", [("outfit_suggest", {"occasion": "meeting"})]),
    (
        "what should I wear tomorrow for the meeting",
        [("outfit_suggest", {"day": "tomorrow", "occasion": "meeting"})],
    ),
    ("what to wear tomorrow", [("outfit_suggest", {"day": "tomorrow"})]),
    ("where is my black belt", _find("black belt")),
    ("where are my brown shoes?", _find("brown shoes")),
    ("where's my steel watch", _find("steel watch")),
    ("where did I put my navy blazer", _find("navy blazer")),
    ("I put my watch in the travel bag", _edit("watch", "travel bag")),
    ("I kept the black belt in drawer 2", _edit("black belt", "drawer 2")),
    ("my navy shirt is in the laundry", _move("basket", "navy shirt")),
    ("put the white shirt in the wash", _move("basket", "white shirt")),
    ("I put my grey socks in the laundry basket", _move("basket", "grey socks")),
    ("the white shirt is back", _move("ready", "white shirt")),
    ("the white shirt is clean.", _move("ready", "white shirt")),
    ("my jeans are back from the dhobi", _move("ready", "jeans")),
    ("what's in the laundry", [("laundry_status", {})]),
    ("laundry status", [("laundry_status", {})]),
    ("what is in the wash", [("laundry_status", {})]),
    ("I'm wearing the blue shirt", _wear("start", "blue shirt")),
    ("wearing the meeting outfit", _wear("start", "meeting outfit")),
    ("I am wearing my charcoal trousers today", _wear("start", "charcoal trousers")),
    ("I wore the blue shirt today", _wear("done", "blue shirt")),
    ("I wore my blue shirt yesterday", _wear("done", "blue shirt", day="yesterday")),
    ("done for today", _wear("done")),
    ("I'm done for today", _wear("done")),
    ("how many shirts do I have", [("wardrobe_count", {"type": "shirt"})]),
    ("how many socks are ready", [("wardrobe_count", {"type": "sock", "ready": True})]),
    ("how many shoes do I have?", [("wardrobe_count", {"category": "footwear"})]),
    ("how many T-shirts have I got", [("wardrobe_count", {"type": "t_shirt"})]),
]


@pytest.mark.parametrize(("text", "calls"), ROWS, ids=[r[0] for r in ROWS])
def test_every_row_of_d20_routes_to_its_tool_calls(text: str, calls: Calls) -> None:
    assert _calls(text) == calls


def test_every_tool_a_phrase_names_is_a_no_ai_tool() -> None:
    named = {tool for _, calls in ROWS for tool, _ in calls}
    assert named - {"belongings_where"} <= NO_AI_TOOLS  # Things' own tool is R14's


NEAR_MISSES = [
    "where is my wife's watch",  # someone else's: a possessive is never the wardrobe's
    "where are the kids' shoes",
    "my wife's shirt is in the laundry",
    "where is my bag",  # the accessory words that are usually Things
    "where are my glasses",
    "where are my spectacles",
    "where are my keys",
    "where's my wallet",
    "where is my umbrella",
    "I put my bag in the car",
    "where is my train",  # R14's not-a-thing words
    "where are the kids",
    "I put the kids in the car",
    "where is my black belt buckle",  # the last word decides: a buckle is not a piece
    "where is my meeting today",
    "what should I write tomorrow",
    "what should I wear to impress my boss when the meeting runs late and it rains",
    "can you tell me where is my black belt and also what to cook",  # a longer sentence
    "how many",
    "how many emails do I have",
    "wearing",
    "I wore",
]


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_near_misses_are_not_the_wardrobes(text: str) -> None:
    assert all(router(text, NOW) is None for router in p13.ROUTERS), text


def _r14_texts() -> list[str]:
    texts = [row[0] for row in D12_ROWS]
    texts += [
        "where are my car keys",
        "where's my bus pass",
        "where is my wife's phone",
        "where did I put the kids' school bags",
        "I left my reading glasses on the fridge",
        "I put my reading glasses on top of the fridge",
        "where is my wife's watch",
        "where are the kids' shoes",
        "where is my bag",
        "I put my bag in the car",
    ]
    return texts


@pytest.mark.parametrize("text", _r14_texts())
def test_every_r14_phrase_routes_as_before_with_r13_first(text: str) -> None:
    assert route_no_ai(text, NOW, BOTH) == route_no_ai(text, NOW, p14.ROUTERS)


def test_only_the_two_moves_d6_names_change() -> None:
    before = _calls("where is my black belt", p14.ROUTERS)
    assert before == [("belongings_where", {"item": "black belt"})]
    assert _calls("where is my black belt") == _find("black belt")
    put = "I put my watch in the travel bag"
    assert _calls(put, p14.ROUTERS) == [
        ("belongings_put", {"item": "watch", "place": "the travel bag"})
    ]
    assert _calls(put)[0][0] == "wardrobe_edit"


@pytest.mark.parametrize(
    "text", ["", " ", "‮" * 50, "where is my " + "belt " * 400, "\U0001f455" * 900]
)
def test_odd_input_never_breaks_a_router(text: str) -> None:
    for router in p13.ROUTERS:
        out = router(text, NOW)
        assert out is None or isinstance(out, NoAIRoute)


def test_a_query_is_his_words_bounded() -> None:
    long_item = "very " * 20 + "long navy shirt"
    assert all(router(f"my {long_item} is in the laundry", NOW) is None for router in p13.ROUTERS)
    [(_, args)] = _calls("my   Navy  Shirt is in the laundry")
    assert args == {"step": "basket", "query": "Navy Shirt"}


def test_the_routers_go_first_and_in_their_order_through_the_wiring() -> None:
    mode = BrainMode(Settings(_env_file=None))
    mode.add_phrases(list(p14.ROUTERS))
    part = WardrobePart("phone", services={"phrases": p13.ROUTERS}, ready="ready")
    app = SimpleNamespace(state=SimpleNamespace(brain_mode=mode, r13_parts={"phone": part}))
    install_r13_phrases(app)  # type: ignore[arg-type]
    assert mode.phrases[: len(p13.ROUTERS)] == p13.ROUTERS
    assert mode.phrases[len(p13.ROUTERS) :] == p14.ROUTERS
    install_r13_phrases(app)  # type: ignore[arg-type]  # twice: nothing added twice
    assert len(mode.phrases) == len(p13.ROUTERS) + len(p14.ROUTERS)
    assert all(r.__name__.startswith("r13_") for r in p13.ROUTERS)
