# src/jarvis/llm/local_provider.py
"""The client for the owner's laptop brain (R1 D10): an OpenAI-compatible provider (Ollama) with
the limits a fetch of an owner-supplied URL needs.

On top of `OpenAICompatProvider`: redirects are never followed (a 3xx is an error), a reply is
capped at 1 MB (streamed or not), the whole call has one deadline (`timeout_s`; httpx's own
timeouts are per phase, so a server that trickles bytes could hold a turn for ever), and a streamed
reply reports zero tokens so it is metered at nothing (the laptop is free).

The base URL has already passed `jarvis.offline.config.check_url`; this class does not decide
whether a URL is allowed, it only refuses to be pushed elsewhere.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMError,
    LLMUnreachable,
    StreamUsage,
    ToolSpec,
)
from jarvis.llm.openai_compat_provider import OpenAICompatProvider

MAX_RESPONSE_BYTES = 1_000_000


class _CappedBody(httpx.AsyncByteStream):
    """The raw bytes of one reply, counted as they come off the wire: past the cap the read stops
    (before httpx buffers a line or an error body, and whatever the SSE stream carries)."""

    def __init__(self, inner: httpx.AsyncByteStream) -> None:
        self._inner = inner

    async def __aiter__(self) -> AsyncIterator[bytes]:
        seen = 0
        async for chunk in self._inner:
            seen += len(chunk)
            if seen > MAX_RESPONSE_BYTES:
                raise LLMError("local brain reply too large")
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


class _CappingTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        resp = await self._inner.handle_async_request(request)
        assert isinstance(resp.stream, httpx.AsyncByteStream)
        return httpx.Response(
            resp.status_code,
            headers=resp.headers,
            stream=_CappedBody(resp.stream),
            extensions=resp.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


class LocalBrainProvider(OpenAICompatProvider):
    name = "local_brain"

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url,
            api_key=api_key,
            client=httpx.AsyncClient(
                timeout=timeout_s,
                follow_redirects=False,
                transport=_CappingTransport(transport or httpx.AsyncHTTPTransport()),
            ),
        )
        self._deadline_s = timeout_s

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        async with self._client.stream(
            "POST", f"{self._base}/chat/completions", headers=self._headers(), json=body
        ) as resp:
            if 300 <= resp.status_code < 400:
                raise LLMError("local brain redirected: refused")
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_RESPONSE_BYTES:
                    raise LLMError("local brain reply too large")
            return httpx.Response(
                resp.status_code,
                content=bytes(buf),
                headers={"content-type": resp.headers.get("content-type", "application/json")},
            )

    async def complete(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> Completion:
        try:
            async with asyncio.timeout(self._deadline_s):
                return await super().complete(
                    system=system,
                    system_dynamic=system_dynamic,
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    effort=effort,
                    tools=tools,
                )
        except TimeoutError as exc:
            raise LLMUnreachable("local brain timed out") from exc

    async def stream(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        usage: StreamUsage | None = None,
    ) -> AsyncIterator[str]:
        sent = 0
        # One monotonic deadline for the whole stream. Each read is bounded with wait_for on its
        # own __anext__: a timeout scope must never be held across `yield` (its cancellation could
        # land in the consumer's task).
        deadline = time.monotonic() + self._deadline_s
        inner = (
            super()
            .stream(
                system=system,
                system_dynamic=system_dynamic,
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                effort=effort,
            )
            .__aiter__()
        )
        try:
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise LLMUnreachable("local brain timed out")
                try:
                    delta = await asyncio.wait_for(inner.__anext__(), left)
                except StopAsyncIteration:
                    break
                except TimeoutError as exc:
                    raise LLMUnreachable("local brain timed out") from exc
                sent += len(delta.encode())
                if sent > MAX_RESPONSE_BYTES:
                    raise LLMError("local brain reply too large")
                yield delta
        finally:
            aclose = getattr(inner, "aclose", None)
            if aclose is not None:
                await aclose()
        if usage is not None:  # free: metered as nothing, never guessed from characters
            usage.started(
                input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0
            )
            usage.finished(output_tokens=0)
