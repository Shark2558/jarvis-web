# tests/test_brain.py
from __future__ import annotations

import pytest

from jarvis.core.brain import Brain
from jarvis.core.guardrails import InputRejected
from jarvis.core.models import ChatRequest
from jarvis.llm.base import LLMTransientError, Role
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.base import SessionNotFound
from jarvis.memory.inmemory import InMemorySessionStore


async def test_first_turn_creates_session_and_persists_both_turns(
    brain: Brain, provider: MockProvider, store: InMemorySessionStore
) -> None:
    provider.script("Good afternoon, Sir.")
    resp = await brain.chat(ChatRequest(message="Hello JARVIS"))

    assert resp.reply == "Good afternoon, Sir."
    assert resp.turn_count == 2
    assert resp.model == "mock-balanced"  # default tier
    session = await store.get(resp.session_id)
    assert session is not None
    assert [t.role for t in session.turns] == [Role.USER, Role.ASSISTANT]
    assert session.turns[1].usage is not None


async def test_session_memory_carries_context(brain: Brain, provider: MockProvider) -> None:
    r1 = await brain.chat(ChatRequest(message="My name is Akash"))
    r2 = await brain.chat(ChatRequest(message="What is my name?", session_id=r1.session_id))

    assert r2.session_id == r1.session_id
    assert r2.turn_count == 4
    # the second LLM call must have seen the first exchange
    second_call = provider.calls[1]
    assert [m.content for m in second_call.messages] == [
        "My name is Akash",
        "Certainly, Sir. You said: My name is Akash",
        "What is my name?",
    ]


async def test_system_prompt_is_stable_and_trailer_is_dynamic(
    brain: Brain, provider: MockProvider
) -> None:
    r1 = await brain.chat(ChatRequest(message="one"))
    await brain.chat(ChatRequest(message="two", session_id=r1.session_id))
    s1, s2 = provider.calls[0].system, provider.calls[1].system
    # persona (cacheable prefix) identical; only the trailer differs
    assert s1.split("Session context")[0] == s2.split("Session context")[0]
    assert "turn 1" in s1 and "turn 3" in s2
    assert "Sir" in s1


async def test_rolling_window_is_bounded(brain: Brain, provider: MockProvider, settings) -> None:
    sid = (await brain.chat(ChatRequest(message="t0"))).session_id
    for i in range(1, 8):
        await brain.chat(ChatRequest(message=f"t{i}", session_id=sid))
    last = provider.calls[-1]
    assert len(last.messages) <= settings.session_max_turns
    assert last.messages[0].role is Role.USER
    assert last.messages[-1].content == "t7"


async def test_tier_override_and_degradation(provider: MockProvider, store, settings) -> None:
    tiers = {ModelTier.FAST: "f", ModelTier.BALANCED: "b", ModelTier.STRONG: "s"}
    brain = Brain(router=ModelRouter(provider, tiers), store=store, settings=settings)

    r = await brain.chat(ChatRequest(message="plan my week", tier="strong"))
    assert r.model == "s"

    provider.fail_next = 1  # STRONG fails once → BALANCED serves the request
    r = await brain.chat(ChatRequest(message="again", tier="strong", session_id=r.session_id))
    assert r.model == "b"
    assert [c.model for c in provider.calls[-2:]] == ["s", "b"]

    provider.fail_next = 3  # every tier fails → error surfaces, user turn still persisted
    with pytest.raises(LLMTransientError):
        await brain.chat(ChatRequest(message="x", tier="strong", session_id=r.session_id))
    session = await store.get(r.session_id)
    assert session is not None and session.turns[-1].role is Role.USER


async def test_input_guard(brain: Brain) -> None:
    with pytest.raises(InputRejected):
        await brain.chat(ChatRequest(message="   \x00  "))
    with pytest.raises(InputRejected):
        await brain.chat(ChatRequest(message="x" * 501))


async def test_unknown_or_foreign_session_rejected(brain: Brain) -> None:
    with pytest.raises(SessionNotFound):
        await brain.chat(ChatRequest(message="hi", session_id="sess_nope"))
    r = await brain.chat(ChatRequest(message="hi", user_id="owner"))
    with pytest.raises(SessionNotFound):
        await brain.chat(ChatRequest(message="hi", user_id="intruder", session_id=r.session_id))


async def test_stream_persists_full_reply(brain: Brain, provider: MockProvider, store) -> None:
    provider.script("Streaming works, Sir.")
    chunks = [c async for c in brain.chat_stream(ChatRequest(message="stream?"))]
    assert "".join(chunks).strip() == "Streaming works, Sir."
    sessions = await store.list_for_user("owner")
    session = await store.get(sessions[0].id)
    assert session is not None and session.turns[-1].content == "Streaming works, Sir."
