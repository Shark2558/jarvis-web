# src/jarvis/llm/anthropic_provider.py
"""Claude implementation of LLMProvider. The only file that imports the `anthropic` SDK.

R14 D9 (A1 choice (b), docs/plans/r14-hardening.md): built with `cache_history` (the setting, on
by default, through `jarvis.llm.factory`), a call adds a second cache breakpoint on the last
message block, so the next round of the SAME reply reads the history from the cache. The trailer
is a system block before the messages, so the hint never reaches across turns. The stream path
(one call a reply) keeps the system breakpoint only. Nothing in the shared interface changes.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, cast

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
    AUTH_REFUSED,
    BUSY,
    NO_ANSWER,
    UNREACHABLE,
    ChatMessage,
    Completion,
    Effort,
    ImageBlock,
    LLMAuthError,
    LLMError,
    LLMOutOfCredit,
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


EPHEMERAL: dict[str, str] = {"type": "ephemeral"}


class AnthropicProvider:
    name = "anthropic"
    vision = True  # R11.1 D10: Claude reads JPEG and PNG message blocks

    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: float = 60.0,
        max_retries: int = 2,
        cache_history: bool = False,
    ) -> None:
        # The SDK retries transient errors with exponential backoff itself; we set the budget.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_s, max_retries=max_retries
        )
        self.cache_history = cache_history  # R14 D9: the history's breakpoint (the setting)

    # ---- helpers -------------------------------------------------------------------------

    @staticmethod
    def _block(b: object) -> dict[str, Any] | None:
        if isinstance(b, TextBlock):
            return {"type": "text", "text": b.text}
        if isinstance(b, ImageBlock):  # R11.1 D10: the owner's own attached picture
            source = {"type": "base64", "media_type": b.media_type, "data": b.b64()}
            return {"type": "image", "source": source}
        if isinstance(b, ToolCall):
            return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.arguments}
        if isinstance(b, ToolResultBlock):  # `trusted` is ours: never sent (base.py)
            return {
                "type": "tool_result",
                "tool_use_id": b.tool_use_id,
                "content": b.content,
                "is_error": b.is_error,
            }
        return None

    @classmethod
    def _to_params(cls, messages: list[ChatMessage]) -> list[MessageParam]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if isinstance(m.content, str):
                out.append({"role": m.role.value, "content": m.content})
                continue
            blocks = [p for p in (cls._block(b) for b in m.content) if p is not None]
            out.append({"role": m.role.value, "content": blocks})
        return cast(list[MessageParam], out)

    @staticmethod
    def _mark_last(params: list[MessageParam]) -> None:
        """R14 D9: a cache breakpoint on the last message's last non-empty block. Every plain
        string goes out as one text block, so a later round's prefix is byte-for-byte the same
        as this one's. `params` are this call's own copies."""
        for p in params:
            msg = cast(dict[str, Any], p)
            if isinstance(msg["content"], str) and msg["content"]:
                msg["content"] = [{"type": "text", "text": msg["content"]}]
        content = cast(dict[str, Any], params[-1])["content"] if params else ""
        for block in reversed(content if isinstance(content, list) else []):
            if block.get("type") != "text" or block.get("text"):
                block["cache_control"] = EPHEMERAL
                return

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
    def _out_of_credit(exc: Exception) -> bool:
        """Anthropic's low-credit answer: HTTP 400, error type `invalid_request_error`, a message
        about the credit balance (R5.1 I1). Only read here, never passed on."""
        if not isinstance(exc, anthropic.BadRequestError):
            return False
        body = exc.body if isinstance(exc.body, dict) else {}
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        message = err.get("message") if isinstance(err, dict) else None
        return (
            isinstance(err, dict)
            and err.get("type") == "invalid_request_error"
            and isinstance(message, str)
            and "credit balance" in message.lower()
        )

    @classmethod
    def _translate(cls, exc: Exception) -> LLMError:
        """Our error class with FIXED words (R14 D9): the vendor's message is read here only to
        tell a low credit balance apart, and never passed on, chained or logged."""
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            return LLMAuthError(AUTH_REFUSED)
        if cls._out_of_credit(exc):
            return LLMOutOfCredit()
        if isinstance(exc, _UNREACHABLE) or (
            isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500
        ):
            return LLMUnreachable(UNREACHABLE)
        if isinstance(exc, _TRANSIENT):
            return LLMTransientError(BUSY)
        return LLMError(NO_ANSWER)

    @classmethod
    def _failed(cls, exc: Exception, model: str) -> LLMError:
        """The translated error, logged with its class and HTTP status only."""
        err = cls._translate(exc)
        status = exc.status_code if isinstance(exc, anthropic.APIStatusError) else None
        extra = {"model": model, "error": type(err).__name__, "status": status}
        log.error("llm call failed", extra=extra)
        return err

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
        history_hint: bool = False,
    ) -> dict[str, Any]:
        params = self._to_params(messages)
        if history_hint and self.cache_history:
            self._mark_last(params)
        kw: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": self._system_blocks(system, system_dynamic),
            "messages": params,
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
                    history_hint=True,
                )
            )
        except Exception as exc:  # noqa: BLE001 — translated into our hierarchy, no chain
            raise self._failed(exc, model) from None

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
        except Exception as exc:  # noqa: BLE001 — translated into our hierarchy, no chain
            raise self._failed(exc, model) from None

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
