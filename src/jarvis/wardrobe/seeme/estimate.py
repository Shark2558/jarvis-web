# src/jarvis/wardrobe/seeme/estimate.py
"""R13.1 Part C: the ₹ of a "See it on me" picture (docs/plans/r13-1-try-on.md D13.2, D13.6, D15;
plan review M1). Dollars stay inside `jarvis.llm` and this arithmetic: every figure out of here is
₹ with GST (`billing.spend.with_tax`, `tryon_tax_pct`).

- `figures(provider, garments=, rate=, tax_pct=)`: the TYPICAL ₹ (the provider's typical for the
  new garment and his pieces, rounded UP to 10 paise: ≈ ₹8.9) and the HOLD (the worst the request
  allows, `MAX_GARMENTS` and `maxOutputTokens`, to the paise: ₹11.22 at ₹95.24).
- `settled_usd` / `settled_inr`: what an answer's usage costs (`llm.tryon.cost_usd`); None when
  the provider's (model, location) isn't priced (then the hold is settled, the safe side).
- `rate_of(billing, s)`: the day's rate (`billing.fx`), else `usd_inr_rate` (₹95.24).
- Words: `rupees` ("₹54.3"), `approx` ("₹9"), `about` ("About ₹9 with GST"), `up10`.
- `quote(...)`: the estimate the console shows before the press (`http.Estimate`).
"""

from __future__ import annotations

import math
from typing import Any

from jarvis.billing.spend import with_tax
from jarvis.llm.tryon import MAX_GARMENTS, TryOnProvider, TryOnUsage, cost_usd, price_of
from jarvis.logging import get_logger
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.tryon.http import Estimate, NewGarment, NotSent, SentPiece

log = get_logger(__name__)


class Figures:
    """The typical ₹ (shown, `inr_shown` is checked against it) and the hold (reserved)."""

    __slots__ = ("hold_inr", "rate", "typical_inr")

    def __init__(self, typical_inr: float, hold_inr: float, rate: float) -> None:
        self.typical_inr, self.hold_inr, self.rate = typical_inr, hold_inr, rate


def up10(inr: float) -> float:
    """Rounded UP to 10 paise (8.895 -> 8.9; 8.9 stays 8.9)."""
    return math.ceil(round(inr * 10, 6)) / 10


def rupees(inr: float) -> str:
    """ "₹300", "₹54.3", "₹0": to 10 paise, no trailing ".0"."""
    shown = round(float(inr) + 1e-9, 1)
    return f"₹{int(shown)}" if shown == int(shown) else f"₹{shown:.1f}"


def approx(inr: float) -> str:
    """ "₹9" for 8.52 or 8.9 (the next whole rupee); under ₹1 to 10 paise."""
    if inr >= 1:
        return f"₹{math.ceil(round(inr, 6))}"
    return f"₹{up10(inr):.1f}"


def about(inr: float) -> str:
    return f"About {approx(inr)} with GST"


def _rate(rate: float) -> float:
    if not isinstance(rate, int | float) or not math.isfinite(rate) or rate <= 0:
        raise ValueError("a rate is a positive number of rupees a dollar")
    return float(rate)


def figures(provider: TryOnProvider, *, garments: int, rate: float, tax_pct: int) -> Figures:
    r = _rate(rate)
    typical_usd, _ = provider.estimate(garments)
    _, worst_usd = provider.estimate(MAX_GARMENTS)
    typical = up10(with_tax(typical_usd * r, tax_pct))
    hold = with_tax(worst_usd * r, tax_pct)
    return Figures(typical, max(hold, typical), r)


def settled_usd(provider: TryOnProvider, usage: TryOnUsage | None) -> float | None:
    if usage is None:
        return None
    d = provider.describe()
    try:
        price = price_of(d.model, d.location)
    except KeyError:
        return None
    return cost_usd(price, usage)


def settled_inr(
    provider: TryOnProvider, usage: TryOnUsage | None, *, rate: float, tax_pct: int
) -> float | None:
    usd = settled_usd(provider, usage)
    return None if usd is None else with_tax(usd * _rate(rate), tax_pct)


async def rate_of(billing: Any, fallback: float) -> float:
    """The day's ₹ a dollar (FxRates never raises); the setting when there is no billing."""
    fx = getattr(billing, "fx", None)
    if fx is None:
        return fallback
    try:
        got = float((await fx.rate()).inr_per_usd)
    except Exception as exc:  # noqa: BLE001 - FxRates never raises; belt and braces
        log.warning("see it on me: no rate", extra={"error": type(exc).__name__})
        return fallback
    return got if math.isfinite(got) and got > 0 else fallback


def confirm_words(garment: str, mine: list[str], *, typical: float, spent: float, cap: int) -> str:
    """ "Make 1 picture of you in a new navy shirt, with your charcoal trousers? About ₹9 with
    GST. ₹54.3 of ₹300 used this month." """
    listed = f", with your {' and '.join(mine)}" if mine else ""
    return texts.CONFIRM.format(
        garment=garment, mine=listed, about=about(typical), spent=rupees(spent), cap=rupees(cap)
    )


def quote(
    fig: Figures, *, tax_pct: int, garment: NewGarment, garment_words: str,
    sent: tuple[SentPiece, ...], not_sent: tuple[NotSent, ...], spent: float, held: float,
    cap: int, room: float | None,
) -> Estimate:  # fmt: skip
    return Estimate(
        typical_inr=fig.typical_inr, hold_inr=fig.hold_inr, tax_pct=tax_pct, sent=sent,
        not_sent=not_sent, cap_left_inr=round(max(0.0, cap - spent - held), 2),
        limit_room_inr=None if room is None else round(max(0.0, room), 2), garment=garment,
        words=confirm_words(
            garment_words, [p.words for p in sent], typical=fig.typical_inr, spent=spent, cap=cap
        ),
    )  # fmt: skip


__all__ = [
    "Figures",
    "about",
    "approx",
    "confirm_words",
    "figures",
    "quote",
    "rate_of",
    "rupees",
    "settled_inr",
    "settled_usd",
    "up10",
]
