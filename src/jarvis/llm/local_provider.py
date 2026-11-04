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
                timeout=timeout_s, follow_redirects=False, transport=transport
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
        try:
            async with asyncio.timeout(self._deadline_s):
                async for delta in super().stream(
                    system=system,
                    system_dynamic=system_dynamic,
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    effort=effort,
                ):
                    sent += len(delta.encode())
                    if sent > MAX_RESPONSE_BYTES:
                        raise LLMError("local brain reply too large")
                    yield delta
        except TimeoutError as exc:
            raise LLMUnreachable("local brain timed out") from exc
        if usage is not None:  # free: metered as nothing, never guessed from characters
            usage.started(
                input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0
            )
            usage.finished(output_tokens=0)
