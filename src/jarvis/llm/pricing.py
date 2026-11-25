# src/jarvis/llm/pricing.py
"""Token → USD metering. Cross-cutting (observability: token & cost metering).

Prices are USD per million tokens (base tier, Oct 2026).
Source: https://platform.claude.com/docs/en/about-claude/pricing

`PRICES` is the free-tier table: Gemini at $0. When the deployment's Gemini key has billing
(`gemini_paid_tier`, R6.4 D9), `BrainRegistry.from_settings` calls `use_gemini_paid_tier(True)`
and Gemini models are priced from `GEMINI_PAID_PRICES` instead; `price_of` reads the table in force.
A model with no price (`price_unknown`) still meters at $0 here, logged once; billing counts its
tokens as "price unknown" and the owner's limit counts them at the `dearest` known price.
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
    # With gemini_paid_tier on, GEMINI_PAID_PRICES below replaces these.
    "gemini-3.8-flash": Price(0.0, 0.0, 0.0, 0.0),
    "gemini-3.6-flash": Price(0.0, 0.0, 0.0, 0.0),
    "gemini-3.5-flash-lite": Price(0.0, 0.0, 0.0, 0.0),
    "gemini-3.1-flash-lite": Price(0.0, 0.0, 0.0, 0.0),
    "mock": Price(0.0, 0.0, 0.0, 0.0),
}

# Gemini's paid ("Standard") tier, USD per 1M tokens, from Google's published price list
# https://ai.google.dev/gemini-api/docs/pricing, read 2026-11-25 (`GEMINI_PAID_SOURCE` and
# `GEMINI_PAID_AS_OF`; the Book's cost table shows that day with the prices). None of these four
# has prompt-length bands. 3.8 Flash and 3.6 Flash list $0.75 input / $3.75 output / $0.075 cache
# through 31 Dec 2026 and $1.50 / $7.50 / $0.15 from 1 Jan 2027: the higher (later) price is used,
# the worst case, so December 2026 reads high, never low. Flash-Lite: the text / image / video
# input price (JARVIS sends no audio to the chat brain). Google bills no per-token cache write
# (stored caches are billed per hour; JARVIS keeps none), so cache_write is the input price, and
# the Gemini provider never reports one.
GEMINI_PAID_PRICES: dict[str, Price] = {
    "gemini-3.8-flash": Price(1.50, 7.50, 0.15, 1.50),
    "gemini-3.6-flash": Price(1.50, 7.50, 0.15, 1.50),
    "gemini-3.5-flash-lite": Price(0.30, 2.50, 0.03, 0.30),
    "gemini-3.1-flash-lite": Price(0.25, 1.50, 0.025, 0.25),
}
GEMINI_PAID_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"
GEMINI_PAID_AS_OF = "2026-11-25"  # the day GEMINI_PAID_PRICES was read from GEMINI_PAID_SOURCE
# Providers that call no vendor: the deterministic test/dev mock and the owner's own laptop
# (`local_brain`). Their models are never "price unknown".
FREE_PROVIDERS: frozenset[str] = frozenset({"mock", "local_brain"})

_PAID_TABLE: dict[str, Price] = {**PRICES, **GEMINI_PAID_PRICES}
_table: dict[str, Price] = PRICES
_warned: set[str] = set()


def use_gemini_paid_tier(on: bool) -> None:
    """Price Gemini at Google's paid tier (`on`) or the free tier's $0. One deployment has one
    Gemini key, so this is process-wide; `BrainRegistry.from_settings` sets it from
    `gemini_paid_tier`."""
    global _table
    _table = _PAID_TABLE if on else PRICES


def gemini_paid_tier() -> bool:
    return _table is _PAID_TABLE


def price_of(model: str) -> Price | None:
    """`model`'s price in the table in force, None when it has none."""
    return _table.get(model)


def is_priced(model: str) -> bool:
    """True when `model` has a price-table entry (possibly $0). False means `cost_usd` would
    meter it at $0 without knowing: say "cost unknown", never "free"."""
    return model in _table


def price_unknown(model: str, provider: str = "") -> bool:
    """True when a reply from `model` costs an amount JARVIS can't tell: no price, and not from a
    provider that calls no vendor (`FREE_PROVIDERS`). Billing counts it as "price unknown"."""
    return not is_priced(model) and provider not in FREE_PROVIDERS


# R6.4 I1: one call with no known price whose tokens nobody reported (a background caller passes
# billing a cost only; a vendor that reports no usage) is counted for the limit as this many
# tokens at the dearest known price, an upper estimate and never ₹0. JARVIS's own background
# prompts are capped at 12,000 characters (about 3,000 tokens; a picture or the Book's context
# adds some) and ask for at most 700 tokens back.
UNREPORTED_CALL = Usage(input_tokens=8_000, output_tokens=1_000)


def dearest() -> Price:
    """The dearest known price of each kind of token in the table in force: what the owner's limit
    counts a "price unknown" reply at (an upper estimate, never ₹0; a vendor dearer than every
    model here would still be counted low)."""
    table = _table.values()
    return Price(
        input_per_mtok=max(p.input_per_mtok for p in table),
        output_per_mtok=max(p.output_per_mtok for p in table),
        cache_read_per_mtok=max(p.cache_read_per_mtok for p in table),
        cache_write_per_mtok=max(p.cache_write_per_mtok for p in table),
    )


def is_paid(model: str) -> bool:
    """True when `model` is in the price table in force with a price above zero. A model with no
    price is not "paid" here: the limit gate asks `price_unknown` for it (`metered_brain`)."""
    p = price_of(model)
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
    price = price_of(model)
    if price is None:
        if model not in _warned:
            log.warning("no price table entry; metering at $0", extra={"model": model})
            _warned.add(model)
        return 0.0
    return priced_at(price, usage)


def priced_at(price: Price, usage: Usage) -> float:
    """`usage` at `price`, in USD."""
    m = 1_000_000
    return round(
        usage.input_tokens * price.input_per_mtok / m
        + usage.output_tokens * price.output_per_mtok / m
        + usage.cache_read_tokens * price.cache_read_per_mtok / m
        + usage.cache_write_tokens * price.cache_write_per_mtok / m,
        6,
    )
