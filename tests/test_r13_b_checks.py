# tests/test_r13_b_checks.py -- R13 Part B's argument checks and card words
# (docs/plans/r13-wardrobe.md "Tools", D10). A malformed call fails fast in plain words before any
# card; every card is written from fixed words (never his label, a shop's label or the words he
# typed), and a look-up that finds nothing still writes a card.
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_b import BLAZER, BLUE_SHIRT, TEE, TRAY, TWIN, WHITE_SHIRT, rig

from jarvis.tools.external import FENCE_PREFIX
from jarvis.wardrobe.laundry import cards, checks

ENTRY = "rv_" + "0" * 10
LOAD = "ld_" + "0" * 8
BATCH = "bt_" + "0" * 8


@pytest.mark.parametrize(
    ("check", "args"),
    [
        (checks.check_move, {"step": "basket", "pieces": "not a list"}),
        (checks.check_move, {"step": "basket", "pieces": [TEE] * 51}),
        (checks.check_move, {"step": "basket", "query": " "}),
        (checks.check_move, {"step": "basket", "query": "x" * 81}),
        (checks.check_move, {"step": "basket", "more": 11, "category": "tops"}),
        (checks.check_move, {"step": "basket", "more": True}),
        (checks.check_move, {"step": "basket", "more": 1}),  # no category
        (checks.check_move, {"step": "ready", "one_of": [TEE, BLUE_SHIRT]}),
        (checks.check_move, {"step": "basket", "one_of": [TEE]}),
        (
            checks.check_move,
            {"step": "basket", "one_of": [TEE, TWIN], "more": 1, "category": "tops"},
        ),
        (checks.check_move, {"step": "basket", "pieces": [TEE], "place": "drawer"}),
        (checks.check_move, {"step": "drying", "load": "load-1"}),
        (checks.check_move, {"step": "basket", "pieces": [TEE], "rev": -1}),
        (checks.check_move, {"step": "basket", "pieces": [TEE], "client_id": "x"}),
        (checks.check_move, {"step": "basket", "pieces": [TEE], "via": "fax"}),
        (checks.check_review, {"action": "resolve"}),
        (checks.check_review, {"action": "resolve", "entry": ENTRY}),
        (checks.check_review, {"action": "resolve", "entry": ENTRY, "outcome": "maybe"}),
        (
            checks.check_review,
            {"action": "resolve", "entry": ENTRY, "outcome": "moved", "to": "archived"},
        ),
        (checks.check_review, {"action": "blind", "categories": ["hats"]}),
        (checks.check_review, {"action": "blind", "since": "yesterday"}),
        (checks.check_review, {"action": "blind", "since": "2026-11-15T18:00:00"}),
        (
            checks.check_review,
            {"action": "blind", "since": "2026-11-15T18:00:00+05:30", "day": "2026-11-15"},
        ),
        (checks.check_review, {"action": "wipe"}),
        (checks.check_correct, {"piece": "shirt"}),
        (checks.check_correct, {"piece": TEE, "event": "we_1"}),
        (checks.check_send, {"action": "pay", "pieces": [BLAZER]}),
        (checks.check_send, {"action": "send", "pieces": []}),
        (
            checks.check_send,
            {"action": "send", "pieces": [BLAZER], "shop": "Dry cleaner", "due": "18/11"},
        ),
        (
            checks.check_send,
            {"action": "send", "pieces": [BLAZER], "shop": "Dry cleaner", "bag": "123456"},
        ),
        (checks.check_send, {"action": "receive", "pieces": [BLAZER]}),
        (
            checks.check_send,
            {"action": "receive", "pieces": [BLAZER], "batch": BATCH, "to": "washing"},
        ),
        (checks.check_status, {"piece": "shirt"}),
    ],
)
def test_a_malformed_call_fails_fast_in_plain_words(check: Any, args: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        check(args)


@pytest.mark.parametrize(
    ("check", "args"),
    [
        (checks.check_move, {"step": "drying", "load": LOAD}),
        (checks.check_move, {"step": "basket", "one_of": [TEE, TWIN], "via": "panel", "rev": 3}),
        (checks.check_review, {"action": "blind", "places": [TRAY], "day": "2026-11-15"}),
        (
            checks.check_review,
            {"action": "resolve", "entry": ENTRY, "outcome": "moved", "to": "ready"},
        ),
        (
            checks.check_send,
            {"action": "receive", "pieces": [BLAZER], "batch": BATCH, "to": "needs_prep"},
        ),
        (checks.check_correct, {"piece": TEE}),
        (checks.check_status, {}),
    ],
)
def test_a_good_call_passes(check: Any, args: dict[str, Any]) -> None:
    check(args)


async def test_every_card_is_fixed_words_and_a_look_up_that_finds_nothing_still_writes_one() -> (
    None
):
    r = await rig()
    view = await r.view()
    assert cards.move(view, {"step": "basket", "one_of": [WHITE_SHIRT, TWIN]}) == (
        "Put one of 2 matching pieces in the laundry basket (you pick which)"
    )
    assert cards.move(view, {"step": "basket", "query": "white shirt"}) == (
        "Put one of 2 matching pieces in the laundry basket (you pick which)"
    )
    assert cards.move(view, {"step": "basket", "query": "purple scarf"}) == (
        "Record a laundry step for wardrobe pieces (none matches yet)"
    )
    assert cards.move(view, {"step": "basket", "more": 2, "category": "tops"}) == (
        "Note 2 pieces in the laundry basket that you couldn't show"
    )
    assert cards.move(view, {"step": "basket", "pieces": [TEE], "more": 1}) == (
        "Put a grey T-shirt in the laundry basket, and 1 more you couldn't show"
    )
    assert cards.move(view, {"step": "drying", "load": LOAD}) == "Note that a whole load is drying"
    assert cards.move(view, {"step": "ready", "pieces": [TEE, BLUE_SHIRT, WHITE_SHIRT, TWIN]}) == (
        "Note that a grey T-shirt, a light blue shirt and 2 more are back and ready"
    )
    assert cards.move(None, {"step": "basket"}) == "Record a laundry step for wardrobe pieces"
    assert cards.review(view, {"action": "list"}) == "List the laundry checks"
    assert cards.review(view, {"action": "blind", "places": [TRAY]}) == (
        "Hold 2 pieces for a quick check: moved without a scan"
    )
    assert cards.review(view, {"action": "resolve", "outcome": "none", "pieces": [TEE]}) == (
        "Answer a laundry check: it didn't happen about a grey T-shirt"
    )
    assert (
        cards.correct(view, {"piece": TEE})
        == "Strike out a recorded laundry step for a grey T-shirt"
    )
    assert cards.correct(None, {"piece": TEE}) == "Strike out a recorded laundry step"
    assert cards.send(
        view, {"action": "send", "pieces": [BLAZER], "shop": "X", "due": "2026-11-18"}
    ) == ("Note that a charcoal blazer went to an outside laundry, due Wed 18 Nov")
    assert cards.send(view, {"action": "receive", "pieces": [BLAZER]}) == (
        "Note that a charcoal blazer came back from an outside laundry"
    )
    assert cards.send(view, {"action": "send", "pieces": [], "due": "soon"}) == (
        "Note that wardrobe pieces went to an outside laundry"
    )


async def test_a_card_for_a_whole_tool_call_never_carries_his_words() -> None:
    r = await rig()
    card = await r.tool("laundry_review", tainted=True, action="blind", places=[TRAY])
    assert card.pending.summary == "Hold 2 pieces for a quick check: moved without a scan"
    corr = await r.tool("laundry_correct", tainted=True, piece=TEE)
    assert corr.pending.summary == "Strike out a recorded laundry step for a grey T-shirt"
    status = await r.tool("laundry_status", query="white shirt")
    assert status.result["found"] is False and len(status.result["candidates"]) == 2
    await r.desk.move(UID, "basket", pieces=(TEE,))
    one = await r.tool("laundry_status", query="grey tee")
    label = one.result["piece"]["label"]
    assert label.startswith(FENCE_PREFIX) and "Old grey tee" in label
