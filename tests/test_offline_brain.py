# tests/test_offline_brain.py -- R1 C end to end through the Brain: the cloud is unreachable, the
# laptop answers, the reply says so, writes become cards, nothing falls back on 429 / auth, the
# stream switches only before its first text, and the owner never sees vendor text.
from __future__ import annotations

import json
from typing import Any

import pytest
from offline_fakes import Rig

from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core import channel
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.llm.base import (
    Completion,
    LLMAuthError,
    LLMTransientError,
    LLMUnreachable,
    ToolCall,
    Usage,
)
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.fallback import FallbackFailed
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.rules import OfflineRules
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry

TIERS = {ModelTier.FAST: "c-fast", ModelTier.BALANCED: "c-bal", ModelTier.STRONG: "c-strong"}
SECRET_VENDOR_TEXT = "vendor says: internal server error id 8f3a"


class Cloud:
    """The cloud brain: raises `error` while set, otherwise answers (or asks for a tool)."""

    name = "cloud"

    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls = 0
        self.tool_once: ToolCall | None = None
        self.stream_error_after: int | None = None

    async def complete(self, **kw: Any) -> Completion:
        self.calls += 1
        if self.error:
            raise self.error
        calls: list[ToolCall] = []
        text = "from the cloud"
        if self.tool_once is not None and kw.get("tools"):
            calls, self.tool_once, text = [self.tool_once], None, ""
        return Completion(
            text=text,
            tool_calls=calls,
            model=kw["model"],
            provider="cloud",
            usage=Usage(input_tokens=1000, output_tokens=1000),
            latency_ms=1,
            cost_usd=0.5,
        )

    async def stream(self, **kw: Any):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.error and self.stream_error_after is None:
            raise self.error
        yield "cloud "
        if self.error:
            raise self.error
        yield "words "


class World:
    def __init__(self) -> None:
        self.reminders: list[dict[str, Any]] = []


def _gateway(world: World, rig: Rig) -> Gateway:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        world.reminders.append(args)
        return {"created": True}

    reg = ToolRegistry()
    reg.register(
        Tool(
            "reminder_add",
            "Add a reminder",
            {"type": "object", "properties": {"text": {"type": "string"}}},
            ActionRisk.REVERSIBLE,
            run,
            summarize=lambda a: f"Reminder: {a.get('text', '')}",
        )
    )

    class NoRules:
        async def rules_for(self, user_id: str) -> list[Any]:
            return []

    return Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(),
        audit=AuditLog(),
        rules=OfflineRules(NoRules()),
    )


async def _brain(rig: Rig, cloud: Cloud, world: World) -> Brain:
    s = Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )
    spec = BrainSpec(id="mock", label="Claude", provider=cloud, tiers=TIERS)
    brains = BrainRegistry([spec], default_id="mock", fallback=rig.svc)
    return Brain(
        store=InMemorySessionStore(ttl_s=3600),
        settings=s,
        brains=brains,
        gateway=_gateway(world, rig),
    )


@pytest.fixture
async def rig() -> Rig:
    return await Rig().ready()


async def test_cloud_unreachable_the_laptop_answers_and_the_reply_says_so(rig: Rig) -> None:
    cloud, world = Cloud(), World()
    cloud.error = LLMUnreachable(SECRET_VENDOR_TEXT)
    rig.laptop.reply = rig.laptop.completion("Two meetings today, Sir.")
    resp = await (await _brain(rig, cloud, world)).chat(ChatRequest(message="what's on today?"))
    assert resp.offline is True and resp.reply == "Two meetings today, Sir."
    assert resp.cost_usd == 0.0 and resp.cost_inr == 0.0
    assert resp.model == "qwen2.5:7b"
    assert SECRET_VENDOR_TEXT not in resp.model_dump_json()


async def test_a_normal_reply_is_not_marked_offline(rig: Rig) -> None:
    resp = await (await _brain(rig, Cloud(), World())).chat(ChatRequest(message="hi"))
    assert resp.offline is False and resp.reply == "from the cloud"
    assert rig.laptop.requests == []


