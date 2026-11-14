# src/jarvis/llm/gemini_provider.py
"""Gemini implementation of LLMProvider over the public REST API (httpx; no vendor SDK).

CHAT ONLY. Tools are deliberately dropped: on the free tier Google may use prompts to improve
its products, so this brain must never receive email/calendar/tool output. History that
contains tool blocks (e.g. the owner switched brains mid-session) is flattened to plain text.

Written against ai.google.dev docs of 2026-10-28; not exercised against the live API in CI
(no key) — hence the single defensive retry without `thinkingConfig` on a 400.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from jarvis.llm.base import (
    AUTH_REFUSED,
    BUSY,
    NO_ANSWER,
    UNREACHABLE,
    ChatMessage,
    Completion,
    Effort,
    LLMAuthError,
    LLMDeclined,
    LLMError,
    LLMTransientError,
    LLMUnreachable,
    Role,
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

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MIN_OUTPUT_TOKENS = 2048  # Gemini 3.x thinks by default and thought tokens share this budget
OUTPUT_PAD = 4
_THINKING_LEVEL = {Effort.LOW: "low", Effort.MEDIUM: "medium", Effort.HIGH: "high"}
_STOP = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens"}


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    # ---- request building ----------------------------------------------------------------

    @staticmethod
    def _flatten(m: ChatMessage) -> str:
        if isinstance(m.content, str):
            return m.content
        parts: list[str] = []
        for b in m.content:
            if isinstance(b, TextBlock):
                parts.append(b.text)
            elif isinstance(b, ToolCall | ToolResultBlock):
                # Brain already withholds such turns from training brains; if one slips
                # through, neither tool names nor tool output may reach this vendor.
                parts.append("[tool exchange withheld]")
        return "\n".join(p for p in parts if p)

    @classmethod
    def _contents(cls, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            text = cls._flatten(m)
            if not text:
                continue
            role = "user" if m.role is Role.USER else "model"
            if out and out[-1]["role"] == role:  # Gemini wants alternating turns
                out[-1]["parts"].append({"text": text})
            else:
                out.append({"role": role, "parts": [{"text": text}]})
        return out

    def _body(
        self,
        *,
        system: str,
        system_dynamic: str | None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None,
        thinking: bool = True,
    ) -> dict[str, Any]:
        sys_parts = [{"text": system}]
        if system_dynamic:
            sys_parts.append({"text": system_dynamic})
        gen: dict[str, Any] = {"maxOutputTokens": max(MIN_OUTPUT_TOKENS, max_tokens * OUTPUT_PAD)}
        if effort is not None and thinking:
            gen["thinkingConfig"] = {"thinkingLevel": _THINKING_LEVEL[effort]}
        return {
            "systemInstruction": {"parts": sys_parts},
            "contents": self._contents(messages),
            "generationConfig": gen,
        }

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._key, "content-type": "application/json"}

    def _url(self, model: str, method: str) -> str:
        return f"{BASE_URL}/models/{model}:{method}"

    # ---- response handling ---------------------------------------------------------------

    def _raise_for_status(self, resp: httpx.Response) -> None:
        """Our error class with FIXED words (R14 D9): Google's answer body is never read into
        the error or a log line; the log says the HTTP status only."""
        code = resp.status_code
        if code < 400:
            return
        log.warning("gemini call failed", extra={"status": code})
        if code in (401, 403):
            raise LLMAuthError(AUTH_REFUSED)
        if code >= 500:
            raise LLMUnreachable(UNREACHABLE)
        if code in (408, 429):
            raise LLMTransientError(BUSY)
        raise LLMError(NO_ANSWER)

    @staticmethod
    def _text(parts: list[dict[str, Any]]) -> str:
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    @staticmethod
    def _usage(meta: dict[str, Any]) -> Usage:
        return Usage(
            input_tokens=int(meta.get("promptTokenCount", 0)),
            output_tokens=int(meta.get("candidatesTokenCount", 0))
            + int(meta.get("thoughtsTokenCount", 0)),
            cache_read_tokens=int(meta.get("cachedContentTokenCount", 0)),
        )

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
        if tools:
            log.warning("gemini brain is chat-only; tools dropped", extra={"n_tools": len(tools)})
        t0 = time.perf_counter()
        data = await self._post(model, system, system_dynamic, messages, max_tokens, effort)
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        if not parts:
            reason = (data.get("promptFeedback") or {}).get("blockReason") or cand.get(
                "finishReason", "empty"
            )
            log.warning("gemini returned no answer", extra={"reason": str(reason)[:60]})
            raise LLMDeclined()
        usage = self._usage(data.get("usageMetadata") or {})
        latency_ms = int((time.perf_counter() - t0) * 1000)
        completion = Completion(
            text=self._text(parts),
            model=model,
            provider=self.name,
            usage=usage,
            stop_reason=_STOP.get(cand.get("finishReason", ""), cand.get("finishReason")),
            latency_ms=latency_ms,
            cost_usd=cost_usd(model, usage),
        )
        log.info(
            "llm call",
            extra={
                "model": model,
                "in_tok": usage.input_tokens,
                "out_tok": usage.output_tokens,
                "latency_ms": latency_ms,
            },
        )
        return completion

    async def _post(
        self,
        model: str,
        system: str,
        system_dynamic: str | None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None,
    ) -> dict[str, Any]:
        for thinking in (True, False):
            body = self._body(
                system=system,
                system_dynamic=system_dynamic,
                messages=messages,
                max_tokens=max_tokens,
                effort=effort,
                thinking=thinking,
            )
            resp = await self._send(model, body)
            if (
                resp.status_code == 400
                and thinking
                and "thinking" in resp.text.lower()
                and effort is not None
            ):
                log.warning("gemini rejected thinkingConfig; retrying without it")
                continue
            self._raise_for_status(resp)
            data: dict[str, Any] = resp.json()
            return data
        raise AssertionError("unreachable")

    async def _send(self, model: str, body: dict[str, Any]) -> httpx.Response:
        failed: LLMUnreachable
        try:
            return await self._client.post(
                self._url(model, "generateContent"), headers=self._headers(), json=body
            )
        except httpx.TransportError as exc:  # a timeout is one too
            failed = _unreachable(exc, "request")
        raise failed  # outside the except block: no __context__ (R14 security review LOW-1)

    async def stream(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        usage: StreamUsage | None = None,  # not filled yet (free models): the caller estimates
    ) -> AsyncIterator[str]:
        body = self._body(
            system=system,
            system_dynamic=system_dynamic,
            messages=messages,
            max_tokens=max_tokens,
            effort=effort,
        )
        failed: LLMUnreachable | None = None
        try:
            async with self._client.stream(
                "POST",
                self._url(model, "streamGenerateContent"),
                params={"alt": "sse"},
                headers=self._headers(),
                json=body,
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    self._raise_for_status(resp)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    chunk = json.loads(payload)
                    cand = (chunk.get("candidates") or [{}])[0]
                    text = self._text((cand.get("content") or {}).get("parts") or [])
                    if text:
                        yield text
        except httpx.TransportError as exc:  # a timeout is one too
            failed = _unreachable(exc, "stream")
        if failed is not None:
            raise failed  # outside the except block: no __context__ (R14 security review LOW-1)


def _unreachable(exc: httpx.TransportError, what: str) -> LLMUnreachable:
    """Fixed words for a Gemini request that got no answer: the class name, never the httpx
    error itself (its request carries the key header)."""
    if isinstance(exc, httpx.TimeoutException):
        return LLMUnreachable(f"Gemini {what} timed out")
    return LLMUnreachable(f"Gemini connection error: {type(exc).__name__}")
