# tests/test_r13_b_tools.py -- R13 Part B's five tools through a REAL gateway
# (docs/plans/r13-wardrobe.md "Tools", D10, D18): `laundry_status` R1 (vouches only when every
# string is his typed words or a fixed word), `laundry_move` R2 `spoken_ok` (a spoken, untainted
# turn runs; a tainted round is a card), `laundry_review`, `laundry_correct`, `laundry_send_out` R2.
# Write tools take piece ids; only `laundry_move` also a `query`, kept as typed in the card's stored
# arguments while the card's words come from `preview` through `redact.py` (D10's one exception).
# Results list at most 20 pieces, fence his labels and show a private piece as "a private basic".
from __future__ import annotations

import json

from r13_fakes import UID
from r13_fakes_b import (
    BLAZER,
    BLUE_SHIRT,
    JACKET,
    NAVY_SHIRT,
    PILOT,
    RACK,
    TEE,
    TROUSERS,
    VEST_A,
    rig,
)

from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.gateway import GatewayOutcome
from jarvis.wardrobe.ports import TOOL_OWNER

NAMES = ("laundry_status", "laundry_move", "laundry_review", "laundry_correct", "laundry_send_out")


async def test_the_five_tools_their_risks_and_flags() -> None:
    r = await rig()
    tools = {t.name: t for t in r.part.tools}
    assert tuple(tools) == NAMES and all(TOOL_OWNER[n] == "laundry" for n in tools)
    assert (
        tools["laundry_status"].risk is ActionRisk.READ_ONLY and tools["laundry_status"].may_vouch
    )
    for name in NAMES[1:]:
        assert tools[name].risk is ActionRisk.REVERSIBLE and not tools[name].may_vouch
    assert [n for n, t in tools.items() if t.spoken_ok] == ["laundry_move"]
    assert not any(t.trusted_output or t.undoable for t in tools.values())
    assert all(t.activity_words and t.preview for n, t in tools.items() if n != "laundry_status")
    for t in tools.values():  # nothing orders, pays, calls or sends: no such argument exists
        props = set(t.input_schema["properties"])
        assert not props & {"phone", "pay", "amount", "order", "message", "whatsapp", "call"}


async def test_a_basket_tap_runs_and_fences_his_label() -> None:
    r = await rig()
    res = await r.tool("laundry_move", step="basket", pieces=[NAVY_SHIRT])
    assert res.outcome is GatewayOutcome.EXECUTED, res
    out = res.result
    assert out["status"] == "done" and out["message"] == "Done: a navy shirt is in the laundry."
    (shown,) = out["pieces"]
    assert shown["id"] == NAVY_SHIRT and shown["state"] == "in_laundry"
    assert shown["label"].startswith(FENCE_PREFIX) and "Navy striped shirt" in shown["label"]


async def test_a_private_piece_is_its_slot_in_the_result() -> None:
    r = await rig()
    res = await r.tool("laundry_move", step="basket", pieces=[VEST_A])
    (shown,) = res.result["pieces"]
    assert shown == {"id": VEST_A, "slot": "base layer", "state": "in_laundry",
                     "words": "a private basic"}  # fmt: skip


async def test_spoken_untainted_runs_tainted_is_a_card_with_fixed_words_and_his_query_kept() -> (
    None
):
    r = await rig()
    spoken = await r.tool("laundry_move", spoken=True, step="basket", query="navy striped shirt")
    assert spoken.outcome is GatewayOutcome.EXECUTED
    card = await r.tool("laundry_move", tainted=True, step="basket", query="light blue shirt")
    assert card.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert card.pending.summary == "Put a light blue shirt in the laundry basket"
    assert "Light blue office shirt" not in card.pending.summary
    assert card.pending.arguments["query"] == "light blue shirt"  # D10: kept as typed
    assert await r.state(BLUE_SHIRT) == "ready"  # nothing ran before his approval


async def test_a_card_for_ids_names_pieces_by_fixed_words_and_a_private_one_plainly() -> None:
    r = await rig()
    card = await r.tool("laundry_move", tainted=True, step="basket", pieces=[TEE, VEST_A])
    assert card.pending.summary == "Put a grey T-shirt and a private basic in the laundry basket"


async def test_status_lists_at_most_20_pieces_and_vouches_for_his_own_words() -> None:
    r = await rig()
    every = [p.id for p in PILOT]
    await r.desk.move(UID, "basket", pieces=tuple(every[:22]))
    res = await r.tool("laundry_status")
    out = res.result
    assert res.outcome is GatewayOutcome.EXECUTED and res.trusted
    assert len(out["basket"]) == 20 and out["more"] == 2 and out["counts"]["basket"] == 22
    assert out["message"] == "22 pieces in the laundry basket. Nothing waits for a check."
    blob = json.dumps(out)
    assert "Light blue office shirt" in blob and FENCE_PREFIX in blob


