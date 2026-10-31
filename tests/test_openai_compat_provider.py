# tests/test_openai_compat_provider.py — OpenAI-compatible provider (Groq/OpenRouter/Ollama/…)
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from jarvis.llm.base import (
    ChatMessage,
    LLMAuthError,
    LLMError,
    LLMTransientError,
    Role,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
)
from jarvis.llm.openai_compat_provider import OpenAICompatProvider

KEY = "gsk-test-key"
BASE = "https://api.example.com/openai/v1"
MSGS = [ChatMessage(role=Role.USER, content="hello")]


def _ok(content: str | None = "At your service, Sir.", **extra: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    msg.update(extra.pop("message", {}))
    body: dict[str, Any] = {
        "id": "chatcmpl-1",
        "model": "llama-3.3-70b",
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }
    body.update(extra)
    return body


def _provider(
    handler: Callable[[httpx.Request], httpx.Response], key: str | None = KEY
) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        BASE, api_key=key, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_request_shape_and_response_mapping() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_ok())

    spec = ToolSpec(name="get_calendar", description="d", input_schema={"type": "object"})
    c = await _provider(handler).complete(
        system="PERSONA",
        system_dynamic="Local time: now",
        messages=MSGS,
        model="llama-3.3-70b",
        max_tokens=256,
        tools=[spec],
    )
    assert seen["url"] == BASE + "/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}"
    body = seen["body"]
    assert body["model"] == "llama-3.3-70b" and body["max_tokens"] == 256
    assert body["messages"][0] == {"role": "system", "content": "PERSONA\n\nLocal time: now"}
    assert body["messages"][1] == {"role": "user", "content": "hello"}
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_calendar",
                "description": "d",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert c.text == "At your service, Sir." and c.provider == "openai_compat"
    assert c.usage.input_tokens == 12 and c.usage.output_tokens == 8
    assert c.stop_reason == "end_turn" and c.tool_calls == []


async def test_no_key_means_no_auth_header_and_no_tools_field_without_tools() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_ok())

    await _provider(handler, key=None).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    assert seen["auth"] is None  # Ollama / LM Studio: no key
    assert "tools" not in seen["body"]


async def test_tool_calls_are_parsed_and_history_blocks_are_mapped() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json=_ok(
                None,
                message={
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_calendar", "arguments": '{"day":"today"}'},
                        }
                    ]
                },
                choices=[
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_calendar",
                                        "arguments": '{"day":"today"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            ),
        )

    history = [
        ChatMessage(role=Role.USER, content="what's on?"),
        ChatMessage(
            role=Role.ASSISTANT,
            content=[
                TextBlock(text="checking"),
                ToolCall(id="t1", name="list_tasks", arguments={}),
            ],
        ),
        ChatMessage(role=Role.USER, content=[ToolResultBlock(tool_use_id="t1", content="[]")]),
    ]
    c = await _provider(handler).complete(system="s", messages=history, model="m", max_tokens=5)
    msgs = seen["body"]["messages"]
    assert msgs[2]["role"] == "assistant" and msgs[2]["content"] == "checking"
    assert msgs[2]["tool_calls"][0]["function"] == {"name": "list_tasks", "arguments": "{}"}
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": "[]"}

    assert c.stop_reason == "tool_use"
    assert c.tool_calls == [ToolCall(id="call_1", name="get_calendar", arguments={"day": "today"})]


async def test_malformed_tool_arguments_become_empty_dict_not_crash() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_ok(
                None,
                choices=[
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c",
                                    "type": "function",
                                    "function": {"name": "x", "arguments": "not json"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            ),
        )

    c = await _provider(handler).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    assert c.tool_calls[0].arguments == {}


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, LLMAuthError),
        (403, LLMAuthError),
        (429, LLMTransientError),
        (503, LLMTransientError),
        (400, LLMError),
    ],
)
async def test_http_errors_are_translated_and_key_redacted(
    status: int, exc: type[Exception]
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"boom {KEY}"}})

    with pytest.raises(exc) as ei:
        await _provider(handler).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    assert KEY not in str(ei.value)


async def test_timeout_and_empty_choices() -> None:
    def slow(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMTransientError):
        await _provider(slow).complete(system="s", messages=MSGS, model="m", max_tokens=5)

    def empty(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(LLMError, match="no answer"):
        await _provider(empty).complete(system="s", messages=MSGS, model="m", max_tokens=5)


async def test_stream_yields_deltas_until_done() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert json.loads(req.content)["stream"] is True
        chunks = [
            {"choices": [{"delta": {"role": "assistant", "content": "At your "}}]},
            {"choices": [{"delta": {"content": "service."}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    out = [
        d
        async for d in _provider(handler).stream(system="s", messages=MSGS, model="m", max_tokens=5)
    ]
    assert "".join(out) == "At your service."


async def test_non_json_200_is_an_llm_error_not_a_crash() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy page</html>")

    with pytest.raises(LLMError, match="non-JSON"):
        await _provider(handler).complete(system="s", messages=MSGS, model="m", max_tokens=5)
