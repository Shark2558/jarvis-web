# tests/test_r64_c2_chat_costs.py — R6.4 D9 follow-up (workbook row 393, builder C2). C made Costs
# count a reply whose model has no known price as "price unknown", but the chat still showed ₹0 for
# one: a reply's cost and the conversation's cost (ChatResponse, the stored conversation) now carry
# an "unpriced" flag, set exactly as billing counts it, so the console says "price unknown".
from __future__ import annotations

import re
from pathlib import Path

from billing_fakes import UID, UNPRICED_TIERS, PricedMock, billing, registry

from jarvis.api import routes
from jarvis.billing import Billing
from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest, Turn, unpriced_calls
from jarvis.llm.base import Role, ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import Gateway

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"


def _rig(
    settings: Settings, gateway: Gateway | None = None
) -> tuple[Brain, Billing, PricedMock, InMemorySessionStore]:
    """The paid, free and unpriced ("custom") brains of billing_fakes, with the custom brain's
    provider in hand (to script its tool calls)."""
    custom = PricedMock()
    base = registry(PricedMock(), PricedMock())
    specs = [s for s in base.list() if s.id != "custom"]
    specs.append(BrainSpec(id="custom", label="Local", provider=custom, tiers=UNPRICED_TIERS))
    reg = BrainRegistry(specs, default_id="anthropic")
    bill = billing(reg)
    store = InMemorySessionStore(ttl_s=3600)
    brain = Brain(brains=reg, store=store, settings=settings, gateway=gateway, billing=bill)
    return brain, bill, custom, store


def _req(brain: str, text: str = "hello", session: str | None = None) -> ChatRequest:
    return ChatRequest(message=text, user_id=UID, brain=brain, session_id=session)


# ---- 1. the chat: a reply and its conversation say "price unknown" -------------------------------


async def test_a_reply_with_no_known_price_is_flagged(settings: Settings) -> None:
    brain, _, _, _ = _rig(settings)
    r = await brain.chat(_req("custom"))
    assert r.unpriced is True and r.cost_inr == 0.0 and r.unpriced_calls == 1
    again = await brain.chat(_req("custom", "and again", r.session_id))
    assert again.unpriced is True and again.unpriced_calls == 2


async def test_priced_and_free_replies_are_not_flagged(settings: Settings) -> None:
    brain, _, _, _ = _rig(settings)
    paid = await brain.chat(_req("anthropic"))
    free = await brain.chat(_req("gemini"))
    for r in (paid, free):
        assert r.unpriced is False and r.unpriced_calls == 0
    assert paid.cost_inr > 0


async def test_the_mock_provider_is_never_price_unknown(settings: Settings) -> None:
    reg = BrainRegistry.from_settings(settings, MockProvider())  # mock-* models, no price
    store = InMemorySessionStore(ttl_s=60)
    brain = Brain(brains=reg, store=store, settings=settings, billing=billing(reg))
    r = await brain.chat(ChatRequest(message="hi", user_id=UID))
    assert r.unpriced is False and r.unpriced_calls == 0


async def test_the_conversation_keeps_its_count_after_a_switch_to_a_priced_brain(
    settings: Settings,
) -> None:
    brain, _, _, _ = _rig(settings)
    first = await brain.chat(_req("custom"))
    paid = await brain.chat(_req("anthropic", "now Claude", first.session_id))
    assert paid.unpriced is False and paid.unpriced_calls == 1  # the earlier reply still counts
    assert paid.total_cost_inr > 0


async def test_each_model_call_of_a_tool_round_is_counted(
    settings: Settings, gateway: Gateway
) -> None:
    brain, _, custom, store = _rig(settings, gateway)
    custom.script_tool_calls([ToolCall(id="t1", name="list_tasks", arguments={})], "No tasks.")
    r = await brain.chat(_req("custom", "my tasks?"))
    assert r.unpriced is True and r.tool_calls == 1
    assert r.unpriced_calls == 2  # the tool request and the reply: two calls, both unpriced
    stored = await store.get_or_raise(r.session_id)
    asked = [t for t in stored.turns if t.role is Role.ASSISTANT]
    assert [t.unpriced for t in asked] == [True, True]


async def test_an_approval_narrated_by_an_unpriced_brain_is_flagged(
    settings: Settings, gateway: Gateway
) -> None:
    brain, _, custom, _ = _rig(settings, gateway)
    call = ToolCall(id="s1", name="send_message", arguments={"to": "p@example.com", "body": "x"})
    custom.script_tool_calls([call], "Awaiting your approval, Sir.")
    r = await brain.chat(_req("custom", "tell P"))
    custom.script("Sent, Sir.")
    done = await brain.approve(r.pending_approvals[0].id, session_id=r.session_id, user_id=UID)
    assert done.reply == "Sent, Sir." and done.unpriced is True
    assert done.unpriced_calls == r.unpriced_calls + 1


async def test_a_streamed_unpriced_reply_is_stored_flagged(settings: Settings) -> None:
    brain, _, _, store = _rig(settings)
    assert "".join([d async for d in brain.chat_stream(_req("custom", "stream please"))])
    (session,) = await store.list_for_user(UID, limit=1)
    stored = await store.get_or_raise(session.id)
    assert stored.turns[-1].role is Role.ASSISTANT and stored.turns[-1].unpriced is True
    paid = "".join([d async for d in brain.chat_stream(_req("anthropic", "s", session.id))])
    assert paid and (await store.get_or_raise(session.id)).turns[-1].unpriced is False


async def test_the_reopened_conversation_says_how_many_had_no_price(settings: Settings) -> None:
    brain, _, _, store = _rig(settings)
    r = await brain.chat(_req("custom"))
    await brain.chat(_req("anthropic", "and Claude", r.session_id))
    view = await routes.get_session(r.session_id, store=store, brain=brain, uid=UID)
    assert view.unpriced_calls == 1 and view.total_cost_inr > 0


def test_a_turn_stored_before_the_flag_reads_as_priced() -> None:
    old = Turn.model_validate({"role": "assistant", "content": "hi", "model": "x"})
    assert old.unpriced is False and unpriced_calls([old]) == 0


def _js(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _literals(js: str) -> list[str]:
    return re.findall(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`", js)


def test_the_console_says_price_unknown_in_the_reply_and_the_conversation() -> None:
    chat, deck = _js("console.js"), _js("console-deck.js")
    assert "r.unpriced === true" in chat and "'price unknown'" in chat
    assert "r.unpriced_calls" in chat and "sess.unpriced_calls" in chat
    assert "d.unpriced" in deck and "V.unpriced" in deck and "price unknown" in deck
    for js in (chat, deck):
        for lit in _literals(js):
            assert "$" not in re.sub(r"\$\{", "", lit)  # rupees only, never a dollar sign
