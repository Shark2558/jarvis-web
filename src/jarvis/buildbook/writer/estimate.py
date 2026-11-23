# src/jarvis/buildbook/writer/estimate.py
"""R6.3 D8 (L4, L6): what writing costs, in rupees, before anything is spent.

From the real packs' sizes (UTF-8 bytes) under three assumptions: low / mid / high = bytes / 4,
/ 3, / 2.5 a token in; 2,200 / 3,000 / 3,500 tokens out a page; 15 / 25 / 30 % of pages redrafted,
each redraft sending about 3,000 tokens more (the failed draft and its failures). The fixed system
prompt counts at the cache-write price. Prices only through `jarvis.llm.write` (the Book reads no
model id or price); the day's rate from billing. Shown as "about Rs <mid> (Rs <low>-<high>)":
"about" is the mid rounded by `model.about_inr`, the same rule everywhere. The hold (one call's
upper bound): `worst_usd` of the bytes sent / 2.5, the system prompt and `MAX_TOKENS` out.
The estimate's id is bound to every input, the release included (M5: a YES never carries).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence

import jarvis.llm.write as write
from jarvis.buildbook.writer.http import Estimate
from jarvis.buildbook.writer.model import (
    BYTES_PER_TOKEN_WORST,
    GST_NOTE,
    MAX_TOKENS,
    SYSTEM_TOKENS,
    RunKind,
    about_inr,
)
from jarvis.llm.brains import BrainSpec
from jarvis.llm.router import ModelTier

BAL = ModelTier.BALANCED
ASSUME: tuple[tuple[float, int, float], ...] = (
    (4.0, 2_200, 0.15),
    (3.0, 3_000, 0.25),
    (2.5, 3_500, 0.30),
)
REDRAFT_EXTRA_TOKENS = 3_000
CALL_SECONDS = (30, 50)  # a page call on the step (Estimate; the trial measures it, D5)


def price_of(spec: BrainSpec) -> float:
    """A fingerprint of the brain's balanced price (a million of each token kind), no literal."""
    return write.estimate_usd(spec, BAL, 1_000_000, 1_000_000, system_tokens=1_000_000)


def _page_usd(spec: BrainSpec, nbytes: int, per: float, out: int, frac: float) -> float:
    one = write.estimate_usd(spec, BAL, math.ceil(nbytes / per), out, system_tokens=SYSTEM_TOKENS)
    extra = write.estimate_usd(spec, BAL, REDRAFT_EXTRA_TOKENS, 0)
    return one * (1 + frac) + extra * frac


def page_inr(spec: BrainSpec, nbytes: int, rate: float) -> float:
    per, out, frac = ASSUME[1]
    return round(_page_usd(spec, nbytes, per, out, frac) * rate, 2)


def tokens_worst(sent_bytes: int) -> int:
    return math.ceil(max(0, sent_bytes) / BYTES_PER_TOKEN_WORST)


def hold_inr(spec: BrainSpec, sent_bytes: int, rate: float) -> float:
    usd = write.worst_usd(spec, BAL, tokens_worst(sent_bytes), MAX_TOKENS, system_cap=SYSTEM_TOKENS)
    return round(usd * rate, 2)


def _id(
    run: RunKind, spec: BrainSpec, sizes: Sequence[int], rate: float, cap: int, rid: str
) -> str:
    raw = json.dumps(
        [run, spec.id, list(sizes), price_of(spec), rate, ASSUME, cap, rid], sort_keys=True
    )
    return "we_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def estimate(
    *,
    run: RunKind,
    spec: BrainSpec,
    sizes: Sequence[int],
    rate: float,
    cap: int,
    release: str,
    brains: int = 1,
    sent_to: tuple[str, ...] = (),
) -> Estimate:
    """The estimate of writing pages of these pack sizes with `spec` (rupees only)."""
    low, mid, high = (
        sum(_page_usd(spec, n, per, out, frac) for n in sizes) * rate for per, out, frac in ASSUME
    )
    calls = len(sizes) * max(1, brains)
    paid = write.paid(spec)
    return Estimate(
        id=_id(run, spec, sizes, rate, cap, release),
        run=run,
        brain=spec.id,
        pages=len(sizes),
        low=math.floor(low),
        mid=about_inr(mid),
        high=math.ceil(high),
        hold=hold_inr(spec, max(sizes, default=0), rate),
        cap=cap,
        minutes_low=math.ceil(calls * (1 + ASSUME[0][2]) * CALL_SECONDS[0] / 60),
        minutes_high=math.ceil(calls * (1 + ASSUME[2][2]) * CALL_SECONDS[1] / 60),
        gst_note=GST_NOTE.format(maker=write.maker(spec)) if paid else "",
        sent_to=sent_to,
    )


__all__ = [
    "ASSUME",
    "CALL_SECONDS",
    "REDRAFT_EXTRA_TOKENS",
    "estimate",
    "hold_inr",
    "page_inr",
    "price_of",
    "tokens_worst",
]
