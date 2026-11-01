# src/jarvis/llm/pricing.py
"""Token → USD metering. Cross-cutting (observability: token & cost metering).

Prices are USD per million tokens (base tier, Oct 2026). Unknown models meter at 0 and log
a warning so a new model never silently reports zero cost in prod dashboards.
Source: https://platform.claude.com/docs/en/about-claude/pricing
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.llm.base import Usage
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
