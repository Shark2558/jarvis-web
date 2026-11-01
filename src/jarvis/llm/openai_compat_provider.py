# src/jarvis/llm/openai_compat_provider.py
"""Generic OpenAI-compatible chat-completions provider (httpx; no vendor SDK).

One implementation covers Groq, OpenRouter, Ollama, LM Studio, vLLM, Together and most
others: they all speak `POST {base_url}/chat/completions`. The API key is optional (local
servers have none). Tool calling uses the OpenAI `tools` / `tool_calls` / `role: tool` shape.

`Effort` is not mapped: there is no portable field for it across these servers.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMAuthError,
    LLMError,
    LLMTransientError,
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

_STOP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_s: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key or None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    # ---- request building ----------------------------------------------------------------

    @staticmethod
    def _assistant_message(blocks: list[Any]) -> dict[str, Any]:
        text = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))
        calls = [
            {
                "id": b.id,
                "type": "function",
                "function": {"name": b.name, "arguments": json.dumps(b.arguments)},
            }
            for b in blocks
            if isinstance(b, ToolCall)
        ]
        msg: dict[str, Any] = {"role": "assistant", "content": text or None}
        if calls:
            msg["tool_calls"] = calls
        return msg

    @classmethod
    def _messages(
        cls, system: str, system_dynamic: str | None, messages: list[ChatMessage]
    ) -> list[dict[str, Any]]:
        sys_text = system + (f"\n\n{system_dynamic}" if system_dynamic else "")
        out: list[dict[str, Any]] = [{"role": "system", "content": sys_text}]
        for m in messages:
            if isinstance(m.content, str):
                out.append({"role": m.role.value, "content": m.content})
            elif m.role is Role.ASSISTANT:
                out.append(cls._assistant_message(m.content))
            else:  # user blocks: tool results first (must follow the tool_calls), then text
                for b in m.content:
                    if isinstance(b, ToolResultBlock):
                        out.append(
                            {"role": "tool", "tool_call_id": b.tool_use_id, "content": b.content}
                        )
                text = "\n".join(b.text for b in m.content if isinstance(b, TextBlock))
                if text:
                    out.append({"role": "user", "content": text})
        return out

    def _body(
        self,
        *,
        system: str,
        system_dynamic: str | None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        tools: list[ToolSpec] | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": self._messages(system, system_dynamic, messages),
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
        if stream:
            body["stream"] = True
        return body

    def _headers(self) -> dict[str, str]:
        h = {"content-type": "application/json"}
        if self._key:
            h["authorization"] = f"Bearer {self._key}"
        return h

    # ---- response handling ---------------------------------------------------------------

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "***") if self._key else text

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            err = resp.json().get("error", {})
            detail = str(err.get("message", err) if isinstance(err, dict) else err)[:300]
        except Exception:  # noqa: BLE001
            detail = ""
        msg = self._redact(f"OpenAI-compatible HTTP {resp.status_code}: {detail}")
        if resp.status_code in (401, 403):
            raise LLMAuthError(msg)
        if resp.status_code in (408, 429) or resp.status_code >= 500:
            raise LLMTransientError(msg)
        raise LLMError(msg)

    @staticmethod
    def _tool_calls(message: dict[str, Any]) -> list[ToolCall]:
        out: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                if not isinstance(args, dict):
                    args = {}
            except (json.JSONDecodeError, TypeError, ValueError):
                log.warning("model returned non-JSON tool arguments; using {}")
                args = {}
            out.append(
                ToolCall(
                    id=str(tc.get("id") or fn.get("name")), name=fn.get("name", ""), arguments=args
                )
            )
        return out

    @staticmethod
    def _usage(u: dict[str, Any]) -> Usage:
        return Usage(
            input_tokens=int(u.get("prompt_tokens", 0)),
            output_tokens=int(u.get("completion_tokens", 0)),
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
        t0 = time.perf_counter()
        body = self._body(
            system=system,
            system_dynamic=system_dynamic,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            tools=tools,
        )
        try:
            resp = await self._client.post(
                f"{self._base}/chat/completions", headers=self._headers(), json=body
            )
        except httpx.TimeoutException as exc:
            raise LLMTransientError("OpenAI-compatible request timed out") from exc
        except httpx.TransportError as exc:
            raise LLMTransientError(f"connection error: {type(exc).__name__}") from exc
        self._raise_for_status(resp)
        try:
            data = resp.json()
        except ValueError as exc:  # HTML from a reverse proxy, wrong base URL, …
            raise LLMError("OpenAI-compatible server returned non-JSON (check base URL)") from exc
        if not isinstance(data, dict):
            raise LLMError("OpenAI-compatible server returned an unexpected body")
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("OpenAI-compatible server returned no answer (empty choices)")
        choice = choices[0]
        message = choice.get("message") or {}
        usage = self._usage(data.get("usage") or {})
        latency_ms = int((time.perf_counter() - t0) * 1000)
        reason = choice.get("finish_reason")
        completion = Completion(
            text=message.get("content") or "",
            tool_calls=self._tool_calls(message),
            model=model,
            provider=self.name,
            usage=usage,
            stop_reason=_STOP.get(reason, reason),
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

    async def stream(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        usage: StreamUsage | None = None,  # not filled (unpriced servers): the caller estimates
    ) -> AsyncIterator[str]:
        body = self._body(
            system=system,
            system_dynamic=system_dynamic,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            tools=None,
            stream=True,
        )
        try:
            async with self._client.stream(
                "POST", f"{self._base}/chat/completions", headers=self._headers(), json=body
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    self._raise_for_status(resp)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except ValueError as exc:
                        raise LLMError("OpenAI-compatible stream sent a non-JSON line") from exc
                    delta = ((chunk.get("choices") or [{}])[0]).get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield text
        except httpx.TimeoutException as exc:
            raise LLMTransientError("OpenAI-compatible stream timed out") from exc
        except httpx.TransportError as exc:
            raise LLMTransientError(f"connection error: {type(exc).__name__}") from exc
