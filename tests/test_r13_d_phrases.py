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
#   - M4 (REVIEW-D-1): R14's put verbs and places are inside R13's; every one of them with a
#     wardrobe word stays the wardrobe's, never `belongings_put`; "wifes" is a person word
#   - M6: A's shapes: a count is `{type}` (a type or a category); the move resolves the piece with
#     `wardrobe_find` and edits by id (`TakeCall`, D10: no `query` reaches `wardrobe_edit`); with
#     I1's runner step (r13_fakes_d.run_taking) a name that fits several pieces moves nothing
#   - L9: on Telegram every D20 sentence is refused with the personal switch off (nothing runs) and
#     reaches its tools with it on
from __future__ import annotations

import re
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
    out, before = [], ""
    for c in route_no_ai(text, NOW, routers).calls:  # a taken value is shown as where it comes from
        took = {arg: f"<{key} of {before}>" for arg, key in getattr(c, "take", ())}
        out.append((c.tool, {**c.arguments, **took}))
        before = c.tool
    return out


Calls = list[tuple[str, dict[str, Any]]]


def _find(q: str) -> Calls:
    return [("wardrobe_find", {"query": q}), ("belongings_where", {"item": q})]


def _move(step: str, q: str) -> Calls:
    return [("laundry_move", {"step": step, "query": q})]


def _wear(action: str, q: str | None = None, **more: str) -> Calls:
    return [("wear_log", {"action": action, **({"query": q} if q else {}), **more})]


def _edit(q: str, place: str) -> Calls:
    took = {"place": place, "piece": "<best of wardrobe_find>"}
    return [("wardrobe_find", {"query": q}), ("wardrobe_edit", took)]


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
    ("I hid my watch in the drawer", _edit("watch", "drawer")),
    ("I put my belt on top of the cupboard", _edit("belt", "on top of the cupboard")),
    ("I hung my blue shirt on the rail", _edit("blue shirt", "rail")),
    ("how many shirts do I have", [("wardrobe_count", {"type": "shirt"})]),
    ("how many socks are ready", [("wardrobe_count", {"type": "sock"})]),
    ("how many shoes do I have?", [("wardrobe_count", {"type": "footwear"})]),
    ("how many T-shirts have I got", [("wardrobe_count", {"type": "t shirt"})]),
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
    "my wifes shirt is in the laundry",  # the apostrophe left out (M4)
    "I put my husbands watch in the drawer",
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
    assert [tool for tool, _ in _calls(put)] == ["wardrobe_find", "wardrobe_edit"]


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


# ---- M4: R14's put forms never take a wardrobe word ------------------------------------------
def _r14_lists() -> tuple[set[str], set[str]]:
    pattern = p14.PUT.pattern
    verbs = re.search(r"\(\?:(kept\|[^)]*)\)", pattern)
    preps = re.search(r"\(\?P<prep>([^)]*)\)", pattern)
    assert verbs is not None and preps is not None
    words = {p.replace("\\s+", " ") for p in preps.group(1).split("|")}
    return set(verbs.group(1).split("|")), words


def test_m4_r14s_put_verbs_and_places_are_all_inside_r13s() -> None:
    verbs, preps = _r14_lists()
    assert verbs and preps and verbs <= set(p13.PUT_VERBS) and preps <= set(p13.PUT_PREPS)
    assert p13.PUT_PREPS.index("on top of") < p13.PUT_PREPS.index("on")


def _matrix() -> list[str]:
    verbs, preps = _r14_lists()
    items = ("watch", "black belt", "shoes", "blue shirt")
    return [
        f"I {v} my {i} {p} the drawer" for v in sorted(verbs) for p in sorted(preps) for i in items
    ]


@pytest.mark.parametrize("text", _matrix())
def test_m4_every_r14_put_form_with_a_wardrobe_word_is_the_wardrobes(text: str) -> None:
    tools = [tool for tool, _ in _calls(text)]
    assert tools == ["wardrobe_find", "wardrobe_edit"], text


# ---- M6: the move edits by id; I1's runner step fills it, or stops ---------------------------
async def test_m6_the_move_edits_the_piece_wardrobe_find_resolved_and_nothing_on_a_tie() -> None:
    from r13_fakes_d import run_taking

    one = await run_taking(
        p13.put("I put my watch in the travel bag", NOW), {"best": "wi_00000000001f"}
    )
    assert one == [
        ("wardrobe_find", {"query": "watch"}),
        ("wardrobe_edit", {"place": "travel bag", "piece": "wi_00000000001f"}),
    ]
    tie = await run_taking(p13.put("I put my watch in the travel bag", NOW), {"best": None})
    assert tie == [("wardrobe_find", {"query": "watch"})]  # several fit: the find's words, no move
    route = p13.put("I put my watch in the travel bag", NOW)
    assert route is not None and all("query" not in c.arguments for c in route.calls[1:])


# ---- L9: D20 over Telegram, the personal switch off and on --------------------------------------
TELEGRAM_ROWS = [(text, calls[0][0]) for text, calls in ROWS if calls[0][0] in NO_AI_TOOLS]


@pytest.mark.parametrize("personal", [False, True], ids=["switch_off", "switch_on"])
@pytest.mark.parametrize(("text", "tool"), TELEGRAM_ROWS, ids=[r[0] for r in TELEGRAM_ROWS])
async def test_l9_a_d20_sentence_on_telegram_follows_the_personal_switch(
    text: str, tool: str, personal: bool
) -> None:
    from r13_fakes import UID
    from r13_fakes_d import telegram_gateway

    from jarvis.core.channel import telegram_turn
    from jarvis.offline.no_ai import run_no_ai
    from jarvis.tools.gateway import GatewayOutcome

    gw, seen = await telegram_gateway(personal=personal)
    with telegram_turn():
        out = await run_no_ai(gw, text, NOW, scope=f"{UID}:tg", extra=p13.ROUTERS)
    assert out.calls and out.calls[0].name == tool
    if not personal:
        assert [r.outcome for r in out.results] == [GatewayOutcome.DENIED] and seen == []
        assert "Telegram" in (out.results[0].error or "") and "Sir" in out.reply  # nothing read
        return
    assert out.results[0].outcome is not GatewayOutcome.DENIED
    assert seen[:1] == [tool] or out.results[0].outcome is GatewayOutcome.AWAITING_CONFIRMATION
