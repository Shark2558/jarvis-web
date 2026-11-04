# tests/test_local_provider.py -- R1 C (D10): the OpenAI-compatible client for the owner's laptop.
# Redirects off, replies capped at 1 MB, the key never echoed, 5xx / network = unreachable, and an
# overall deadline (httpx's timeouts are per phase; a trickling server must not hold a turn).
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from jarvis.llm.base import (
    ChatMessage,
    LLMAuthError,
    LLMError,
    LLMUnreachable,
    Role,
    StreamUsage,
)
from jarvis.llm.local_provider import MAX_RESPONSE_BYTES, LocalBrainProvider

BASE = "https://laptop.tail1234.ts.net/v1"
KEY = "k3y-should-never-leak-0123456789"
MSGS = [ChatMessage(role=Role.USER, content="hi")]
KW: dict[str, Any] = {"system": "s", "messages": MSGS, "model": "qwen2.5:7b", "max_tokens": 50}


def _ok(text: str = "At your service.") -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }


def _provider(
    handler: Callable[[httpx.Request], httpx.Response], timeout_s: float = 5.0
) -> LocalBrainProvider:
    return LocalBrainProvider(
        BASE, api_key=KEY, timeout_s=timeout_s, transport=httpx.MockTransport(handler)
    )


async def test_request_goes_to_chat_completions_with_the_bearer_key() -> None:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=_ok())

    c = await _provider(h).complete(**KW)
    assert c.text == "At your service." and c.model == "qwen2.5:7b"
    assert str(seen[0].url) == f"{BASE}/chat/completions"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(seen[0].content)["model"] == "qwen2.5:7b"


async def test_a_redirect_is_refused_not_followed() -> None:
    hits: list[str] = []

    def h(req: httpx.Request) -> httpx.Response:
        hits.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    with pytest.raises(LLMError):
        await _provider(h).complete(**KW)
    assert hits == [f"{BASE}/chat/completions"]  # the Location was never requested


async def test_a_redirect_on_a_stream_is_refused_too() -> None:
    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": "http://10.0.0.1/"})

    with pytest.raises(LLMError):
        async for _ in _provider(h).stream(**KW):
            pass


async def test_a_reply_over_one_megabyte_is_refused() -> None:
    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))

    with pytest.raises(LLMError, match="too large"):
        await _provider(h).complete(**KW)


async def test_a_reply_just_under_the_cap_is_read() -> None:
    pad = "a" * 1000
    body = json.dumps(_ok(pad)).encode()

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    assert (await _provider(h).complete(**KW)).text == pad


async def test_a_stream_over_the_cap_is_cut() -> None:
    chunk = json.dumps({"choices": [{"delta": {"content": "y" * 50_000}}]})
    sse = ("data: " + chunk + "\n\n") * 30 + "data: [DONE]\n\n"

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse.encode())

    got = 0
    with pytest.raises(LLMError, match="too large"):
        async for d in _provider(h).stream(**KW):
            got += len(d)
    assert got <= MAX_RESPONSE_BYTES


async def test_stream_reports_zero_usage_so_an_offline_reply_meters_nothing() -> None:
    sse = 'data: {"choices":[{"delta":{"content":"hi "}}]}\n\ndata: [DONE]\n\n'

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse.encode())

    usage = StreamUsage()
    out = [d async for d in _provider(h).stream(usage=usage, **KW)]
    assert out == ["hi "]
    assert usage.reported and usage.final
    assert usage.input_tokens == 0 and usage.output_tokens == 0


@pytest.mark.parametrize(
    ("status", "exc"), [(401, LLMAuthError), (403, LLMAuthError), (503, LLMUnreachable)]
)
async def test_errors_never_echo_the_key(status: int, exc: type[Exception]) -> None:
    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"bad {KEY}"}})

    with pytest.raises(exc) as ei:
        await _provider(h).complete(**KW)
    assert KEY not in str(ei.value)


