# src/jarvis/llm/anthropic_provider.py
"""Claude implementation of LLMProvider. The only file that imports the `anthropic` SDK."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import anthropic
from anthropic.types import (
    MessageParam,
    RawContentBlockDeltaEvent,
    RawMessageDeltaEvent,
    RawMessageStartEvent,
    TextBlockParam,
    TextDelta,
    ToolParam,
    ToolUseBlock,
)
from anthropic.types import TextBlock as AnthropicTextBlock

from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMAuthError,
    LLMError,
    LLMTransientError,
    LLMUnreachable,
    StreamUsage,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
    Usage,
)
from jarvis.llm.pricing import cost_usd
from jarvis.logging import get_logger

log = get_logger(__name__)

_TRANSIENT = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
    anthropic.ServiceUnavailableError,
)
# R1 D12: the vendor could not be reached at all (no answer, or a server-side 5xx). A 429 is NOT
# one of these: it stays a plain transient error and never sends a turn to the owner's laptop.
_UNREACHABLE = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
    anthropic.ServiceUnavailableError,
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, *, timeout_s: float = 60.0, max_retries: int = 2) -> None:
        # The SDK retries transient errors with exponential backoff itself; we set the budget.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_s, max_retries=max_retries
        )

    # ---- helpers -------------------------------------------------------------------------

    @staticmethod
    def _to_params(messages: list[ChatMessage]) -> list[MessageParam]:
        out: list[MessageParam] = []
        for m in messages:
            if isinstance(m.content, str):
                out.append({"role": m.role.value, "content": m.content})
                continue
            blocks: list = []
            for b in m.content:
                if isinstance(b, TextBlock):
                    blocks.append({"type": "text", "text": b.text})
                elif isinstance(b, ToolCall):
                    blocks.append(
                        {"type": "tool_use", "id": b.id, "name": b.name, "input": b.arguments}
                    )
                elif isinstance(b, ToolResultBlock):
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": b.tool_use_id,
                            "content": b.content,
                            "is_error": b.is_error,
                        }
                    )
            out.append({"role": m.role.value, "content": blocks})
        return out

    @staticmethod
    def _tool_params(tools: list[ToolSpec] | None) -> list[ToolParam] | None:
        if not tools:
            return None
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]

    @staticmethod
    def _system_blocks(system: str, system_dynamic: str | None) -> list[TextBlockParam]:
        # The persona/system prompt is identical across turns → mark it cacheable.
        # Cache reads cost 5-10% of input price; this is the single cheapest win we have.
        # Per-request context (time, session facts) goes in a second, uncached block so it
        # never invalidates the cached prefix.
        blocks: list[TextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        if system_dynamic:
            blocks.append({"type": "text", "text": system_dynamic})
        return blocks

    @staticmethod
    def _usage(u: anthropic.types.Usage) -> Usage:
        return Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
        )

    @staticmethod
    def _translate(exc: Exception) -> LLMError:
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            return LLMAuthError(str(exc))
        if isinstance(exc, _UNREACHABLE) or (
            isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500
        ):
            return LLMUnreachable(str(exc))
        if isinstance(exc, _TRANSIENT):
            return LLMTransientError(str(exc))
        return LLMError(str(exc))

    def _kwargs(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None,
        tools: list[ToolSpec] | None = None,
    ) -> dict:
        kw: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": self._system_blocks(system, system_dynamic),
            "messages": self._to_params(messages),
        }
        if effort is not None:
            kw["output_config"] = {"effort": effort.value}
        tp = self._tool_params(tools)
        if tp:
            kw["tools"] = tp
        return kw

    # ---- LLMProvider ---------------------------------------------------------------------

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
        t0 = time.perf_counter()
        try:
            msg = await self._client.messages.create(
                **self._kwargs(
                    system=system,
                    system_dynamic=system_dynamic,
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    effort=effort,
                    tools=tools,
                )
            )
        except Exception as exc:  # noqa: BLE001 — translated into our hierarchy below
            err = self._translate(exc)
            log.error("llm call failed", extra={"model": model, "error": type(err).__name__})
            raise err from exc

        latency_ms = int((time.perf_counter() - t0) * 1000)
        text = "".join(b.text for b in msg.content if isinstance(b, AnthropicTextBlock))
        calls = [
            ToolCall(
                id=b.id, name=b.name, arguments=dict(b.input) if isinstance(b.input, dict) else {}
            )
            for b in msg.content
            if isinstance(b, ToolUseBlock)
        ]
        usage = self._usage(msg.usage)
        completion = Completion(
            text=text,
            tool_calls=calls,
            model=msg.model,
            provider=self.name,
            usage=usage,
            stop_reason=msg.stop_reason,
            latency_ms=latency_ms,
            cost_usd=cost_usd(model, usage),
        )
        log.info(
            "llm call",
            extra={
                "model": msg.model,
                "in_tok": usage.input_tokens,
                "out_tok": usage.output_tokens,
                "cache_read": usage.cache_read_tokens,
                "latency_ms": latency_ms,
                "cost_usd": completion.cost_usd,
                "stop": msg.stop_reason,
            },
        )
        return completion

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
        """Text deltas; the exact usage goes into `usage` as it arrives: input + cache counts on
        `message_start`, the cumulative output (and any revised input) on `message_delta`. A
        reader that leaves early keeps the opening counts (the caller estimates the rest)."""
        try:
            async with self._client.messages.stream(
                **self._kwargs(
                    system=system,
                    system_dynamic=system_dynamic,
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    effort=effort,
                )
            ) as stream:
                async for event in stream:
                    if isinstance(event, RawContentBlockDeltaEvent):
                        if isinstance(event.delta, TextDelta) and event.delta.text:
                            yield event.delta.text
                    elif usage is not None:
                        self._note_usage(event, usage)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    @staticmethod
    def _note_usage(event: object, sink: StreamUsage) -> None:
        if isinstance(event, RawMessageStartEvent):
            u = event.message.usage
            sink.started(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_input_tokens,
                cache_write_tokens=u.cache_creation_input_tokens,
            )
        elif isinstance(event, RawMessageDeltaEvent):
            d = event.usage
            sink.finished(
                output_tokens=d.output_tokens,
                input_tokens=d.input_tokens,
                cache_read_tokens=d.cache_read_input_tokens,
                cache_write_tokens=d.cache_creation_input_tokens,
            )
