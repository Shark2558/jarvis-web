# tests/test_gemini_provider.py — Gemini REST provider against a fake HTTP transport (no network)
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import LLMBackend, Settings
from jarvis.llm.base import (
    ChatMessage,
    Effort,
    LLMAuthError,
    LLMError,
    LLMTransientError,
    Role,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
)
from jarvis.llm.gemini_provider import GeminiProvider
from jarvis.llm.router import ModelRouter, ModelTier, build_provider
from jarvis.memory.inmemory import InMemorySessionStore

KEY = "AIza-test-key"


def _ok(text: str = "At your service, Sir.", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {
            "promptTokenCount": 11,
            "candidatesTokenCount": 7,
            "thoughtsTokenCount": 30,
            "totalTokenCount": 48,
        },
        "modelVersion": "gemini-3.8-flash",
    }
    body.update(extra)
    return body


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> GeminiProvider:
    return GeminiProvider(KEY, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


MSGS = [ChatMessage(role=Role.USER, content="hello")]


async def test_request_shape_and_response_mapping() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["key_header"] = req.headers.get("x-goog-api-key")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_ok())

    c = await _provider(handler).complete(
        system="PERSONA",
        system_dynamic="Local time: now",
        messages=[
            ChatMessage(role=Role.USER, content="a"),
            ChatMessage(role=Role.USER, content="b"),  # same role twice → merged
            ChatMessage(role=Role.ASSISTANT, content="ok"),
            ChatMessage(role=Role.USER, content="hello"),
        ],
        model="gemini-3.8-flash",
        max_tokens=256,
        effort=Effort.LOW,
    )
    assert seen["url"].endswith("/v1beta/models/gemini-3.8-flash:generateContent")
    assert "key=" not in seen["url"]  # the key never travels in the URL
    assert seen["key_header"] == KEY
    body = seen["body"]
    assert body["systemInstruction"]["parts"] == [{"text": "PERSONA"}, {"text": "Local time: now"}]
    assert [m["role"] for m in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][0]["parts"] == [{"text": "a"}, {"text": "b"}]
    gc = body["generationConfig"]
    assert gc["maxOutputTokens"] >= 2048  # padded: thinking shares the budget
    assert gc["thinkingConfig"] == {"thinkingLevel": "low"}
    assert "tools" not in body

    assert c.text == "At your service, Sir."
    assert c.provider == "gemini" and c.tool_calls == []
    assert c.usage.input_tokens == 11 and c.usage.output_tokens == 37  # candidates + thoughts
    assert c.stop_reason == "end_turn" and c.cost_usd == 0.0


async def test_thought_parts_are_not_shown_and_max_tokens_maps() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        body = _ok()
        body["candidates"][0]["content"]["parts"] = [
            {"text": "internal reasoning", "thought": True},
            {"text": "Visible answer."},
        ]
        body["candidates"][0]["finishReason"] = "MAX_TOKENS"
        return httpx.Response(200, json=body)

    c = await _provider(handler).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    assert c.text == "Visible answer." and c.stop_reason == "max_tokens"


async def test_tools_are_dropped_and_tool_blocks_flattened_to_text() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return httpx.Response(200, json=_ok())

    spec = ToolSpec(name="get_calendar", description="d", input_schema={"type": "object"})
    msgs = [
        ChatMessage(role=Role.USER, content="what's on?"),
        ChatMessage(
            role=Role.ASSISTANT,
            content=[
                TextBlock(text="checking"),
                ToolCall(id="t1", name="get_calendar", arguments={}),
            ],
        ),
        ChatMessage(role=Role.USER, content=[ToolResultBlock(tool_use_id="t1", content="[]")]),
    ]
    await _provider(handler).complete(
        system="s", messages=msgs, model="m", max_tokens=5, tools=[spec]
    )
    assert "tools" not in seen
    flat = json.dumps(seen["contents"])
    assert "functionCall" not in flat and "functionResponse" not in flat
    assert "get_calendar" in flat  # history stays readable as plain text


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, LLMAuthError),
        (403, LLMAuthError),
        (429, LLMTransientError),
        (503, LLMTransientError),
        (500, LLMTransientError),
        (400, LLMError),
    ],
)
async def test_http_errors_are_translated(status: int, exc: type[Exception]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"boom {KEY}"}})

    with pytest.raises(exc) as ei:
        await _provider(handler).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    assert KEY not in str(ei.value)  # never echo the credential back


