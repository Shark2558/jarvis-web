# tests/test_r14_c_llm_errors.py -- R14 Part C, D9 "Vendor text out of errors" (plan
# docs/plans/r14-hardening.md, fact 13): all four error classes carry fixed words in all three
# providers, the vendor's message never reaches the error, its chain or a log line, and the
# router logs the class name, not str(exc). No network: every vendor answer is a MockTransport.
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import anthropic
import httpx
import httpx2  # the anthropic SDK's own HTTP package (tests/test_anthropic_provider.py)
import pytest

from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import (
    FIXED_ERROR_WORDS,
    ChatMessage,
    Completion,
    LLMAuthError,
    LLMError,
    LLMTransientError,
    LLMUnreachable,
    Role,
    Usage,
)
from jarvis.llm.gemini_provider import GeminiProvider
from jarvis.llm.local_provider import LocalBrainProvider
from jarvis.llm.openai_compat_provider import OpenAICompatProvider
from jarvis.llm.router import ModelRouter, ModelTier

VENDOR = "VENDOR-SECRET-TEXT sk-ant-should-never-leak"
KEY = "test-key-0123456789"
MSGS = [ChatMessage(role=Role.USER, content="hello")]
Handler = Callable[[httpx.Request], httpx.Response]


def _anthropic(handler: Callable[[httpx2.Request], httpx2.Response]) -> AnthropicProvider:
    p = AnthropicProvider(KEY, timeout_s=5, max_retries=0)
    p._client = anthropic.AsyncAnthropic(
        api_key=KEY,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return p


def _answer(status: int, kind: str = "api_error") -> Handler:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"type": kind, "message": VENDOR}})

    return handler


def _vendor(status: int, kind: str) -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": {"type": kind, "message": VENDOR}})

    return handler


