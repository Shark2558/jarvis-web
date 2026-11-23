# src/jarvis/buildbook/writer/consent.py
"""R6.3 D6, D7, D12 (plan review H2): every grant of spending authority is his typed YES on the
rupee words shown first. `grants` names what a pick grants beyond `Pick.confirmed` (what his last
typed YES granted, all zero at first): the first saved pick (every non-zero cap is a raise), any
cap or the % line raised, a switch to a paid brain, a switch to a brain that trains on what it
reads (the learning note, no rupees), and "update by itself" turned on. Nothing granted: the pick
saves at once (lowering is instant). `terms_id` binds a YES to exactly those words: the pick, the
brain's balanced price and the day's rate (`wt_` + 12 hex, never an estimate's `we_`).
"""

from __future__ import annotations

import hashlib
import json

import jarvis.llm.write as write
from jarvis.buildbook.writer import estimate, texts
from jarvis.buildbook.writer.model import PACK_CAP_BYTES, Caps, Confirmed, is_yes
from jarvis.llm.brains import BrainSpec

RUPEE_CAPS = ("trial", "first", "release", "month")
TYPICAL_PAGE_BYTES = 48_000  # a page's typical pack, for the "about" of one page (D8's mid)


def terms_id(brain: str, caps: Caps, auto: bool, *, price: float, rate: float) -> str:
    raw = json.dumps(
        {"brain": brain, "caps": caps.model_dump(), "auto": auto, "price": price, "rate": rate},
        sort_keys=True,
    )
    return "wt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _brain_words(spec: BrainSpec, confirmed: Confirmed, rate: float) -> list[str]:
    if spec.id == confirmed.brain:
        return []
    out: list[str] = []
    if write.paid(spec):
        page = estimate.page_inr(spec, TYPICAL_PAGE_BYTES, rate)
        hold = estimate.hold_inr(spec, PACK_CAP_BYTES, rate)
        out.append(
            texts.PAID_WORDS.format(label=spec.label, page=texts.inr(page), hold=texts.inr(hold))
        )
    if spec.trains_on_content:
        out.append(texts.TRAINS_WORDS.format(label=spec.label, maker=write.maker(spec)))
    return out


def _cap_words(spec: BrainSpec, caps: Caps, confirmed: Confirmed) -> list[str]:
    old = confirmed.caps
    if confirmed.brain is None:  # the first saved pick: every cap is granted at once
        first = texts.PICK_WORDS.format(
            label=spec.label,
            first=texts.inr(caps.first),
            release=texts.inr(caps.release),
            month=texts.inr(caps.month),
        )
        return [first, texts.PCT_WORDS.format(pct=caps.limit_pct)]
    out = [
        texts.RAISE_WORDS.format(
            what=texts.CAP_NAMES[name],
            old=texts.inr(getattr(old, name)),
            new=texts.inr(getattr(caps, name)),
        )
        for name in RUPEE_CAPS
        if getattr(caps, name) > getattr(old, name)
    ]
    if caps.limit_pct > old.limit_pct:
        out.append(texts.PCT_RAISE_WORDS.format(old=old.limit_pct, new=caps.limit_pct))
    return out


def grants(
    *, spec: BrainSpec, caps: Caps, auto: bool, confirmed: Confirmed, rate: float
) -> tuple[str, ...]:
    """The words of what this pick grants beyond `confirmed` (at most six); () grants nothing."""
    words = _brain_words(spec, confirmed, rate) + _cap_words(spec, caps, confirmed)
    if auto and not confirmed.auto_update:
        words.append(
            texts.AUTO_WORDS.format(release=texts.inr(caps.release), month=texts.inr(caps.month))
        )
    if confirmed.brain is not None and not words:
        return ()
    return tuple(words[:6])


def lowered(caps: Caps, auto: bool, confirmed: Confirmed) -> Confirmed:
    """What stays granted after a save that granted nothing: the lower values (H2)."""
    return confirmed.model_copy(
        update={"caps": caps, "auto_update": auto and confirmed.auto_update}
    )


__all__ = ["RUPEE_CAPS", "grants", "is_yes", "lowered", "terms_id"]
