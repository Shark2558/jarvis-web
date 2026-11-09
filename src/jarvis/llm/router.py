# src/jarvis/llm/router.py
"""ModelRouter: callers ask for a *tier*, the router picks the model and handles degradation.

Graceful degradation (architecture tenet): a transient failure on STRONG falls back to
BALANCED, BALANCED to FAST. FAST failing is terminal — the caller decides what to do.

R1 D12: a cloud that is UNREACHABLE (`LLMUnreachable`: no connection, timeout, 5xx) is different —
every tier is down, so with a ready fallback brain (the owner's laptop) the same call goes there
instead of down a tier. 429 / auth / 4xx never do. A stream switches only before its first text;
never mid-stream. After a cloud miss answered by the laptop, the next two minutes skip the cloud
(`Breaker`), then one cloud try.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from jarvis.config import LLMBackend, Settings
from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMAuthError,
    LLMError,
    LLMOutOfCredit,
    LLMProvider,
    LLMTransientError,
    LLMUnreachable,
    StreamUsage,
    ToolSpec,
)
from jarvis.llm.fallback import FALLBACK_REFUSED_TEXT, Breaker, FallbackBrain, FallbackFailed
from jarvis.llm.gemini_provider import GeminiProvider
from jarvis.llm.mock_provider import MockProvider
from jarvis.logging import get_logger

log = get_logger(__name__)

GUARD_REFRESH_S = 5.0  # how often the router re-reads the persisted no-AI switch
NO_AI_REFUSAL = "The AI is switched off (no-AI mode): no model was called."


class BrainOff(LLMError):
    """R4 D7: a model call was attempted while `brain_mode == "none"`. Defence in depth: the brain
    routes around the model in that mode, and this makes a stray call fail loudly instead of
    spending money. Not transient and not an outage: neither the laptop fallback nor a lower
    tier is tried."""


class ModelTier(StrEnum):
    FAST = "fast"  # classification, routing, extraction — Haiku-class
    BALANCED = "balanced"  # everyday conversation — Sonnet-class
    STRONG = "strong"  # planning, multi-step reasoning — Opus-class


# no_credit (R5.1 I1): the vendor answered that the account has no credit left to bill
BrainState = Literal["unknown", "ok", "busy", "unreachable", "refused", "odd", "no_credit"]


@dataclass(frozen=True)
class BrainHealth:
    """What the router already knows about the cloud brain: how its last real call ended and
    whether the laptop is covering for it. Reading it costs nothing (no call, no tokens)."""

    state: BrainState
    on_laptop: bool


_DEGRADE_TO: dict[ModelTier, ModelTier | None] = {
    ModelTier.STRONG: ModelTier.BALANCED,
    ModelTier.BALANCED: ModelTier.FAST,
    ModelTier.FAST: None,
}


class ModelRouter:
    def __init__(
        self,
        provider: LLMProvider,
        tiers: dict[ModelTier, str],
        fallback: FallbackBrain | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        blocked: Callable[[], bool] | None = None,
    ) -> None:
        self.provider = provider
        self._tiers = tiers
        self.fallback = fallback
        self._breaker = Breaker(clock=clock)
        self._last: BrainState = "unknown"  # R4 B: how the last real call ended (health())
        self._blocked: Callable[[], bool] | None = blocked  # R4 D7: the no-AI switch
        self._refresh: Callable[[], Awaitable[None]] | None = None  # re-reads the switch
        self._clock = clock
        self._refreshed_at = float("-inf")

    def bind_blocked(
        self, blocked: Callable[[], bool], refresh: Callable[[], Awaitable[None]] | None = None
    ) -> None:
        """R4 D7: `Brain` hands every router the no-AI switch once, at construction. While it
        reads True a model call raises `BrainOff`. `refresh` re-reads the persisted switch; the
        router calls it at most every `GUARD_REFRESH_S` before any provider call (I2 F1)."""
        self._blocked, self._refresh = blocked, refresh

    def is_blocked(self) -> bool:
        """True while the AI is switched off: background callers skip instead of calling."""
        return self._blocked is not None and self._blocked()

    async def _ensure_allowed(self) -> None:
        """Refresh the switch (at most every `GUARD_REFRESH_S`), then refuse while it is off. A
        refresh that fails is a refusal: when we cannot tell, no model is called."""
        if await self.blocked_now():
            raise BrainOff(NO_AI_REFUSAL)

    async def blocked_now(self) -> bool:
        """`is_blocked` after a (rate-limited) re-read of the persisted switch: what background
        callers (brief summary, recall sweep) ask before a call."""
        now = self._clock()
        if self._refresh is not None and now - self._refreshed_at >= GUARD_REFRESH_S:
            try:
                await self._refresh()
            except Exception as exc:  # noqa: BLE001 - fail closed
                log.error("no-AI switch unreadable", extra={"error": type(exc).__name__})
                return True
            self._refreshed_at = now
        return self.is_blocked()

    @classmethod
    def from_settings(cls, s: Settings, provider: LLMProvider | None = None) -> ModelRouter:
        if provider is None:
            provider = build_provider(s)
        return cls(provider, tiers_for(s, s.llm_backend))

    def resolve(self, tier: ModelTier) -> str:
        return self._tiers[tier]

    def health(self) -> BrainHealth:
        """The cloud brain's state from the last real call; never makes a call itself."""
        return BrainHealth(state=self._last, on_laptop=self._breaker.is_open())

    def _note_failure(self, exc: LLMError) -> None:
        if isinstance(exc, LLMUnreachable):
            self._last = "unreachable"
        elif isinstance(exc, LLMAuthError):
            self._last = "refused"
        elif isinstance(exc, LLMOutOfCredit):
            self._last = "no_credit"
        elif isinstance(exc, LLMTransientError):
            self._last = "busy"
        else:
            self._last = "odd"

    async def _fallback_ready(self) -> bool:
        if self.fallback is None:
            return False
        try:
            return await self.fallback.ready()
        except Exception as exc:  # noqa: BLE001 — a broken fallback must not break the cloud path
            log.warning("fallback brain check failed", extra={"error": type(exc).__name__})
            return False

    async def _cloud_ok(self) -> None:
        self._last = "ok"
        self._breaker.reset()
        if self.fallback is None:
            return
        try:
            await self.fallback.cloud_ok()
        except Exception as exc:  # noqa: BLE001 — bookkeeping only
            log.warning("fallback cloud_ok failed", extra={"error": type(exc).__name__})

    async def _offline_complete(self, cause: LLMError | None, **kw: Any) -> Completion | None:
        """The fallback's answer, or None when it is off or (with no `cause`) failed. With a
        `cause` (the cloud's error) a failed laptop raises `FallbackFailed` instead."""
        if self.fallback is None or not await self._fallback_ready():
            return None
        try:
            done = await self.fallback.complete(**kw)
        except Exception as exc:  # noqa: BLE001 — anything the laptop does wrong = "no answer"
            log.warning("fallback brain failed", extra={"error": type(exc).__name__})
            self._breaker.reset()
            if cause is None:
                return None
            raise _failed(exc) from cause
        if cause is not None:  # a cloud miss opens the window; answers inside it don't extend it
            self._breaker.trip()
        return done

    async def complete(
        self,
        *,
        tier: ModelTier,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None = None,
        tools: list[ToolSpec] | None = None,
        allow_degrade: bool = True,
    ) -> Completion:
        await self._ensure_allowed()
        local = {
            "tier": tier,
            "system": system,
            "system_dynamic": system_dynamic,
            "messages": messages,
            "max_tokens": max_tokens,
            "effort": effort,
            "tools": tools,
        }
        tried_laptop = False
        if self._breaker.is_open():  # a recent miss: straight to the laptop, cloud as a last resort
            if await self._fallback_ready():
                done = await self._offline_complete(None, **local)
                if done is not None:
                    return done
                tried_laptop = True  # the laptop was really asked and did not answer
            else:
                self._breaker.reset()  # off / not configured: nothing to hold the cloud back
        current: ModelTier | None = tier
        while current is not None:
            model = self.resolve(current)
            try:
                result = await self.provider.complete(
                    system=system,
                    system_dynamic=system_dynamic,
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    effort=effort,
                    tools=tools,
                )
            except LLMUnreachable as exc:
                self._note_failure(exc)
                # every tier is down: the laptop (if ready), else degrade as before
                if tried_laptop:
                    raise FallbackFailed() from exc
                done = await self._offline_complete(exc, **local)
                if done is not None:
                    return done
                current = self._degrade(current, exc, allow_degrade)
            except LLMTransientError as exc:
                self._note_failure(exc)
                current = self._degrade(current, exc, allow_degrade)
            except LLMError as exc:  # auth / other: not retried, but remembered
                self._note_failure(exc)
                raise
            else:
                await self._cloud_ok()
                return result
        raise AssertionError("unreachable")

    @staticmethod
    def _degrade(current: ModelTier, exc: LLMError, allow_degrade: bool) -> ModelTier:
        nxt = _DEGRADE_TO[current] if allow_degrade else None
        if nxt is None:
            raise exc
        log.warning(
            "tier degraded after transient error",
            extra={"from": current.value, "to": nxt.value, "error": str(exc)[:200]},
        )
        return nxt

    async def stream(
        self,
        *,
        tier: ModelTier,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None = None,
        usage: StreamUsage | None = None,
    ) -> AsyncIterator[str]:
        await self._ensure_allowed()
        # No mid-stream degradation: once tokens are flowing to a TTS engine we cannot restart.
        # The laptop takes over only when the cloud stream failed BEFORE its first text.
        local = {
            "tier": tier,
            "system": system,
            "system_dynamic": system_dynamic,
            "messages": messages,
            "max_tokens": max_tokens,
            "effort": effort,
            "usage": usage,
        }
        tried_laptop = False
        if self._breaker.is_open() and await self._fallback_ready():
            try:
                async for delta in self._local_stream(local, miss=False):
                    yield delta
                return
            except _LaptopSilent:
                tried_laptop = True  # nothing reached the caller: give the cloud a try
        elif self._breaker.is_open():
            self._breaker.reset()  # the fallback went off / away: nothing to hold the cloud back
        started = False
        try:
            async for delta in self.provider.stream(
                system=system,
                system_dynamic=system_dynamic,
                messages=messages,
                model=self.resolve(tier),
                max_tokens=max_tokens,
                effort=effort,
                usage=usage,
            ):
                started = True
                yield delta
        except LLMUnreachable as exc:
            self._note_failure(exc)
            if tried_laptop:
                raise FallbackFailed() from exc
            if started or not await self._fallback_ready():
                raise
            try:
                async for delta in self._local_stream(local, miss=True):
                    yield delta
            except _LaptopSilent as silent:
                raise _failed(silent.args[0]) from exc
            return
        except LLMError as exc:  # busy / auth / other: propagates, but remembered
            self._note_failure(exc)
            raise
        await self._cloud_ok()

    async def _local_stream(self, kw: dict[str, Any], *, miss: bool) -> AsyncIterator[str]:
        """The laptop's stream. Raises `_LaptopSilent` if it fails before its first text; a failure
        after that propagates (text already reached the caller)."""
        assert self.fallback is not None
        got = False
        try:
            async for delta in self.fallback.stream(**kw):
                got = True
                yield delta
        except Exception as exc:
            if got:
                raise
            log.warning("fallback stream failed", extra={"error": type(exc).__name__})
            self._breaker.reset()
            raise _LaptopSilent(exc) from exc
        if miss:
            self._breaker.trip()