def _refused(_: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError(VENDOR)


def _clean(err: BaseException, caplog: pytest.LogCaptureFixture) -> None:
    assert str(err) in FIXED_ERROR_WORDS, str(err)
    assert VENDOR not in str(err) and KEY not in str(err)
    _unchained(err)
    for record in caplog.records:
        assert VENDOR not in record.getMessage()
        assert VENDOR not in str(record.__dict__), record.__dict__
        assert KEY not in str(record.__dict__)


def _unchained(err: BaseException) -> None:
    """Security review LOW-1: `raise ... from None` inside `except` still leaves the vendor's
    exception (its response, body and request headers) on `__context__`; nothing may hold it."""
    assert err.__cause__ is None and err.__context__ is None, repr(err.__context__)


ANTHROPIC_CASES = [
    (401, "authentication_error", LLMAuthError),
    (403, "permission_error", LLMAuthError),
    (429, "rate_limit_error", LLMTransientError),
    (500, "api_error", LLMUnreachable),
    (529, "overloaded_error", LLMUnreachable),
    (400, "invalid_request_error", LLMError),
]


@pytest.mark.parametrize(("status", "kind", "cls"), ANTHROPIC_CASES)
async def test_anthropic_errors_carry_fixed_words_only(
    status: int, kind: str, cls: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(cls) as got:
        await _anthropic(_vendor(status, kind)).complete(
            system="s", messages=MSGS, model="m", max_tokens=5
        )
    _clean(got.value, caplog)  # no vendor chain: neither __cause__ nor __context__


async def test_anthropic_unreachable_and_its_stream_carry_fixed_words(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMUnreachable) as got:
        await _anthropic(_refused).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    _clean(got.value, caplog)
    with pytest.raises(LLMAuthError) as streamed:
        async for _ in _anthropic(_vendor(401, "authentication_error")).stream(
            system="s", messages=MSGS, model="m", max_tokens=5
        ):
            pass
    _clean(streamed.value, caplog)


HTTP_CASES = [
    (401, LLMAuthError),
    (403, LLMAuthError),
    (429, LLMTransientError),
    (408, LLMTransientError),
    (500, LLMUnreachable),
    (503, LLMUnreachable),
    (400, LLMError),
]


def _gemini(handler: Handler) -> GeminiProvider:
    return GeminiProvider(KEY, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _compat(handler: Handler) -> OpenAICompatProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatProvider("https://llm.example.com/v1", api_key=KEY, client=client)


@pytest.mark.parametrize(("status", "cls"), HTTP_CASES)
@pytest.mark.parametrize("build", [_gemini, _compat], ids=["gemini", "openai_compat"])
async def test_http_providers_carry_fixed_words_only(
    build: Callable[[Handler], Any],
    status: int,
    cls: type[Exception],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(cls) as got:
        await build(_answer(status)).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    _clean(got.value, caplog)
    with pytest.raises(cls) as streamed:
        async for _ in build(_answer(status)).stream(
            system="s", messages=MSGS, model="m", max_tokens=5
        ):
            pass
    _clean(streamed.value, caplog)


async def test_the_laptop_brain_inherits_the_fixed_words(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    transport = httpx.MockTransport(_answer(401))
    local = LocalBrainProvider(
        "http://laptop.example.com:11434/v1", api_key=KEY, timeout_s=5, transport=transport
    )
    with pytest.raises(LLMAuthError) as got:
        await local.complete(system="s", messages=MSGS, model="m", max_tokens=5)
    _clean(got.value, caplog)


def _timeout(_: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout(VENDOR)


def _no_route(_: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(VENDOR)


@pytest.mark.parametrize("handler", [_timeout, _no_route], ids=["timeout", "transport"])
@pytest.mark.parametrize("build", [_gemini, _compat], ids=["gemini", "openai_compat"])
async def test_an_unreachable_http_vendor_leaves_no_exception_behind(
    build: Callable[[Handler], Any], handler: Handler
) -> None:
    """LOW-1 for the two HTTP providers: httpx's error holds the request (and its key header)."""
    with pytest.raises(LLMUnreachable) as got:
        await build(handler).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    _unchained(got.value)
    assert VENDOR not in str(got.value)
    with pytest.raises(LLMUnreachable) as streamed:
        async for _ in build(handler).stream(system="s", messages=MSGS, model="m", max_tokens=5):
            pass
    _unchained(streamed.value)


async def test_a_non_json_answer_leaves_no_response_text_behind() -> None:
    """LOW-1, same rule: `JSONDecodeError.doc` is the whole response body (a proxy's page)."""

    def html(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"<html>{VENDOR}</html>")

    with pytest.raises(LLMError, match="non-JSON") as got:
        await _compat(html).complete(system="s", messages=MSGS, model="m", max_tokens=5)
    _unchained(got.value)


class _Raises:
    """`messages.create` / `messages.stream` that fail with our own bug, not the vendor's."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def create(self, **_: Any) -> Any:
        raise self.exc

    def stream(self, **_: Any) -> Any:
        raise self.exc


@pytest.mark.parametrize("path", ["complete", "stream"])
async def test_a_failure_log_names_the_cause_class_without_its_words(
    path: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Python review M2: a programming error must be told apart from an outage in the log
    (`cause` = the original class name), and its message is never logged."""
    caplog.set_level(logging.DEBUG)
    p = _anthropic(_vendor(200, "unused"))
    monkeypatch.setattr(p._client, "messages", _Raises(TypeError(VENDOR)))
    with pytest.raises(LLMError) as got:
        if path == "complete":
            await p.complete(system="s", messages=MSGS, model="m", max_tokens=5)
        else:
            async for _ in p.stream(system="s", messages=MSGS, model="m", max_tokens=5):
                pass
    _clean(got.value, caplog)
    (failed,) = [r for r in caplog.records if r.getMessage() == "llm call failed"]
    assert failed.__dict__["cause"] == "TypeError" and failed.__dict__["error"] == "LLMError"


async def test_a_vendor_failure_log_names_the_vendors_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMAuthError):
        await _anthropic(_vendor(401, "authentication_error")).complete(
            system="s", messages=MSGS, model="m", max_tokens=5
        )
    (failed,) = [r for r in caplog.records if r.getMessage() == "llm call failed"]
    assert failed.__dict__["cause"] == "AuthenticationError" and failed.__dict__["status"] == 401


class _Flaky:
    """Fails once on the strong model with vendor text, then answers on the balanced one."""

    name = "flaky"

    def __init__(self) -> None:
        self.models: list[str] = []

    async def complete(self, **kw: Any) -> Completion:
        self.models.append(kw["model"])
        if kw["model"] == "strong-model":
            raise LLMTransientError(VENDOR)
        usage = Usage(input_tokens=1, output_tokens=1)
        return Completion(text="ok", model=kw["model"], provider="flaky", usage=usage, latency_ms=0)

    def stream(self, **kw: Any) -> Any:
        raise NotImplementedError


async def test_the_router_logs_the_class_name_not_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    tiers = {
        ModelTier.STRONG: "strong-model",
        ModelTier.BALANCED: "balanced-model",
        ModelTier.FAST: "fast-model",
    }
    provider = _Flaky()
    router = ModelRouter(provider, tiers)
    done = await router.complete(tier=ModelTier.STRONG, system="s", messages=MSGS, max_tokens=5)
    assert done.text == "ok" and provider.models == ["strong-model", "balanced-model"]
    degraded = [r for r in caplog.records if "degraded" in r.getMessage()]
    assert degraded and degraded[0].__dict__["error"] == "LLMTransientError"
    assert all(VENDOR not in str(r.__dict__) for r in caplog.records)


def test_the_fixed_words_are_plain_and_distinct() -> None:
    assert len(FIXED_ERROR_WORDS) == len(set(FIXED_ERROR_WORDS)) >= 4
    assert all(w and w.isascii() and "{" not in w for w in FIXED_ERROR_WORDS)
