# tests/test_calls_approvals.py — R18 A1: approving a call through the gateway (calls_place, R3):
# a card every time, one use, 10 minutes, bound to the number and the card; a passkey for a
# number never called before; the dial grant spent once at dial time and counted.
from __future__ import annotations

import pytest
from calls_a1_fakes import NUMBER, SCOPE, UID, Rig, known, rig

from jarvis.calls.approvals import MSG_NEEDS_PASSKEY, GrantInvalid, approving
from jarvis.calls.cards import CardRefused, card_args, read_draft
from jarvis.calls.limits import LimitRefused, ist_day
from jarvis.calls.models import CallCard, CardStatus
from jarvis.calls.tools import ANSWER_MODE, PLACE
from jarvis.llm.base import ToolCall
from jarvis.tools.context import presenting_proof
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import context_trust

DRAFT = {"number": NUMBER, "purpose": "Book a laundry pickup", "languages": ["ml-IN", "en-IN"]}


def _call(args: dict[str, object], name: str = PLACE) -> ToolCall:
    return ToolCall(id="t1", name=name, arguments=args)


async def _stored_card(r: Rig) -> CallCard:
    card = await r.service.builder.build(UID, read_draft(DRAFT))
    await r.store.put_card(UID, card)
    return card


async def _approve_console(r: Rig, card: CallCard, proof: object = None) -> object:
    call = _call(card_args(card))
    with approving(card.id), context_trust(untrusted=False):
        asked = await r.gateway.execute(call, scope=SCOPE)
        assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and asked.pending
        with presenting_proof(proof if proof != "auto" else f"pk:{asked.pending.id}"):
            return await r.gateway.execute(call, confirmation_id=asked.pending.id, scope=SCOPE)


async def test_a_known_number_is_one_card_then_one_tap() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    done = await _approve_console(r, card)
    assert done.outcome is GatewayOutcome.EXECUTED  # type: ignore[attr-defined]
    assert done.result["status"] == "placing"  # type: ignore[attr-defined]
    stored = await r.store.get_card(UID, card.id)
    assert stored is not None and stored.status is CardStatus.APPROVED
    assert r.starter.started and r.starter.started[0][1] == card.id


async def test_the_card_text_never_carries_the_full_number() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    with approving(card.id), context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(card_args(card)), scope=SCOPE)
    assert asked.pending is not None
    assert "0001" in asked.pending.summary and "9000000001" not in asked.pending.summary
    tail = await r.audit.tail(20)
    assert all("9000000001" not in e.detail for e in tail.entries)


async def test_a_new_number_without_passkeys_in_force_is_refused_before_any_card() -> None:
    r = await rig(passkey=False)
    with context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(DRAFT), scope=SCOPE)
    assert asked.outcome is GatewayOutcome.ERROR and asked.pending is None
    assert "passkey" in (asked.error or "")
    assert await r.gateway.pending() == []


async def test_a_new_number_needs_a_passkey_made_for_that_card() -> None:
    r = await rig(passkey=True)
    card = await _stored_card(r)
    assert card.new_number
    with pytest.raises(PermissionError):
        await _approve_console(r, card, proof=None)
    assert (await r.store.get_card(UID, card.id)).status is CardStatus.DRAFT  # type: ignore[union-attr]
    r2 = await rig(passkey=True)
    card2 = await _stored_card(r2)
    done = await _approve_console(r2, card2, proof="auto")
    assert done.outcome is GatewayOutcome.EXECUTED  # type: ignore[attr-defined]


async def test_a_chat_card_is_built_and_stored_on_approval() -> None:
    r = await rig()
    await known(r.store)
    with context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(DRAFT), scope=SCOPE)
    assert asked.pending is not None
    done = await r.gateway.execute(_call(DRAFT), confirmation_id=asked.pending.id, scope=SCOPE)
    assert done.outcome is GatewayOutcome.EXECUTED
    stored = await r.store.get_card(UID, done.result["card_id"])
    assert stored is not None and stored.status is CardStatus.APPROVED


async def test_an_approval_token_is_spent_once() -> None:
    r = await rig()
    await known(r.store)
    with context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(DRAFT), scope=SCOPE)
    assert asked.pending is not None
    await r.gateway.execute(_call(DRAFT), confirmation_id=asked.pending.id, scope=SCOPE)
    again = await r.gateway.execute(_call(DRAFT), confirmation_id=asked.pending.id, scope=SCOPE)
    assert again.outcome is GatewayOutcome.CONFIRMATION_INVALID
    assert len(r.starter.started) == 1


async def test_an_approval_for_another_number_never_runs() -> None:
    r = await rig()
    await known(r.store)
    await known(r.store, "+919000000002")
    with context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(DRAFT), scope=SCOPE)
    assert asked.pending is not None
    other = DRAFT | {"number": "+919000000002"}
    done = await r.gateway.execute(_call(other), confirmation_id=asked.pending.id, scope=SCOPE)
    assert done.outcome is GatewayOutcome.CONFIRMATION_INVALID and not r.starter.started


async def test_an_approval_expires_after_ten_minutes() -> None:
    r = await rig()
    await known(r.store)
    with context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(DRAFT), scope=SCOPE)
    assert asked.pending is not None
    stored = await r.gateway.gate.store.get(asked.pending.id)
    assert stored is not None
    assert round((stored.expires_at - stored.created_at).total_seconds()) == 600