def _failed(laptop_error: Exception) -> FallbackFailed:
    """The friendly error for 'cloud unreachable and the laptop gave no answer'."""
    if isinstance(laptop_error, LLMAuthError):
        return FallbackFailed(FALLBACK_REFUSED_TEXT)
    return FallbackFailed()


class _LaptopSilent(Exception):
    """The fallback brain gave no text (internal to the router)."""


def build_provider(s: Settings) -> LLMProvider:
    if s.llm_backend is LLMBackend.MOCK:
        return MockProvider()
    if s.llm_backend is LLMBackend.ANTHROPIC:
        if s.anthropic_api_key is None:
            raise RuntimeError("JARVIS_ANTHROPIC_API_KEY is not set")
        return AnthropicProvider(
            s.anthropic_api_key.get_secret_value(),
            timeout_s=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
        )
    if s.llm_backend is LLMBackend.GEMINI:
        if s.gemini_api_key is None:
            raise RuntimeError("JARVIS_GEMINI_API_KEY is not set")
        return GeminiProvider(s.gemini_api_key.get_secret_value(), timeout_s=s.llm_timeout_s)
    if s.llm_backend is LLMBackend.OPENAI_COMPAT:
        from jarvis.llm.openai_compat_provider import OpenAICompatProvider

        if not s.openai_compat_configured:
            raise RuntimeError("JARVIS_OPENAI_COMPAT_BASE_URL / _MODEL_BALANCED are not set")
        assert s.openai_compat_base_url is not None
        return OpenAICompatProvider(
            s.openai_compat_base_url,
            api_key=s.openai_compat_api_key.get_secret_value() if s.openai_compat_api_key else None,
            timeout_s=s.llm_timeout_s,
        )
    raise ValueError(f"unknown llm backend: {s.llm_backend}")


def tiers_for(s: Settings, backend: LLMBackend) -> dict[ModelTier, str]:
    """Tier → model id map for one backend. Skills ask for tiers, never model ids."""
    if backend is LLMBackend.GEMINI:
        return {
            ModelTier.FAST: s.gemini_model_fast,
            ModelTier.BALANCED: s.gemini_model_balanced,
            ModelTier.STRONG: s.gemini_model_strong,
        }
    if backend is LLMBackend.OPENAI_COMPAT:
        balanced = s.openai_compat_model_balanced or "default"
        return {
            ModelTier.FAST: s.openai_compat_model_fast or balanced,
            ModelTier.BALANCED: balanced,
            ModelTier.STRONG: s.openai_compat_model_strong or balanced,
        }
    return {
        ModelTier.FAST: s.model_fast,
        ModelTier.BALANCED: s.model_balanced,
        ModelTier.STRONG: s.model_strong,
    }
