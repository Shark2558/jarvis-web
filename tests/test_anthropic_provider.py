# tests/test_anthropic_provider.py
"""Exercises the real SDK code path against a fake HTTP transport — no network, no key."""

from __future__ import annotations

import json

import anthropic
import httpx2 as httpx
import pytest

from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import (
    ChatMessage,
    Effort,
    LLMAuthError,
    LLMTransientError,
    Role,
    StreamUsage,
)


def _message_json(text: str = "At your service, Sir.") -> dict:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 120,
            "output_tokens": 9,
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 0,
        },
    }


def _provider(handler) -> AnthropicProvider:  # type: ignore[no-untyped-def]
    p = AnthropicProvider("sk-test", timeout_s=5, max_retries=0)
    p._client = anthropic.AsyncAnthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return p


async def test_request_shape_and_response_mapping() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content))
        return httpx.Response(200, json=_message_json())

    c = await _provider(handler).complete(
        system="PERSONA",
        system_dynamic="Local time: now",
        messages=[ChatMessage(role=Role.USER, content="hello")],
        model="claude-sonnet-5-5",
        max_tokens=256,
        effort=Effort.LOW,
    )

    # request: cached persona block, uncached dynamic block, effort via output_config
    assert captured["model"] == "claude-sonnet-5-5"
    assert captured["max_tokens"] == 256
    assert captured["system"][0] == {
        "type": "text",
        "text": "PERSONA",
        "cache_control": {"type": "ephemeral"},
    }
    assert captured["system"][1] == {"type": "text", "text": "Local time: now"}
    assert captured["output_config"] == {"effort": "low"}
    assert captured["messages"] == [{"role": "user", "content": "hello"}]
    assert "temperature" not in captured

    # response: text, usage incl. cache, cost from the price table
    assert c.text == "At your service, Sir."
    assert c.usage.input_tokens == 120 and c.usage.cache_read_tokens == 100
    assert c.provider == "anthropic" and c.stop_reason == "end_turn"
    expected_cost = (120 * 2.0 + 9 * 10.0 + 100 * 0.10) / 1_000_000
    assert c.cost_usd == pytest.approx(expected_cost, rel=1e-6)


async def test_error_translation() -> None:
    def rate_limited(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"type": "rate_limit_error", "message": "slow"}})

    def unauthorized(_: httpx.Request) -> httpx.Response:
        err = {"type": "authentication_error", "message": "no"}
        return httpx.Response(401, json={"error": err})

    msgs = [ChatMessage(role=Role.USER, content="x")]
    with pytest.raises(LLMTransientError):
        await _provider(rate_limited).complete(system="s", messages=msgs, model="m", max_tokens=5)
    with pytest.raises(LLMAuthError):
        await _provider(unauthorized).complete(system="s", messages=msgs, model="m", max_tokens=5)


async def test_tools_and_tool_results_on_the_wire() -> None:
    from jarvis.llm.base import ToolCall, ToolResultBlock, ToolSpec

    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content))
        body = _message_json()
        body["content"] = [
            {"type": "tool_use", "id": "tu_1", "name": "get_calendar", "input": {"day": "today"}}
        ]
        body["stop_reason"] = "tool_use"
        return httpx.Response(200, json=body)

    spec = ToolSpec(
        name="get_calendar", description="d", input_schema={"type": "object", "properties": {}}
    )
    msgs = [
        ChatMessage(role=Role.USER, content="hi"),
        ChatMessage(
            role=Role.ASSISTANT, content=[ToolCall(id="tu_0", name="list_tasks", arguments={})]
        ),
        ChatMessage(role=Role.USER, content=[ToolResultBlock(tool_use_id="tu_0", content="[]")]),
    ]
    c = await _provider(handler).complete(
        system="s", messages=msgs, model="m", max_tokens=5, tools=[spec]
    )
    assert captured["tools"] == [
        {
            "name": "get_calendar",
            "description": "d",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    assert captured["messages"][1]["content"][0]["type"] == "tool_use"
    assert captured["messages"][2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "tu_0",
        "content": "[]",
        "is_error": False,
    }
    assert c.tool_calls == [ToolCall(id="tu_1", name="get_calendar", arguments={"day": "today"})]
    assert c.stop_reason == "tool_use"


# ---- streaming (slice 10 A2): text deltas out, the vendor's usage into the caller's sink ---------
def _sse(*events: dict) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


_START = {
    "type": "message_start",
    "message": {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 120,
            "output_tokens": 1,
            "cache_read_input_tokens": 900,
            "cache_creation_input_tokens": 30,
        },
    },
}
_BLOCK = {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
_END = (
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 9},
    },
    {"type": "message_stop"},
)
MSGS = [ChatMessage(role=Role.USER, content="hello")]


def _delta(text: str) -> dict:
    delta = {"type": "text_delta", "text": text}
    return {"type": "content_block_delta", "index": 0, "delta": delta}


def _streaming(body: bytes) -> AnthropicProvider:
    def handler(req: httpx.Request) -> httpx.Response:
        assert json.loads(req.content)["stream"] is True
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    return _provider(handler)


async def test_stream_yields_text_and_reports_exact_usage() -> None:
    sink = StreamUsage()
    p = _streaming(_sse(_START, _BLOCK, _delta("At your "), _delta("service, Sir."), *_END))
    got = [
        d
        async for d in p.stream(
            system="s", messages=MSGS, model="claude-sonnet-5-5", max_tokens=5, usage=sink
        )
    ]
    assert "".join(got) == "At your service, Sir."
    assert (sink.input_tokens, sink.output_tokens) == (120, 9)
    assert (sink.cache_read_tokens, sink.cache_write_tokens) == (900, 30)
    assert sink.final is True


async def test_stream_cut_short_keeps_the_opening_usage() -> None:
    sink = StreamUsage()
    p = _streaming(_sse(_START, _BLOCK, _delta("At your "), _delta("service"), *_END))
    gen = p.stream(system="s", messages=MSGS, model="claude-sonnet-5-5", max_tokens=5, usage=sink)
    assert await gen.__anext__() == "At your "
    await gen.aclose()  # the owner went away: the closing count never arrives
    assert sink.input_tokens == 120 and sink.cache_read_tokens == 900
    assert sink.final is False


async def test_stream_without_a_sink_still_streams() -> None:
    p = _streaming(_sse(_START, _BLOCK, _delta("ok"), *_END))
    got = [d async for d in p.stream(system="s", messages=MSGS, model="m", max_tokens=5)]
    assert got == ["ok"]