async def test_a_dead_laptop_is_unreachable() -> None:
    def h(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMUnreachable):
        await _provider(h).complete(**KW)


async def test_the_overall_deadline_cuts_a_server_that_trickles() -> None:
    async def slow_stream() -> Any:
        for _ in range(100):
            await asyncio.sleep(0.05)
            yield b" "

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=slow_stream())

    with pytest.raises(LLMUnreachable):
        await _provider(h, timeout_s=0.2).complete(**KW)


async def test_the_key_is_optional_in_the_client_itself() -> None:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=_ok())

    p = LocalBrainProvider(BASE, api_key=None, timeout_s=5, transport=httpx.MockTransport(h))
    await p.complete(**KW)
    assert "authorization" not in seen[0].headers


async def test_close_releases_the_client() -> None:
    p = _provider(lambda _: httpx.Response(200, json=_ok()))
    await p.aclose()
    await p.aclose()  # idempotent


async def test_stream_deadline_never_cancels_the_consumer() -> None:
    """The timeout must not be a scope held across `yield`: a consumer that awaits between chunks
    past the deadline gets LLMUnreachable on its next read, never a cancellation of its own task."""
    sse = (
        "".join(f'data: {{"choices":[{{"delta":{{"content":"w{i} "}}}}]}}\n\n' for i in range(6))
        + "data: [DONE]\n\n"
    )

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse.encode())

    got: list[str] = []
    slept = 0
    with pytest.raises(LLMUnreachable):
        async for d in _provider(h, timeout_s=0.3).stream(**KW):
            got.append(d)
            await asyncio.sleep(0.15)  # the consumer's own awaits
            slept += 1
    assert 1 <= len(got) < 6
    assert slept == len(got)  # every consumer sleep completed: none was cancelled


async def test_stream_slow_server_is_cut_at_the_deadline_per_read() -> None:
    async def trickle() -> Any:
        yield b'data: {"choices":[{"delta":{"content":"a "}}]}\n\n'
        await asyncio.sleep(5)
        yield b"data: [DONE]\n\n"

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=trickle())

    got: list[str] = []
    with pytest.raises(LLMUnreachable):
        async for d in _provider(h, timeout_s=0.3).stream(**KW):
            got.append(d)
    assert got == ["a "]


# ---- M1: the byte cap holds on the raw wire, whatever the stream carries -----------------------

CHUNK = 64 * 1024


def _gen(total: int, fill: bytes, served: list[int]) -> Any:
    async def body() -> Any:
        sent = 0
        while sent < total:
            piece = (fill * CHUNK)[:CHUNK]
            sent += len(piece)
            served.append(sent)
            yield piece

    return body()


async def test_sse_comment_lines_do_not_get_round_the_cap() -> None:
    served: list[int] = []

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_gen(3_000_000, b": xxxxxxxx\n", served))

    with pytest.raises(LLMError, match="too large"):
        async for _ in _provider(h).stream(**KW):
            pass
    assert served[-1] <= MAX_RESPONSE_BYTES + 2 * CHUNK


async def test_a_line_with_no_newline_is_cut_at_the_cap() -> None:
    served: list[int] = []

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_gen(3_000_000, b"x", served))

    with pytest.raises(LLMError, match="too large"):
        async for _ in _provider(h).stream(**KW):
            pass
    assert served[-1] <= MAX_RESPONSE_BYTES + 2 * CHUNK


async def test_a_huge_error_body_is_not_buffered_whole() -> None:
    served: list[int] = []

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=_gen(3_000_000, b"e", served))

    with pytest.raises(LLMError):
        async for _ in _provider(h).stream(**KW):
            pass
    assert served[-1] <= MAX_RESPONSE_BYTES + 2 * CHUNK


async def test_a_normal_stream_is_unaffected_by_the_wire_cap() -> None:
    sse = 'data: {"choices":[{"delta":{"content":"hi "}}]}\n\ndata: [DONE]\n\n'

    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse.encode())

    assert [d async for d in _provider(h).stream(**KW)] == ["hi "]
