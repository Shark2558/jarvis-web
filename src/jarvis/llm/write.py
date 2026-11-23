# src/jarvis/llm/write.py
"""R6.3 D1 (docs/plans/r6-3-book-content.md): the Build Book writer's ONE model call, by tier.

`write_text` streams one page from the router's own provider at `router.resolve(tier)`. Unlike
the router's `complete`/`stream` it never asks the laptop brain and never changes tier; it refuses
under No-AI (`BrainOff`) and while the breaker is open (`WriterUnavailable("cloud_down")`); it
streams through the provider's `no_retry()` view (M1). Nothing received -> `WriterUnavailable`
(the call never left: release its hold); a stream that broke after it started, or our own
`timeout_s` -> a `Written` with `complete=False` (settle at its usage, D8); a length stop is not
complete either (L10). Prices only through `jarvis.llm.pricing`: the Book reads no model id or price
(`estimate_usd`, `worst_usd`, `offered`, `paid`, `model_of`). No tools are ever sent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from jarvis.llm import base, pricing
from jarvis.llm.brains import BrainSpec
from jarvis.llm.router import NO_AI_REFUSAL, BrainOff, ModelRouter, ModelTier

Why = Literal["cloud_down", "busy", "refused", "no_credit", "declined", "no_answer"]
LENGTH_STOPS = frozenset({"max_tokens", "MAX_TOKENS"})
MTOK = 1_000_000


class WriterUnavailable(base.LLMError):
    """The call did not happen (nothing was received): the page waits and its hold is released."""

    def __init__(self, why: Why) -> None:
        super().__init__(f"the writer's brain is unavailable ({why})")
        self.why: Why = why


@dataclass(frozen=True)
class Written:
    text: str
    model: str
    provider: str
    tier: ModelTier
    usage: base.Usage
    cost_usd: float
    seconds: float
    complete: bool
    stop_reason: str | None


_WHY: tuple[tuple[type[base.LLMError], Why], ...] = (
    (base.LLMUnreachable, "cloud_down"),
    (base.LLMTransientError, "busy"),
    (base.LLMAuthError, "refused"),
    (base.LLMOutOfCredit, "no_credit"),
    (base.LLMDeclined, "declined"),
)


def _why(exc: base.LLMError) -> Why:
    return next((why for kind, why in _WHY if isinstance(exc, kind)), "no_answer")


def _no_retry(provider: base.LLMProvider) -> base.LLMProvider:
    view = getattr(provider, "no_retry", None)
    return view() if callable(view) else provider


async def write_text(
    router: ModelRouter,
    *,
    tier: ModelTier,
    system: str,
    system_dynamic: str | None,
    messages: list[base.ChatMessage],
    max_tokens: int,
    timeout_s: float,
    clock: Callable[[], float] | None = None,
) -> Written:
    if await router.blocked_now():
        raise BrainOff(NO_AI_REFUSAL)
    if router.health().on_laptop:
        raise WriterUnavailable("cloud_down")
    now = clock or asyncio.get_running_loop().time
    model, provider, usage = router.resolve(tier), _no_retry(router.provider), base.StreamUsage()
    parts: list[str] = []
    started, cut = now(), False
    try:
        async with asyncio.timeout(timeout_s):
            async for delta in provider.stream(
                system=system,
                system_dynamic=system_dynamic,
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                usage=usage,
            ):
                parts.append(delta)
    except TimeoutError:
        cut = True  # our own deadline: the call left and may be billed
    except base.LLMError as exc:
        if not parts and not usage.reported:
            raise WriterUnavailable(_why(exc)) from None
        cut = True  # it started, then broke: settle at what it used
    text = "".join(parts)
    sent = len(system) + len(system_dynamic or "") + sum(len(m.text()) for m in messages)
    used = pricing.stream_usage(usage, input_chars=sent, output_chars=len(text))
    stop = None if cut else usage.stop_reason
    cost, took = pricing.cost_usd(model, used), max(0.0, now() - started)
    name, whole = getattr(router.provider, "name", ""), not cut and stop not in LENGTH_STOPS
    return Written(text, model, name, tier, used, cost, took, whole, stop)


MAKERS = {"anthropic": "Anthropic", "gemini": "Google"}  # the Book names no vendor itself (L3)


def maker(spec: BrainSpec) -> str:
    return MAKERS.get(getattr(spec.provider, "name", ""), spec.label)


def model_of(spec: BrainSpec, tier: ModelTier = ModelTier.BALANCED) -> str:
    return spec.tiers[tier]


def paid(spec: BrainSpec, tier: ModelTier = ModelTier.BALANCED) -> bool:
    return pricing.is_paid(model_of(spec, tier))


def offered(spec: BrainSpec, tier: ModelTier = ModelTier.BALANCED) -> bool:
    """M2: priced, and paid or the free (training) tier: never Rs 0 while a vendor bills."""
    model = model_of(spec, tier)
    return pricing.is_priced(model) and (pricing.is_paid(model) or spec.trains_on_content)


def _usd(spec: BrainSpec, tier: ModelTier, tokens: tuple[int, int, int], worst: bool) -> float:
    price = pricing.PRICES.get(model_of(spec, tier))
    if price is None:
        return 0.0  # unpriced: never offered (M2)
    sys_price = price.cache_write_per_mtok
    sys_price = max(price.input_per_mtok, sys_price) if worst else sys_price
    sent, system, out = tokens
    usd = sent * price.input_per_mtok + system * sys_price + out * price.output_per_mtok
    return round(usd / MTOK, 6)


def estimate_usd(
    spec: BrainSpec, tier: ModelTier, in_tokens: int, out_tokens: int, *, system_tokens: int = 0
) -> float:
    """A call's price: input, the fixed system prompt at the cache-write price, output."""
    return _usd(spec, tier, (in_tokens, system_tokens, out_tokens), worst=False)


def worst_usd(
    spec: BrainSpec, tier: ModelTier, in_cap: int, out_cap: int, *, system_cap: int = 0
) -> float:
    """D8's hold (an upper bound): the system prompt at the dearer of input and cache-write."""
    return _usd(spec, tier, (in_cap, system_cap, out_cap), worst=True)