async def test_status_does_not_vouch_for_a_shop_label_written_from_other_peoples_words() -> None:
    r = await rig()
    sent = await r.tool(
        "laundry_send_out", tainted=True, action="send", pieces=[BLAZER], shop="Quick Wash"
    )
    assert sent.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert "Quick Wash" not in sent.pending.summary
    assert sent.pending.summary == "Note that a charcoal blazer went to an outside laundry"
    done = await r.gateway.execute(
        ToolCall(id="t-send", name="laundry_send_out", arguments=sent.pending.arguments),
        confirmation_id=sent.pending.id,
        scope=r.scope,
    )
    assert done.outcome is GatewayOutcome.EXECUTED, done
    status = await r.tool("laundry_status")
    assert not status.trusted  # the shop's label came from a round that read outside words
    assert status.result["batches"][0]["shop"].startswith(FENCE_PREFIX)


async def test_one_pieces_history_through_the_status_tool() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(TEE,))
    res = await r.tool("laundry_status", piece=TEE)
    assert res.result["state"] == "in_laundry" and res.result["step"] == "In laundry since 09:01"


async def test_review_list_resolve_and_blind_through_the_tool() -> None:
    r = await rig()
    from r13_fakes_b import TRAY

    blind = await r.tool("laundry_review", action="blind", places=[TRAY])
    assert blind.result["status"] == "review"
    listed = await r.tool("laundry_review", action="list")
    (entry,) = listed.result["entries"]
    assert entry["kind"] == "rescan" and entry["words"] == "Moved without a scan: check these."
    done = await r.tool("laundry_review", action="resolve", entry=entry["id"], outcome="these")
    assert (
        done.result["status"] == "done" and (await r.tool("laundry_review")).result["entries"] == []
    )


async def test_correct_through_the_tool_strikes_out_the_newest_step_by_default() -> None:
    r = await rig()
    await r.tool("laundry_move", step="basket", pieces=[JACKET])
    res = await r.tool("laundry_correct", piece=JACKET)
    assert res.outcome is GatewayOutcome.EXECUTED and await r.state(JACKET) == "ready"
    assert res.result["message"] == (
        "Done: that step is struck out and the piece's state worked out again."
    )


async def test_send_and_receive_through_the_tool() -> None:
    r = await rig()
    sent = await r.tool(
        "laundry_send_out", action="send", pieces=[BLAZER, TROUSERS], shop="Dry cleaner",
        due="2026-11-18",
    )  # fmt: skip
    batch = sent.result["batch"]
    got = await r.tool("laundry_send_out", action="receive", batch=batch, pieces=[BLAZER])
    assert got.result["message"] == (
        "Noted: 1 of 2 pieces is back from the outside laundry; 1 is still out."
    )


async def test_bad_arguments_fail_fast_and_refusals_are_plain_words() -> None:
    r = await rig()
    bad = await r.tool("laundry_move", step="iron", pieces=[TEE])
    assert bad.outcome is GatewayOutcome.ERROR
    bad_id = await r.tool("laundry_move", step="basket", pieces=["shirt"])
    assert bad_id.outcome is GatewayOutcome.ERROR
    nothing = await r.tool("laundry_move", step="basket")
    assert nothing.outcome is GatewayOutcome.ERROR
    number = await r.tool(
        "laundry_send_out", action="send", pieces=[BLAZER], shop="Call 98470 12345"
    )
    assert number.outcome is GatewayOutcome.ERROR and "phone number" in (number.error or "")
    refused = await r.tool("laundry_move", step="drying", pieces=[TEE])
    assert refused.result == {
        "status": "refused",
        "message": "A grey T-shirt isn't washing, so that step doesn't fit it.",
    }
    unknown = await r.tool("laundry_move", step="basket", pieces=["wi_" + "9" * 12])
    assert unknown.result["status"] == "refused"
    assert unknown.result["message"] == "That piece isn't in your wardrobe."


async def test_without_the_wardrobe_the_tools_say_so() -> None:
    r = await rig(keyring=False)
    res = await r.tool("laundry_move", step="basket", pieces=[TEE])
    assert res.result == {
        "status": "unavailable",
        "message": "Laundry is off: this server has no token key.",
    }
    status = await r.tool("laundry_status")
    assert status.result["status"] == "unavailable"


async def test_a_ready_step_with_a_place_returns_to_it() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(NAVY_SHIRT,))
    res = await r.tool("laundry_move", step="ready", pieces=[NAVY_SHIRT], place=RACK)
    place = res.result["pieces"][0]["place"]
    assert place.startswith(FENCE_PREFIX) and "Shirt rack" in place  # his words, fenced
