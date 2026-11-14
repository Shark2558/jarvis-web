# tests/test_r14_c_cache.py -- R14 Part C, D9 "Cache within the reply" (A1 choice (b), plan
# docs/plans/r14-hardening.md): the Anthropic provider, built with `cache_history` from the
# settings, adds a second cache breakpoint on the last message block itself; off = one breakpoint
# (the system block's), as before R14. No brain slot and no hint in the shared interface. The
# stream path (one call a reply, never a second round) keeps the system breakpoint only.
from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2
from pydantic import SecretStr

from jarvis.config import LLMBackend, Settings
from jarvis.llm import factory
from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import (
    ChatMessage,
    LLMProvider,
    Role,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
)
from jarvis.llm.brains import BrainRegistry
from jarvis.llm.router import build_provider


def _message_json() -> dict[str, Any]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": "Done, Sir."}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }


def _provider(sent: list[dict[str, Any]], *, cache_history: bool) -> AnthropicProvider:
    def handler(req: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(req.content))
        if "stream" in sent[-1]:
            body = (
                'event: message_start\ndata: {"type":"message_start","message":{"id":"m",'
                '"type":"message","role":"assistant","model":"claude-sonnet-5-5","content":[],'
                '"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":1,'
                '"output_tokens":1}}}\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n'
            )
            return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=body)
        return httpx2.Response(200, json=_message_json())

    p = AnthropicProvider("sk-test", timeout_s=5, max_retries=0, cache_history=cache_history)
    p._client = anthropic.AsyncAnthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return p


def _marks(body: dict[str, Any]) -> list[str]:
    """Where the request's cache breakpoints sit: 'system:<i>' or 'message:<i>:<j>'."""
    out = [f"system:{i}" for i, b in enumerate(body["system"]) if "cache_control" in b]
    for i, m in enumerate(body["messages"]):
        if isinstance(m["content"], list):
            out += [f"message:{i}:{j}" for j, b in enumerate(m["content"]) if "cache_control" in b]
    return out


TOOL = ToolSpec(name="web_read", description="read a page", input_schema={"type": "object"})
ROUND = [
    ChatMessage(role=Role.USER, content="read example.com"),
    ChatMessage(role=Role.ASSISTANT, content=[ToolCall(id="c1", name="web_read", arguments={})]),
    ChatMessage(
        role=Role.USER,
        content=[ToolResultBlock(tool_use_id="c1", content="[untrusted tool output]\npage")],
    ),
]


async def test_the_hint_adds_one_breakpoint_on_the_last_message_block() -> None:
    sent: list[dict[str, Any]] = []
    await _provider(sent, cache_history=True).complete(
        system="PERSONA", system_dynamic="trailer", messages=ROUND, model="m", max_tokens=9,
        tools=[TOOL],
    )  # fmt: skip
    assert _marks(sent[0]) == ["system:0", "message:2:0"]
    assert sent[0]["messages"][2]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in sent[0]["system"][1]  # the trailer stays uncached


async def test_without_the_hint_there_is_one_breakpoint_as_before() -> None:
    sent: list[dict[str, Any]] = []
    await _provider(sent, cache_history=False).complete(
        system="PERSONA", messages=ROUND, model="m", max_tokens=9, tools=[TOOL]
    )
    assert _marks(sent[0]) == ["system:0"]


async def test_a_plain_last_message_becomes_one_marked_text_block() -> None:
    sent: list[dict[str, Any]] = []
    msgs = [ChatMessage(role=Role.USER, content="hello")]
    await _provider(sent, cache_history=True).complete(
        system="P", messages=msgs, model="m", max_tokens=9
    )
    last = sent[0]["messages"][-1]["content"]
    assert last == [{"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}]
    assert msgs[0].content == "hello"  # the caller's messages are never changed


async def test_the_mark_goes_on_the_last_non_empty_block() -> None:
    sent: list[dict[str, Any]] = []
    msgs = [ChatMessage(role=Role.USER, content=[TextBlock(text="look"), TextBlock(text="")])]
    await _provider(sent, cache_history=True).complete(
        system="P", messages=msgs, model="m", max_tokens=9
    )
    assert _marks(sent[0]) == ["system:0", "message:0:0"]
    sent.clear()
    empty = [ChatMessage(role=Role.USER, content=[TextBlock(text="")])]
    await _provider(sent, cache_history=True).complete(
        system="P", messages=empty, model="m", max_tokens=9
    )
    assert _marks(sent[0]) == ["system:0"]  # an empty text block can never carry one


async def test_the_stream_keeps_the_system_breakpoint_only() -> None:
    sent: list[dict[str, Any]] = []
    async for _ in _provider(sent, cache_history=True).stream(
        system="P", messages=[ChatMessage(role=Role.USER, content="hi")], model="m", max_tokens=9
    ):
        pass
    assert _marks(sent[0]) == ["system:0"]


async def test_a_second_round_keeps_the_first_rounds_prefix_byte_for_byte() -> None:
    sent: list[dict[str, Any]] = []
    p = _provider(sent, cache_history=True)
    first = ROUND[:1]
    await p.complete(system="P", messages=first, model="m", max_tokens=9, tools=[TOOL])
    await p.complete(system="P", messages=ROUND, model="m", max_tokens=9, tools=[TOOL])
    one, two = sent
    assert one["tools"] == two["tools"] and one["system"] == two["system"]
    unmarked = {k: v for k, v in one["messages"][0]["content"][0].items() if k != "cache_control"}
    assert two["messages"][0]["content"] == [unmarked]  # the same block, now before the mark


def _anthropic_settings(**kw: Any) -> Settings:
    return Settings(
        _env_file=None,
        llm_backend=LLMBackend.ANTHROPIC,
        anthropic_api_key=SecretStr("sk-ant-test"),
        **kw,
    )


def test_the_factory_builds_claude_with_the_setting() -> None:
    on, off = _anthropic_settings(), _anthropic_settings(cache_history=False)
    assert factory.anthropic_provider(on).cache_history is True
    assert factory.anthropic_provider(off).cache_history is False
    built = build_provider(off)
    assert isinstance(built, AnthropicProvider) and built.cache_history is False
    claude = BrainRegistry.from_settings(on).get("anthropic").provider
    assert isinstance(claude, AnthropicProvider) and claude.cache_history is True
    assert isinstance(claude, LLMProvider)


def test_the_shared_interface_has_no_cache_hint() -> None:
    import inspect

    from jarvis.llm import base, router

    assert "cache_hint" not in inspect.getsource(base)
    assert "cache_hint" not in inspect.getsource(router)
    assert "cache_history" not in inspect.signature(LLMProvider.complete).parameters
