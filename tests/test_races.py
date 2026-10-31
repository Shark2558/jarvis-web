# tests/test_races.py — slice 5 review fixes: concurrent owner actions on one conversation.
# SlowDocs adds a few ms to every database call so concurrent requests really interleave
# (an in-memory store without awaits would hide every race).
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pytest

from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.storage import doc_storage
from jarvis.storage.docs import Doc, DocTx, MemoryDocs, Op, Query, T
from jarvis.tools.builtin import InMemoryWorld, builtin_tools
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

DELAY_S = 0.004
TIERS = {t: f"mock-{t.value}" for t in ModelTier}


class SlowDocs(MemoryDocs):
    async def get(self, path: str) -> Doc | None:
        await asyncio.sleep(DELAY_S)
        return await super().get(path)

    async def query(self, q: Query) -> list[tuple[str, Doc]]:
        await asyncio.sleep(DELAY_S)
        return await super().query(q)

    async def write(self, ops: Sequence[Op]) -> None:
        await asyncio.sleep(DELAY_S)
        await super().write(ops)

    async def transaction(self, fn: Callable[[DocTx], Awaitable[T]]) -> T:
        await asyncio.sleep(DELAY_S)
        return await super().transaction(fn)


@pytest.fixture
def slow_brain(settings: Any, provider: MockProvider, world: InMemoryWorld) -> Brain:
    st = doc_storage(SlowDocs())
    reg = ToolRegistry()
    for t in builtin_tools(world):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(st.approvals), audit=st.audit)
    return Brain(
        router=ModelRouter(provider, TIERS), store=st.sessions, settings=settings, gateway=gw
    )


async def _propose(brain: Brain, provider: MockProvider) -> tuple[str, str]:
    provider.script_tool_calls(
        [ToolCall(id="s1", name="send_message", arguments={"to": "priya@x.com", "body": "3pm"})],
        "Awaiting your approval, Sir.",
    )
    r = await brain.chat(ChatRequest(message="tell priya 3pm"))
    return r.pending_approvals[0].id, r.session_id


async def _settle(*aws: Awaitable[Any]) -> list[Any]:
    return list(await asyncio.gather(*aws, return_exceptions=True))


async def test_double_approve_sends_once_and_never_resurrects(
    slow_brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    pid, sid = await _propose(slow_brain, provider)
    provider.script("Sent, Sir.")
    provider.script("Sent, Sir.")
    results = await _settle(
        slow_brain.approve(pid, session_id=sid), slow_brain.approve(pid, session_id=sid)
    )
    assert world.sent == [{"to": "priya@x.com", "body": "3pm"}]
    assert sum(isinstance(r, LookupError) for r in results) == 1
    assert await slow_brain.gateway.pending() == []  # type: ignore[union-attr]
    session = await slow_brain.store.get(sid)
    assert session is not None
    outcomes = [
        b
        for t in session.turns
        for b in t.blocks
        if getattr(b, "tool_use_id", None) == f"approve_{pid}"
    ]
    assert len(outcomes) == 1 and not outcomes[0].is_error  # the record of the send survives


async def test_approve_and_decline_race_has_one_outcome(
    slow_brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    pid, sid = await _propose(slow_brain, provider)
    provider.script("Sent.")
    provider.script("Understood, nothing sent.")
    results = await _settle(
        slow_brain.decline(pid, session_id=sid), slow_brain.approve(pid, session_id=sid)
    )
    assert sum(isinstance(r, LookupError) for r in results) == 1
    assert len(world.sent) <= 1
    assert await slow_brain.gateway.pending() == []  # type: ignore[union-attr]


async def test_concurrent_messages_in_one_conversation_are_all_kept(
    slow_brain: Brain, provider: MockProvider
) -> None:
    provider.script("first")
    sid = (await slow_brain.chat(ChatRequest(message="hello"))).session_id
    provider.script("a")
    provider.script("b")
    await _settle(
        slow_brain.chat(ChatRequest(message="one", session_id=sid)),
        slow_brain.chat(ChatRequest(message="two", session_id=sid)),
    )
    session = await slow_brain.store.get(sid)
    assert session is not None
    assert sorted(t.content for t in session.turns if t.role.value == "user") == [
        "hello",
        "one",
        "two",
    ]
    assert len(session.turns) == 6


async def test_forget_waits_for_a_running_reply_and_clears_its_approvals(
    slow_brain: Brain, provider: MockProvider
) -> None:
    pid, sid = await _propose(slow_brain, provider)
    provider.script("late reply")
    results = await _settle(
        slow_brain.chat(ChatRequest(message="still there?", session_id=sid)),
        slow_brain.forget(sid),
    )
    assert results[1] is True
    assert await slow_brain.store.get(sid) is None  # not resurrected by the in-flight reply
    assert await slow_brain.gateway.pending() == []  # type: ignore[union-attr]
    assert await slow_brain.forget(sid) is False


class FlakyAudit:
    """An audit trail whose writes fail AFTER a tool has run (e.g. Firestore hiccup)."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.fail_outcomes = inner, {"executed", "error"}

    async def append(self, **kw: Any) -> Any:
        if kw["outcome"] in self.fail_outcomes:
            raise RuntimeError("firestore unavailable")
        return await self.inner.append(**kw)

    async def tail(self, limit: int) -> Any:
        return await self.inner.tail(limit)

    async def verify_all(self) -> bool:
        return await self.inner.verify_all()


async def test_audit_failure_after_send_still_records_the_send(
    slow_brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    pid, sid = await _propose(slow_brain, provider)
    assert slow_brain.gateway is not None
    slow_brain.gateway.audit = FlakyAudit(slow_brain.gateway.audit)
    provider.script("Sent, Sir.")
    await slow_brain.approve(pid, session_id=sid)  # must not raise: the message already went
    assert len(world.sent) == 1
    session = await slow_brain.store.get(sid)
    assert session is not None
    done = [
        b
        for t in session.turns
        for b in t.blocks
        if getattr(b, "tool_use_id", "") == f"approve_{pid}"
    ]
    assert len(done) == 1 and not done[0].is_error


async def test_rejected_first_message_leaves_no_empty_conversation(slow_brain: Brain) -> None:
    from jarvis.core.guardrails import InputRejected

    with pytest.raises(InputRejected):
        await slow_brain.chat(ChatRequest(message="\x00\x01  "))
    assert await slow_brain.store.list_for_user("owner") == []
