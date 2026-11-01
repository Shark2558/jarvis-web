# src/jarvis/llm/mock_provider.py
"""Deterministic provider for tests, evals in CI, and offline development.

Scripted replies are consumed FIFO; when the script is empty it echoes the last user turn.
`fail_next` injects a transient error so retry / degradation paths are testable.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMTransientError,
    StreamUsage,
    ToolCall,
    ToolSpec,
    Usage,
)


@dataclass
class RecordedCall:
    system: str
    messages: list[ChatMessage]
    model: str
    max_tokens: int
    effort: Effort | None
    tools: list[ToolSpec] | None = None


@dataclass
class MockProvider:
    name: str = "mock"
    scripted: deque[str | tuple[list[ToolCall], str]] = field(default_factory=deque)
    calls: list[RecordedCall] = field(default_factory=list)
    fail_next: int = 0
    latency_ms: int = 0

    def script(self, *replies: str) -> None:
        self.scripted.extend(replies)

    def script_tool_calls(self, calls: list[ToolCall], final_text: str | None = None) -> None:
        """Next completion asks for `calls`; the one after (if given) is `final_text`."""
        self.scripted.append((calls, ""))
        if final_text is not None:
            self.scripted.append(final_text)

    def _reply(self, messages: list[ChatMessage]) -> tuple[str, list[ToolCall]]:
        if self.scripted:
            item = self.scripted.popleft()
            if isinstance(item, tuple):
                return item[1], item[0]
            return item, []
        last_user = next((m.text() for m in reversed(messages) if m.role == "user"), "")
        return f"Certainly, Sir. You said: {last_user}", []

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
        full_system = system + ("\n" + system_dynamic if system_dynamic else "")
        self.calls.append(
            RecordedCall(full_system, list(messages), model, max_tokens, effort, tools)
        )
        if self.fail_next > 0:
            self.fail_next -= 1
            raise LLMTransientError("mock: simulated transient failure")
        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000)
        text, calls = self._reply(messages)
        approx_in = sum(len(m.text()) for m in messages) // 4 + len(full_system) // 4
        return Completion(
            text=text,
            tool_calls=calls,
            model=model,
            provider=self.name,
            usage=Usage(input_tokens=approx_in, output_tokens=max(1, len(text) // 4)),
            stop_reason="tool_use" if calls else "end_turn",
            latency_ms=self.latency_ms,
            cost_usd=0.0,
        )

    async def stream(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        usage: StreamUsage | None = None,  # reports nothing: the caller's estimate is exercised
    ) -> AsyncIterator[str]:
        completion = await self.complete(
            system=system,
            system_dynamic=system_dynamic,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            effort=effort,
        )
        for word in completion.text.split(" "):
            yield word + " "