async def test_a_card_edited_after_it_was_proposed_does_not_run() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    with approving(card.id), context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(card_args(card)), scope=SCOPE)
    assert asked.pending is not None
    edited = card.model_copy(update={"purpose": "Ask for a refund too"})
    await r.store.put_card(UID, edited)
    with approving(card.id):
        done = await r.gateway.execute(
            _call(card_args(edited)), confirmation_id=asked.pending.id, scope=SCOPE
        )
    assert done.outcome is GatewayOutcome.CONFIRMATION_INVALID and not r.starter.started


async def test_the_stored_card_must_match_what_is_approved() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    changed = card_args(card) | {"purpose": "Something else"}
    with approving(card.id), context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(changed), scope=SCOPE)
    assert asked.outcome is GatewayOutcome.ERROR and "changed" in (asked.error or "")


async def test_quiet_hours_refuse_the_card() -> None:
    r = await rig()
    await known(r.store)
    r.clock.advance(hours=10)  # 22:00 IST
    with context_trust(untrusted=False):
        asked = await r.gateway.execute(_call(DRAFT), scope=SCOPE)
    assert asked.outcome is GatewayOutcome.ERROR and "21:00" in (asked.error or "")


async def test_the_dial_spends_the_grant_once_and_counts_the_call() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    await _approve_console(r, card)
    grant_id = r.starter.started[0][2]
    used = await r.service.take_for_dial(UID, grant_id, "call_00000000000a")
    assert used.status is CardStatus.USED
    counts = await r.store.day_counts(UID, ist_day(r.clock()))
    assert counts.calls == 1
    with pytest.raises(GrantInvalid):
        await r.service.take_for_dial(UID, grant_id, "call_00000000000a")
    assert await r.service.confirm_dial(grant_id, "call_00000000000a", NUMBER)
    assert not await r.service.confirm_dial(grant_id, "call_00000000000a", NUMBER)  # once


async def test_the_phone_check_refuses_another_call_or_number() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    await _approve_console(r, card)
    grant_id = r.starter.started[0][2]
    assert not await r.service.confirm_dial(grant_id, "call_00000000000a", NUMBER)  # not dialled
    await r.service.take_for_dial(UID, grant_id, "call_00000000000a")
    assert not await r.service.confirm_dial(grant_id, "call_00000000000b", NUMBER)
    assert not await r.service.confirm_dial(grant_id, "call_00000000000a", "+919000000002")


async def test_a_grant_expires_after_ten_minutes() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    await _approve_console(r, card)
    r.clock.advance(minutes=10, seconds=1)
    with pytest.raises(GrantInvalid):
        await r.service.take_for_dial(UID, r.starter.started[0][2], "call_00000000000a")


async def test_a_limit_at_dial_time_refuses_and_spends_the_grant() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    await _approve_console(r, card)
    day = ist_day(r.clock())
    for _ in range(2):
        await r.store.count_call(UID, day, NUMBER)
    with pytest.raises(LimitRefused):
        await r.service.take_for_dial(UID, r.starter.started[0][2], "call_00000000000a")
    with pytest.raises(GrantInvalid):
        await r.service.take_for_dial(UID, r.starter.started[0][2], "call_00000000000a")


async def test_cancel_drops_the_grant() -> None:
    r = await rig()
    await known(r.store)
    card = await _stored_card(r)
    await _approve_console(r, card)
    cancelled = await r.service.cancel(UID, card.id)
    assert cancelled.status is CardStatus.CANCELLED
    with pytest.raises(GrantInvalid):
        await r.service.take_for_dial(UID, r.starter.started[0][2], "call_00000000000a")
    with pytest.raises(CardRefused):
        await r.service.cancel(UID, card.id)


async def test_place_never_runs_outside_an_approval() -> None:
    r = await rig()
    from jarvis.tools.context import tool_context

    with tool_context(SCOPE), pytest.raises(PermissionError):
        await r.service.place(DRAFT)


async def test_needs_passkey_words_say_how() -> None:
    assert "Approvals → Permissions" in MSG_NEEDS_PASSKEY


async def test_answer_mode_on_is_a_card_and_off_runs_at_once() -> None:
    r = await rig()
    with context_trust(untrusted=False):
        on = await r.gateway.execute(
            _call({"on": True, "after_rings": 4, "policy": "contacts"}, ANSWER_MODE), scope=SCOPE
        )
    assert on.outcome is GatewayOutcome.AWAITING_CONFIRMATION and on.pending is not None
    done = await r.gateway.execute(
        _call({"on": True, "after_rings": 4, "policy": "contacts"}, ANSWER_MODE),
        confirmation_id=on.pending.id,
        scope=SCOPE,
    )
    assert done.outcome is GatewayOutcome.EXECUTED
    settings = await r.store.settings(UID)
    assert settings.answering_on and settings.answer_after_rings == 4
    with context_trust(untrusted=False):
        off = await r.gateway.execute(_call({"on": False}, ANSWER_MODE), scope=SCOPE)
    assert off.outcome is GatewayOutcome.EXECUTED
    assert not (await r.store.settings(UID)).answering_on