async def test_a_new_turn_after_an_offline_one_is_not_marked(rig: Rig) -> None:
    cloud = Cloud()
    brain = await _brain(rig, cloud, World())
    cloud.error = LLMUnreachable("x")
    first = await brain.chat(ChatRequest(message="one"))
    cloud.error = None
    # right after a miss the breaker keeps the next two minutes on the laptop (see the breaker
    # tests); here we want the cloud again, so close it
    brain.brains.router_for("mock")._breaker.reset()
    second = await brain.chat(ChatRequest(message="two", session_id=first.session_id))
    assert first.offline is True and second.offline is False


async def test_a_write_in_an_offline_turn_is_a_card_not_an_action(rig: Rig) -> None:
    cloud, world = Cloud(), World()
    cloud.error = LLMUnreachable("x")
    call = {
        "id": "t1",
        "type": "function",
        "function": {"name": "reminder_add", "arguments": json.dumps({"text": "call mum"})},
    }
    rig.laptop.queue = [rig.laptop.completion("", [call])]
    brain = await _brain(rig, cloud, world)
    resp = await brain.chat(ChatRequest(message="remind me to call mum"))
    assert resp.offline is True
    assert world.reminders == []  # nothing ran
    assert len(resp.pending_approvals) == 1
    assert "call mum" in resp.pending_approvals[0].summary


async def test_the_same_write_runs_when_the_cloud_answers(rig: Rig) -> None:
    cloud, world = Cloud(), World()
    cloud.tool_once = ToolCall(id="t1", name="reminder_add", arguments={"text": "call mum"})
    resp = await (await _brain(rig, cloud, world)).chat(ChatRequest(message="remind me"))
    assert world.reminders == [{"text": "call mum"}] and resp.pending_approvals == []


async def test_the_laptop_is_offered_only_the_offline_tools(rig: Rig) -> None:
    cloud, world = Cloud(), World()
    cloud.error = LLMUnreachable("x")
    await (await _brain(rig, cloud, world)).chat(ChatRequest(message="hi"))
    sent = rig.laptop.chats()[0]
    assert [t["function"]["name"] for t in sent["tools"]] == ["reminder_add"]


@pytest.mark.parametrize("err", [LLMTransientError("429"), LLMAuthError("401")])
async def test_429_and_auth_never_reach_the_laptop(rig: Rig, err: Exception) -> None:
    cloud = Cloud()
    cloud.error = err
    brain = await _brain(rig, cloud, World())
    with pytest.raises((LLMTransientError, LLMAuthError)):
        await brain.chat(ChatRequest(message="hi"))
    assert rig.laptop.requests == []


async def test_laptop_down_too_gives_the_friendly_error_without_vendor_text(rig: Rig) -> None:
    cloud = Cloud()
    cloud.error = LLMUnreachable(SECRET_VENDOR_TEXT)
    rig.laptop.up = False
    brain = await _brain(rig, cloud, World())
    with pytest.raises(FallbackFailed) as ei:
        await brain.chat(ChatRequest(message="hi"))
    assert str(ei.value) == "Claude can't be reached and your laptop didn't answer."
    assert SECRET_VENDOR_TEXT not in str(ei.value)


async def test_offline_off_in_the_settings_means_the_original_error(rig: Rig) -> None:
    await rig.svc.configure("u", enabled=False)
    cloud = Cloud()
    cloud.error = LLMUnreachable("x")
    brain = await _brain(rig, cloud, World())
    with pytest.raises(LLMUnreachable) as ei:
        await brain.chat(ChatRequest(message="hi"))
    assert not isinstance(ei.value, FallbackFailed) and rig.laptop.requests == []


async def test_the_stream_falls_back_before_its_first_text_and_is_marked(rig: Rig) -> None:
    cloud = Cloud()
    cloud.error = LLMUnreachable("x")
    brain = await _brain(rig, cloud, World())
    from jarvis.core.brain import StreamMeta

    meta = StreamMeta()
    out = [d async for d in brain.chat_stream(ChatRequest(message="hi"), meta=meta)]
    assert "".join(out) == "lap top "
    assert channel.answered_offline() is True  # the stored turn carries the same flag


async def test_a_stream_cut_mid_way_is_never_switched(rig: Rig) -> None:
    cloud = Cloud()
    cloud.error = LLMUnreachable("dropped")
    cloud.stream_error_after = 1
    brain = await _brain(rig, cloud, World())
    got: list[str] = []
    with pytest.raises(LLMUnreachable):
        async for d in brain.chat_stream(ChatRequest(message="hi")):
            got.append(d)
    assert got == ["cloud "] and rig.laptop.requests == []
