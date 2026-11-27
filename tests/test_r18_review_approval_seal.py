# tests/test_r18_review_approval_seal.py -- R18 combined review (the ADD writer's item 1): a waiting
# call card's number was stored in plain text in the `approvals` collection (the pending
# `calls_place` arguments), while every other R18 number is sealed with the keyring's `calls`
# purpose. The approval store now seals it (and a booking's give_number) on the way in and opens it
# on the way out, bound to the approval's id; the masked display stays as it was.
from __future__ import annotations

import json

import pytest
from calls_a1_fakes import NUMBER, SCOPE, known, rig

from jarvis.calls.pending import CallNumberSeal, seal_pending_calls
from jarvis.core.guardrails import ActionRisk, PendingAction
from jarvis.core.models import PendingApproval
from jarvis.keyring import Keyring
from jarvis.llm.base import ToolCall
from jarvis.storage.approvals import DocApprovalStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.gateway import Gateway, GatewayOutcome

GIVE = "+919876543210"
RING = Keyring(bytes(range(32)))


def _call(**args: object) -> PendingAction:
    base: dict[str, object] = {"number": NUMBER, "purpose": "Book a pickup"}
    return PendingAction(
        tool="calls_place",
        arguments=base | args,
        risk=ActionRisk.IRREVERSIBLE,
        summary="Call the number ending 0001: Book a pickup",
        scope=SCOPE,
    )


def _store() -> tuple[DocApprovalStore, MemoryDocs]:
    docs = MemoryDocs()
    store = DocApprovalStore(docs, prefix="t_")
    store.use_seal(CallNumberSeal(RING.cipher("calls")))
    return store, docs


def _raw(docs: MemoryDocs) -> str:
    return json.dumps(docs._data, default=str)


async def test_review_a_waiting_call_s_number_is_sealed_at_rest() -> None:
    store, docs = _store()
    action = _call(booking={"give_name": "Sam", "give_number": GIVE, "windows": []})
    await store.put(action)
    raw = _raw(docs)
    assert (
        NUMBER not in raw
        and "9000000001" not in raw
        and GIVE not in raw
        and "9876543210" not in raw
    )
    got = await store.get(action.id)
    assert got is not None and got.arguments == action.arguments  # opened whole for the gate
    assert [a.arguments["number"] for a in await store.pending_in(SCOPE)] == [NUMBER]
    assert [a.arguments["number"] for a in await store.list_pending()] == [NUMBER]
    shown = PendingApproval.from_action(got)
    assert shown.arguments["number"] == "+91 …0001"  # the masked display stays


async def test_review_the_sealed_card_is_consumed_and_cancelled_whole() -> None:
    store, _ = _store()
    first, second = _call(), _call(purpose="Ask about the shirt")
    await store.put(first)
    await store.put(second)
    taken = await store.consume(first.id, lambda a: a.arguments["number"] == NUMBER)
    assert taken is not None and taken.arguments["number"] == NUMBER
    gone = await store.cancel(second.id)
    assert gone is not None and gone.arguments["number"] == NUMBER


async def test_review_a_sealed_number_moved_to_another_card_never_opens() -> None:
    store, docs = _store()
    one, two = _call(), _call(number="+919000000002")
    await store.put(one)
    await store.put(two)
    path_one, path_two = f"t_approvals/{one.id}", f"t_approvals/{two.id}"
    a, b = json.loads(docs._data[path_one]["json"]), json.loads(docs._data[path_two]["json"])
    b["arguments"]["number"] = a["arguments"]["number"]  # swap a sealed number between cards
    docs._data[path_two] = {**docs._data[path_two], "json": json.dumps(b)}
    assert await store.get(two.id) is None  # unreadable, never a wrong number


async def test_review_other_cards_are_stored_as_before() -> None:
    store, docs = _store()
    other = PendingAction(
        tool="send_email",
        arguments={"to": "a@example.com", "body": "hi"},
        risk=ActionRisk.IRREVERSIBLE,
        summary="Send",
        scope=SCOPE,
    )
    await store.put(other)
    assert "a@example.com" in _raw(docs)
    assert (await store.get(other.id)) == other


async def test_review_the_gateway_flow_runs_on_the_sealed_store() -> None:
    r = await rig()
    await known(r.store)
    store, docs = _store()
    gw = Gateway(
        registry=r.gateway.registry,
        policy=r.gateway.policy,
        gate=type(r.gateway.gate)(store),
        audit=r.audit,
        approval_guard=r.guard,
    )
    call = ToolCall(id="c1", name="calls_place", arguments={"number": NUMBER, "purpose": "Book"})
    asked = await gw.execute(call, scope="u_0123456789abcdef:s1")
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and asked.pending is not None
    assert NUMBER not in _raw(docs)
    done = await gw.execute(call, confirmation_id=asked.pending.id, scope="u_0123456789abcdef:s1")
    assert done.outcome is GatewayOutcome.EXECUTED, done.error
    assert r.starter.started  # the approved call started, its number opened whole


def test_review_the_wiring_seals_a_document_store_only() -> None:
    class _Gate:
        def __init__(self, store: object) -> None:
            self.store = store

    class _Gw:
        def __init__(self, store: object) -> None:
            self.gate = _Gate(store)

    doc = DocApprovalStore(MemoryDocs())
    assert seal_pending_calls(_Gw(doc), RING) is True and doc.seal is not None
    assert seal_pending_calls(_Gw(object()), RING) is False  # in memory: nothing at rest


@pytest.mark.parametrize("odd", [None, 7, ["+919000000001"]])
async def test_review_an_odd_number_value_is_left_to_the_tool_s_own_check(odd: object) -> None:
    store, _ = _store()
    action = _call(number=odd)
    await store.put(action)
    got = await store.get(action.id)
    assert got is not None and got.arguments["number"] == odd


async def test_review_the_joined_app_puts_the_seal_on_its_gateway(
    settings: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64

    from pydantic import SecretStr

    from jarvis.api import create_app
    from jarvis.api import r18_wiring as wiring
    from jarvis.llm.mock_provider import MockProvider
    from jarvis.memory.inmemory import InMemorySessionStore

    seen: list[object] = []
    monkeypatch.setattr(wiring, "seal_pending_calls", lambda gw, ring: seen.append(gw) or True)
    key = SecretStr(base64.b64encode(bytes(range(1, 33))).decode())
    s = settings.model_copy(update={"token_key": key, "tools_enabled": True})  # type: ignore[attr-defined]
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        assert seen == [app.state.gateway]
