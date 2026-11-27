# tests/test_r18_review_approvals_mask.py -- R18 combined review (E-NOTES, I1-NOTES 4.8): the
# Approvals panel's generic card prints a pending card's arguments as JSON, so a waiting
# `calls_place` showed the whole phone number. What a card SHOWS (`PendingApproval`, the Approvals
# list and a chat reply's cards) carries the number masked, as the card's own text does; the gate
# keeps the whole arguments, which are what runs on his approval.
from __future__ import annotations

import json

import pytest
from calls_a1_fakes import NUMBER, UID, known, rig

from jarvis.core.guardrails import ActionRisk, PendingAction
from jarvis.core.models import PendingApproval
from jarvis.llm.base import ToolCall
from jarvis.tools.gateway import GatewayOutcome

GIVE = "+919876543210"


def _action(tool: str = "calls_place", **args: object) -> PendingAction:
    base: dict[str, object] = {"number": NUMBER, "purpose": "Book a pickup"}
    return PendingAction(
        tool=tool,
        arguments=base | args,
        risk=ActionRisk.IRREVERSIBLE,
        summary="Call the number ending 0001: Book a pickup",
        scope=f"{UID}:calls",
    )


def test_review_a_call_card_shows_the_number_masked() -> None:
    action = _action(booking={"give_name": "Sam", "give_number": GIVE, "windows": []})
    shown = PendingApproval.from_action(action)
    text = json.dumps(shown.model_dump(mode="json"))
    assert NUMBER not in text and GIVE not in text and "9000000001" not in text
    assert shown.arguments["number"] == "+91 …0001"
    assert shown.arguments["booking"]["give_number"] == "+91 …3210"
    assert shown.arguments["purpose"] == "Book a pickup"
    assert action.arguments["number"] == NUMBER  # the gate's own copy is whole: it is what runs
    assert action.arguments["booking"]["give_number"] == GIVE


def test_review_other_cards_show_their_arguments_as_before() -> None:
    other = _action(tool="send_email", to="a@example.com")
    assert PendingApproval.from_action(other).arguments == other.arguments


@pytest.mark.parametrize("odd", [None, 7, "", "12"])
def test_review_an_odd_number_value_is_never_shown_whole(odd: object) -> None:
    shown = PendingApproval.from_action(_action(number=odd)).arguments["number"]
    assert shown == "…" or shown is None


async def test_review_the_approvals_list_never_carries_the_whole_number() -> None:
    from jarvis.api import routes

    r = await rig()
    await known(r.store)
    call = ToolCall(id="c1", name="calls_place", arguments={"number": NUMBER, "purpose": "Book"})
    asked = await r.gateway.execute(call, scope=f"{UID}:s1")
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION

    class _Brain:
        gateway = r.gateway

    listed = await routes._pending_models(_Brain(), UID)  # type: ignore[arg-type]
    assert listed and NUMBER not in json.dumps([p.model_dump(mode="json") for p in listed])
    assert asked.pending is not None and asked.pending.arguments["number"] == NUMBER  # runs whole
