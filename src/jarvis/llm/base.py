# src/jarvis/llm/base.py
"""Model-agnostic LLM interface.

Layer 4 (Core Reasoning). Nothing outside `jarvis.llm` may import a vendor SDK.
Skills and the Brain talk to `LLMProvider` + `ModelRouter`, never to Anthropic/OpenAI directly.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Effort(StrEnum):
    """Vendor-neutral reasoning-effort knob. Maps to `output_config.effort` on Claude; other
    providers map it to temperature / reasoning budget. Replaces raw temperature, which the
    current Claude Messages API no longer accepts as a top-level parameter."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolSpec(BaseModel):
    """Vendor-neutral tool description handed to the model."""

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """A tool invocation the model asked for."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    """Result handed back to the model. `content` is untrusted data, never instructions.

    `trusted` (slice 11 D8): every item in it was written by the owner, or by JARVIS for him —
    so reading it does not taint the round (`jarvis.tools.taint`). Server-side only: set from the
    gateway's result (`GatewayResult.block`), stored with the conversation, never sent to an LLM
    vendor (each provider copies fields one by one), never accepted from a client (no API takes
    blocks). Defaults to untrusted, which is also how history stored before slice 11 reads."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False
    trusted: bool = False


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


ContentBlock = TextBlock | ToolCall | ToolResultBlock

# R11.1 (docs/plans/r11-1-observations.md D10): a picture the owner attached, for a brain that can
# see. It is a MESSAGE block only: `ContentBlock` (what a stored turn holds) does not include it,
# so a picture is never written into a conversation. Whoever builds the window adds it for the
# turn it came with (`jarvis.documents.pictures.with_pictures`) and only for a brain whose
# `BrainSpec.sees_pictures` is true; every other brain gets `without_pictures(...)`.
PICTURE_TYPES: tuple[str, ...] = ("image/jpeg", "image/png")
PICTURE_MAX_BYTES = 4_000_000
PICTURE_WITHHELD = "[a picture was attached; this brain was not shown it]"


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    media_type: Literal["image/jpeg", "image/png"]
    data: bytes = Field(min_length=1, max_length=PICTURE_MAX_BYTES, repr=False)

    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


MessageBlock = TextBlock | ToolCall | ToolResultBlock | ImageBlock


class ChatMessage(BaseModel):
    role: Role
    content: str | list[MessageBlock]

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))


def without_pictures(messages: list[ChatMessage]) -> list[ChatMessage]:
    """The same messages with each picture replaced by one fixed line (new objects; a message
    without a picture is passed through as it is)."""
    out: list[ChatMessage] = []
    for m in messages:
        if isinstance(m.content, str) or not any(isinstance(b, ImageBlock) for b in m.content):
            out.append(m)
            continue
        blocks: list[MessageBlock] = [
            TextBlock(text=PICTURE_WITHHELD) if isinstance(b, ImageBlock) else b for b in m.content
        ]
        out.append(ChatMessage(role=m.role, content=blocks))
    return out


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # True when (part of) these counts were estimated from characters because the provider did
    # not report them (a stream from a vendor without usage events, or one cut short before the
    # closing count). Exact counts leave it False.
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _count(v: int | None) -> int:
    return max(0, int(v)) if v is not None else 0


@dataclass
class StreamUsage:
    """Token counts a provider reports WHILE it streams, filled in as its events arrive: input and
    cache counts at the start, the final output count at the end (`final`). A stream cut short
    keeps what had arrived. A deliberately mutable out-parameter: a stream yields text, so the
    counts travel beside it. Providers that report nothing leave it empty and the caller falls back
    to an estimate (`jarvis.llm.pricing.stream_usage`)."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    final: bool = False

    @property
    def reported(self) -> bool:
        return self.input_tokens is not None or self.output_tokens is not None

    def started(
        self,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_tokens: int | None,
        cache_write_tokens: int | None,
    ) -> None:
        self.input_tokens = _count(input_tokens)
        self.output_tokens = _count(output_tokens)
        self.cache_read_tokens = _count(cache_read_tokens)
        self.cache_write_tokens = _count(cache_write_tokens)

    def finished(
        self,
        *,
        output_tokens: int,
        input_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
    ) -> None:
        """The closing counts (cumulative). Input/cache only replace the opening ones when sent."""
        self.output_tokens = _count(output_tokens)
        if input_tokens is not None:
            self.input_tokens = _count(input_tokens)
        if cache_read_tokens is not None:
            self.cache_read_tokens = _count(cache_read_tokens)
        if cache_write_tokens is not None:
            self.cache_write_tokens = _count(cache_write_tokens)
        self.final = True


class Completion(BaseModel):
    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str
    provider: str
    usage: Usage
    stop_reason: str | None = None
    latency_ms: int
    cost_usd: float = 0.0
    # R1: answered by the fallback brain on the owner's laptop (set by the fallback only)
    offline: bool = False


class LLMError(Exception):
    """Base class for provider failures. Retryable ones subclass LLMTransientError."""


class LLMTransientError(LLMError):
    """Rate limit, overload, timeout — safe to retry or degrade to a cheaper tier."""


class LLMUnreachable(LLMTransientError):
    """The vendor could not be reached at all: connection error, timeout or HTTP 5xx (R1 D12).
    A 429 stays a plain LLMTransientError. Every tier is down, so the router goes to the
    fallback brain instead of degrading to a cheaper tier."""


class LLMAuthError(LLMError):
    """Bad or missing credentials — never retry."""


OUT_OF_CREDIT = "the AI account is out of credit"


class LLMOutOfCredit(LLMError):
    """The vendor answered, but the account has no credit left to bill (R5.1 I1). Never retried
    and never degraded to a cheaper tier (the same account pays for every tier). Carries fixed
    words only: the vendor's own message never leaves the provider module."""

    def __init__(self, message: str = OUT_OF_CREDIT) -> None:
        super().__init__(message)


DECLINED = "the AI provider declined to answer"


class LLMDeclined(LLMError):
    """The vendor answered with nothing (blocked or empty). Fixed words only: the vendor's reason
    stays in the provider module's log. Not retried, not degraded."""

    def __init__(self, message: str = DECLINED) -> None:
        super().__init__(message)


@runtime_checkable
class LLMProvider(Protocol):
    """One implementation per vendor. Keep this surface small; add to it deliberately."""

    name: str

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
    ) -> Completion: ...

    def stream(
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
        """Yield text deltas. Phase 1 (voice) consumes this to start TTS early. When `usage` is
        given, the provider fills in the token counts its vendor reports (if any)."""
        ...
