# tests/test_llm_unreachable.py -- R1 C (D12): which cloud failures mean "unreachable" (the fallback
# brain may answer) and which must never fall back. Network error, timeout and HTTP 5xx (incl. 529
# overloaded) -> LLMUnreachable; 429, other 4xx and auth stay what they were.
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anthropic
import httpx
import httpx2
import pytest

from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import (
    ChatMessage,
    LLMAuthError,
    LLMError,
    LLMTransientError,
    LLMUnreachable,
    Role,
)
from jarvis.llm.gemini_provider import GeminiProvider
from jarvis.llm.openai_compat_provider import OpenAICompatProvider

MSGS = [ChatMessage(role=Role.USER, content="hi")]
KW: dict[str, Any] = {"system": "s", "messages": MSGS, "model": "m", "max_tokens": 5}

# status -> expected class (LLMUnreachable subclasses LLMTransientError, so a 429 is checked as NOT
# unreachable)
STATUSES = [
    (500, LLMUnreachable),
    (502, LLMUnreachable),
    (503, LLMUnreachable),
    (529, LLMUnreachable),
    (429, LLMTransientError),
    (400, LLMError),
    (401, LLMAuthError),
    (403, LLMAuthError),
]


def _check(exc: BaseException, want: type[Exception]) -> None:
    assert isinstance(exc, want)
    if want is LLMTransientError:
        assert not isinstance(exc, LLMUnreachable)
    if want is LLMError:
        assert not isinstance(exc, LLMTransientError)


def _openai(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatProvider:
    c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatProvider("https://x.test/v1", api_key="k", client=c)


def _gemini(handler: Callable[[httpx.Request], httpx.Response]) -> GeminiProvider:
    c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiProvider("gk", client=c)


def _anthropic(handler: Callable[[httpx2.Request], httpx2.Response]) -> AnthropicProvider:
    p = AnthropicProvider("sk-test", timeout_s=5, max_retries=0)
    p._client = anthropic.AsyncAnthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return p


@pytest.mark.parametrize(("status", "want"), STATUSES)
async def test_openai_compat_status_classes(status: int, want: type[Exception]) -> None:
    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    with pytest.raises(want) as ei:
        await _openai(h).complete(**KW)
    _check(ei.value, want)


@pytest.mark.parametrize(("status", "want"), STATUSES)
async def test_gemini_status_classes(status: int, want: type[Exception]) -> None:
    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    with pytest.raises(want) as ei:
        await _gemini(h).complete(**KW)
    _check(ei.value, want)


@pytest.mark.parametrize(("status", "want"), STATUSES)
async def test_anthropic_status_classes(status: int, want: type[Exception]) -> None:
    def h(_: httpx2.Request) -> httpx2.Response:
        err = {"type": "api_error", "message": "boom"}
        return httpx2.Response(status, json={"type": "error", "error": err})

    with pytest.raises(want) as ei:
        await _anthropic(h).complete(**KW)
    _check(ei.value, want)


@pytest.mark.parametrize("make", [_openai, _gemini])
@pytest.mark.parametrize(
    "boom", [httpx.ConnectError("no route"), httpx.ReadTimeout("slow"), httpx.ConnectTimeout("t")]
)
async def test_transport_errors_are_unreachable(
    make: Callable[[Any], Any], boom: Exception
) -> None:
    def h(_: httpx.Request) -> httpx.Response:
        raise boom

    with pytest.raises(LLMUnreachable):
        await make(h).complete(**KW)


async def test_anthropic_connection_error_and_timeout_are_unreachable() -> None:
    def refused(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route")

    def slow(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow")

    for h in (refused, slow):
        with pytest.raises(LLMUnreachable):
            await _anthropic(h).complete(**KW)


@pytest.mark.parametrize("make", [_openai, _gemini])
async def test_streams_classify_the_same_way(make: Callable[[Any], Any]) -> None:
    def down(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "x"}})

    def limited(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "x"}})

    with pytest.raises(LLMUnreachable):
        async for _ in make(down).stream(**KW):
            pass
    with pytest.raises(LLMTransientError) as ei:
        async for _ in make(limited).stream(**KW):
            pass
    assert not isinstance(ei.value, LLMUnreachable)


async def test_408_is_transient_but_not_unreachable() -> None:
    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(408, json={"error": {"message": "x"}})

    with pytest.raises(LLMTransientError) as ei:
        await _openai(h).complete(**KW)
    assert not isinstance(ei.value, LLMUnreachable)
