# src/jarvis/llm/pricing.py
"""Token → USD metering. Cross-cutting (observability: token & cost metering).

Prices are USD per million tokens (base tier, Oct 2026). Unknown models meter at 0 and log
a warning so a new model never silently reports zero cost in prod dashboards.
Source: https://platform.claude.com/docs/en/about-claude/pricing
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.llm.base import StreamUsage, Usage
from jarvis.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float


# Cache reads: 10% of input on Haiku, 5% on Opus 5.5 / Sonnet 5.5. Cache writes: 1.25x input.
PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": Price(2.00, 10.00, 0.10, 2.50),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01, 0.125),
    # Gemini free tier is $0 ("free of charge" per ai.google.dev/gemini-api/docs/pricing, Oct 2026).
    # If gemini_paid_tier is enabled, add real prices here before relying on cost metering.
    "gemini-3.8-flash": Price(0.0, 0.0, 0.0, 0.0),
    "gemini-3.6-flash": Price(0.0, 0.0, 0.0, 0.0),
    "gemini-3.5-flash-lite": Price(0.0, 0.0, 0.0, 0.0),
    "gemini-3.1-flash-lite": Price(0.0, 0.0, 0.0, 0.0),
    "mock": Price(0.0, 0.0, 0.0, 0.0),
}

_warned: set[str] = set()


def is_priced(model: str) -> bool:
    """True when `model` has a price-table entry (possibly $0). False means `cost_usd` would
    meter it at $0 without knowing: say "cost unknown", never "free"."""
    return model in PRICES


def is_paid(model: str) -> bool:
    """True when `model` is in the price table with a price above zero: the only models the
    owner's monthly limit applies to (free and unpriced models are never blocked)."""
    p = PRICES.get(model)
    return p is not None and (
        p.input_per_mtok > 0
        or p.output_per_mtok > 0
        or p.cache_read_per_mtok > 0
        or p.cache_write_per_mtok > 0
    )


CHARS_PER_TOKEN = 4  # rough English average; used only when a provider reports no usage


def estimate_usage(input_chars: int, output_chars: int) -> Usage:
    """Token counts for a call whose provider reported none (a stream without usage events, a
    learning run cut short). An estimate, shown with "≈" like every rupee figure; it keeps a paid
    call from metering at 0. Streams use `stream_usage`, which prefers the vendor's counts."""
    per = CHARS_PER_TOKEN
    return Usage(
        input_tokens=-(-max(0, input_chars) // per), output_tokens=-(-max(0, output_chars) // per)
    )


def stream_usage(reported: StreamUsage, *, input_chars: int, output_chars: int) -> Usage:
    """What a streamed call is metered at: the vendor's own counts where they arrived (input and
    cache from the start event, output from the closing one); characters/4 for any part that did
    not, flagged `estimated`. A stream cut short bills at least the text that reached us."""
    guess = estimate_usage(input_chars, output_chars)
    if not reported.reported:
        return guess.model_copy(update={"estimated": True})
    output = reported.output_tokens or 0
    if not reported.final:  # the closing count never came: what we received is a floor
        output = max(output, guess.output_tokens)
    return Usage(
        input_tokens=reported.input_tokens or 0,
        output_tokens=output,
        cache_read_tokens=reported.cache_read_tokens,
        cache_write_tokens=reported.cache_write_tokens,
        estimated=not reported.final,
    )


def cost_usd(model: str, usage: Usage) -> float:
    price = PRICES.get(model)
    if price is None:
        if model not in _warned:
            log.warning("no price table entry; metering at $0", extra={"model": model})
            _warned.add(model)
        return 0.0
    m = 1_000_000
    return round(
        usage.input_tokens * price.input_per_mtok / m
        + usage.output_tokens * price.output_per_mtok / m
        + usage.cache_read_tokens * price.cache_read_per_mtok / m
        + usage.cache_write_tokens * price.cache_write_per_mtok / m,
        6,
    )