async def test_timeout_is_transient() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMTransientError):
        await _provider(handler).complete(system="s", messages=MSGS, model="m", max_tokens=5)


async def test_blocked_prompt_raises_clear_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    with pytest.raises(LLMError, match="blocked"):
        await _provider(handler).complete(system="s", messages=MSGS, model="m", max_tokens=5)


async def test_retries_once_without_thinking_config_on_400() -> None:
    calls: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body)
        if "thinkingConfig" in body.get("generationConfig", {}):
            msg = "Unknown name thinkingLevel at generation_config.thinking_config"
            return httpx.Response(400, json={"error": {"message": msg}})
        return httpx.Response(200, json=_ok("recovered"))

    c = await _provider(handler).complete(
        system="s", messages=MSGS, model="m", max_tokens=5, effort=Effort.LOW
    )
    assert c.text == "recovered" and len(calls) == 2


async def test_stream_yields_text_deltas() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith(":streamGenerateContent")
        assert req.url.params.get("alt") == "sse"
        chunks = [
            {"candidates": [{"content": {"parts": [{"text": "At your "}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "service."}]}}]},
        ]
        sse = "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks)
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    out = [
        d
        async for d in _provider(handler).stream(system="s", messages=MSGS, model="m", max_tokens=5)
    ]
    assert "".join(out) == "At your service."


# ---- config / router / console --------------------------------------------------------------


def _gemini_settings(**kw: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.GEMINI,
        gemini_api_key=SecretStr(KEY),
        **kw,
    )


def test_router_uses_gemini_models_and_provider() -> None:
    s = _gemini_settings()
    r = ModelRouter.from_settings(s)
    assert r.provider.name == "gemini"
    assert r.resolve(ModelTier.FAST) == "gemini-3.5-flash-lite"
    assert r.resolve(ModelTier.BALANCED) == "gemini-3.8-flash"
    assert r.resolve(ModelTier.STRONG) == "gemini-3.8-flash"


def test_gemini_backend_requires_key_in_prod() -> None:
    s = Settings(
        _env_file=None, env="prod", api_token=SecretStr("t"), llm_backend=LLMBackend.GEMINI
    )  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        s.require_prod_invariants()
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        build_provider(s)


async def test_console_config_warns_when_free_tier_trains_on_content() -> None:
    from jarvis.llm.mock_provider import MockProvider

    async def cfg(s: Settings) -> dict[str, str]:
        app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                return (await c.get("/console/config")).json()

    free = await cfg(_gemini_settings())
    assert "improve" in free["privacy_warning"].lower() and free["brain"] == "gemini"
    paid = await cfg(_gemini_settings(gemini_paid_tier=True))
    assert paid["privacy_warning"] == ""
    claude = await cfg(Settings(_env_file=None, env="dev", llm_backend=LLMBackend.MOCK))  # type: ignore[call-arg]
    assert claude["privacy_warning"] == ""


# ---- friendly LLM errors --------------------------------------------------------------------


async def test_llm_errors_are_friendly_and_do_not_leak_vendor_text(
    client: AsyncClient, provider: Any
) -> None:
    from jarvis.llm.base import LLMError as E

    async def boom(**_: Any) -> Any:
        raise E(
            "Error code: 400 - {'type': 'invalid_request_error', "
            "'message': 'Your credit balance is too low'}"
        )

    provider.complete = boom  # type: ignore[method-assign]
    r = await client.post("/v1/chat", json={"message": "hi"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "credit" in detail.lower() and "invalid_request_error" not in detail
