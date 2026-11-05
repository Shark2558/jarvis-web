# tests/test_no_ai_runner.py
"""No-AI mode end to end with spies (R4 D-D4/D-D3, py-M8..M10): no spend, no recall, no fallback,
pending approvals visible (also when streaming), conflict-safe storage, fixed error lines."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.config import Settings
from jarvis.core.brain import Brain, StreamMeta
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.llm.base import ChatMessage, Role
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import BrainOff, ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.no_ai import DENIED, NEEDS_OK, UNAVAILABLE
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.base import Tool
from tests.conftest import TIERS


class BillingSpy:
    def __init__(self) -> None:
        self.records: list[tuple[Any, ...]] = []
        self.checks = 0

    async def ensure_allowed(self, *a: Any) -> None:
        self.checks += 1

    async def record(self, *a: Any) -> float:
        self.records.append(a)
        return 0.0

    async def inr(self, usd: float) -> float:
        return 0.0


class MemorySpy:
    def __init__(self) -> None:
        self.recalls = 0
        self.after = 0

    async def recall(self, *a: Any, **k: Any) -> Any:
        self.recalls += 1
        raise AssertionError("recall must not run in no-AI mode")

    def after_turn(self, *a: Any, **k: Any) -> None:
        self.after += 1


class FallbackSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def ready(self) -> bool:
        self.calls += 1
        return True

    async def complete(self, **k: Any) -> Any:
        self.calls += 1
        raise AssertionError("the laptop fallback must not run for BrainOff")


def tool(name: str, result: Any, risk: ActionRisk = ActionRisk.READ_ONLY, boom: str = "") -> Tool:
    async def run(_a: dict[str, Any]) -> Any:
        if boom:
            raise RuntimeError(boom)
        return result

    return Tool(name, f"fake {name}", {"type": "object", "properties": {}}, risk, run)


def build(
    settings: Settings, store: InMemorySessionStore, tools: list[Tool], **extra: Any
) -> tuple[Brain, MockProvider]:
    provider = MockProvider()
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    s = settings.model_copy(update={"brain_mode": "none", "user_timezone": "Asia/Kolkata"})
    router = extra.pop("router", None) or ModelRouter(provider, TIERS)
    return Brain(router=router, store=store, settings=s, gateway=gw, **extra), provider


async def test_no_billing_record_and_no_budget_check_in_no_ai_mode(
    settings: Settings, store: InMemorySessionStore
) -> None:
    spy = BillingSpy()
    brain, _ = build(settings, store, [tool("systems_check", {"spoken": "ok"})], billing=spy)

    await brain.chat(ChatRequest(message="systems check"))
    _ = [d async for d in brain.chat_stream(ChatRequest(message="systems check"))]

    assert spy.records == [] and spy.checks == 0


async def test_no_memory_recall_or_learning_in_no_ai_mode(
    settings: Settings, store: InMemorySessionStore
) -> None:
    mem = MemorySpy()
    brain, _ = build(settings, store, [tool("systems_check", {"spoken": "ok"})], memory=mem)

    await brain.chat(ChatRequest(message="systems check"))

    assert mem.recalls == 0 and mem.after == 0


async def test_brain_off_does_not_trigger_the_laptop_fallback(
    settings: Settings, store: InMemorySessionStore
) -> None:
    fb = FallbackSpy()
    provider = MockProvider()
    brain, _ = build(
        settings,
        store,
        [],
        router=ModelRouter(provider, TIERS, fallback=fb),  # type: ignore[arg-type]
    )

    with pytest.raises(BrainOff):
        await brain.router.complete(
            tier=ModelTier.FAST,
            system="s",
            messages=[ChatMessage(role=Role.USER, content="x")],
            max_tokens=5,
        )

    assert fb.calls == 0 and provider.calls == []


async def test_a_pending_approval_is_returned_in_no_ai_mode(
    settings: Settings, store: InMemorySessionStore
) -> None:
    brain, provider = build(
        settings, store, [tool("reminder_add", {"status": "set"}, ActionRisk.IRREVERSIBLE)]
    )

    resp = await brain.chat(ChatRequest(message="set a timer for 10 minutes"))

    assert resp.reply == NEEDS_OK
    assert len(resp.pending_approvals) == 1 and provider.calls == []


async def test_a_pending_approval_is_returned_when_streaming_too(
    settings: Settings, store: InMemorySessionStore
) -> None:
    brain, _ = build(
        settings, store, [tool("reminder_add", {"status": "set"}, ActionRisk.IRREVERSIBLE)]
    )
    meta = StreamMeta()

    chunks = [
        d async for d in brain.chat_stream(ChatRequest(message="timer 10 minutes"), meta=meta)
    ]

    assert "".join(chunks) == NEEDS_OK
    assert len(meta.pending) == 1


async def test_tool_error_text_is_never_echoed_to_the_owner(
    settings: Settings, store: InMemorySessionStore
) -> None:
    secret = "postgres://user:hunter2@10.0.0.5/db exploded"
    brain, _ = build(settings, store, [tool("systems_check", None, boom=secret)])

    resp = await brain.chat(ChatRequest(message="systems check"))

    assert "hunter2" not in resp.reply and resp.reply == UNAVAILABLE


async def test_a_write_in_no_ai_mode_is_recorded_conflict_safe(
    settings: Settings, store: InMemorySessionStore
) -> None:
    brain, _ = build(
        settings, store, [tool("reminder_add", {"message": "Reminder set."}, ActionRisk.REVERSIBLE)]
    )

    resp = await brain.chat(ChatRequest(message="set a timer for 10 minutes"))

    session = await store.get(resp.session_id)
    assert session is not None and [t.role for t in session.turns] == [Role.USER, Role.ASSISTANT]
    assert resp.reply == "Reminder set."


def test_denied_line_is_fixed_text() -> None:
    assert DENIED.endswith("Sir.")
