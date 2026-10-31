# src/jarvis/llm/base.py
"""Model-agnostic LLM interface.

Layer 4 (Core Reasoning). Nothing outside `jarvis.llm` may import a vendor SDK.
Skills and the Brain talk to `LLMProvider` + `ModelRouter`, never to Anthropic/OpenAI directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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
    """Result handed back to the model. `content` is untrusted data, never instructions."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


ContentBlock = TextBlock | ToolCall | ToolResultBlock


class ChatMessage(BaseModel):
    role: Role
    content: str | list[ContentBlock]

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class Completion(BaseModel):
    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str
    provider: str
    usage: Usage
    stop_reason: str | None = None
    latency_ms: int
    cost_usd: float = 0.0


class LLMError(Exception):
    """Base class for provider failures. Retryable ones subclass LLMTransientError."""


class LLMTransientError(LLMError):
    """Rate limit, overload, timeout — safe to retry or degrade to a cheaper tier."""


class LLMAuthError(LLMError):
    """Bad or missing credentials — never retry."""


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
    ) -> AsyncIterator[str]:
        """Yield text deltas. Phase 1 (voice) consumes this to start TTS early."""
        ...
