# src/jarvis/understand/estimate.py
"""The rupee estimate before a costly reply (R11.1; plan D12; Layers 2 and 4).

When the files waiting to go with a message are large or complex (`is_large`: more than 40,000
characters in all, a workbook with more than 3 sheets or 2,000 rows, more than 2 pictures) the
console asks before it sends, and shows above Send:

    About ₹N on the <tier> tier; about ₹M on the stronger tier.

with the tier it suggests (the stronger one when the files are complex, the current one when
they are only long); the owner chooses, then sends. The estimate is deliberately simple and is
always "about": the files' characters and the message's, divided by 4, plus about 1,500 tokens
a picture (only for a brain that will be shown it), as input; a quarter of the working answer
cap (`work_output_tokens`) as output; at `llm/pricing.py` prices and the day's rate
(`Billing.inr`). Below ₹5 on the tier the reply would use, nothing is shown. Nothing is shown
either for a brain that costs nothing or whose price is unknown, in No-AI mode (no reply is paid
for), or when anything needed to work it out is missing. It never calls a model and never
spends: it only reads the owner's own waiting files' counts. A skill still asks for a tier,
never a model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from jarvis.billing.service import paid_brain, rupees
from jarvis.fixes.ports import FixContext
from jarvis.llm.base import Usage
from jarvis.llm.pricing import CHARS_PER_TOKEN, cost_usd
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger

log = get_logger(__name__)

LARGE_CHARS = 40_000
MANY_SHEETS = 3
MANY_ROWS = 2_000
MANY_PICTURES = 2
PICTURE_TOKENS = 1_500  # about what one picture costs to read (the plan's cost table)
TYPICAL_OUTPUT_SHARE = 4  # the output cap's typical use: a quarter of it
SHOW_FROM_INR = 5.0
MAX_IDS = 20
STRONGER: dict[ModelTier, ModelTier] = {
    ModelTier.FAST: ModelTier.BALANCED,
    ModelTier.BALANCED: ModelTier.STRONG,
}


@dataclass(frozen=True)
class Estimate:
    show: bool = False
    tier: str = ""
    inr: float = 0.0
    stronger_tier: str | None = None
    stronger_inr: float | None = None
    suggest: str = ""
    line: str = ""


NOTHING = Estimate()


def is_large(*, chars: int, sheets: int, rows: int, pictures: int) -> bool:
    """Large or complex enough to be worth an estimate (plan D12)."""
    return (
        chars > LARGE_CHARS or sheets > MANY_SHEETS or rows > MANY_ROWS or pictures > MANY_PICTURES
    )


def _complex(*, sheets: int, rows: int, pictures: int) -> bool:
    return sheets > MANY_SHEETS or rows > MANY_ROWS or pictures > MANY_PICTURES


def _about(inr: float) -> str:
    return rupees(float(round(inr)))


class Estimator:
    def __init__(self, ctx: FixContext) -> None:
        self._ctx = ctx

    async def _waiting(self, uid: str, ids: Sequence[str]) -> list[Any]:
        docs = self._ctx.state("documents")
        if docs is None:
            return []
        found = [await docs.store.get(aid) for aid in list(dict.fromkeys(ids))[:MAX_IDS]]
        return [a for a in found if a is not None and a.owner == uid and a.waiting]

    async def _ai_off(self, uid: str) -> bool:
        mode = self._ctx.state("brain_mode")
        if mode is None:
            return True
        return bool(await mode.load(uid) == "none")

    def _tier(self, wanted: str | None) -> ModelTier:
        try:
            return ModelTier(wanted or self._ctx.s.default_tier)
        except ValueError:
            return ModelTier(self._ctx.s.default_tier)

    async def estimate(
        self,
        uid: str,
        *,
        attachments: Sequence[str],
        message: str = "",
        brain: str | None = None,
        tier: str | None = None,
    ) -> Estimate:
        """What a reply on these waiting files would cost, or `NOTHING` (show False)."""
        try:
            return await self._estimate(uid, attachments, message, brain, tier)
        except Exception as exc:  # noqa: BLE001 — an estimate is a courtesy, never a failure
            log.warning("estimate unavailable", extra={"reason": type(exc).__name__})
            return NOTHING

    async def _estimate(
        self, uid: str, ids: Sequence[str], message: str, brain: str | None, tier: str | None
    ) -> Estimate:
        atts = await self._waiting(uid, ids)
        chars = sum(a.chars for a in atts)
        sheets = max((a.sheets or 0 for a in atts), default=0)
        rows = max((a.rows or 0 for a in atts), default=0)
        pictures = sum(a.pictures for a in atts)
        if not atts or not is_large(chars=chars, sheets=sheets, rows=rows, pictures=pictures):
            return NOTHING
        brains, billing = self._ctx.state("brains"), self._ctx.state("billing")
        if brains is None or billing is None or await self._ai_off(uid):
            return NOTHING
        try:
            spec = brains.get(brain) if brain else brains.default
        except LookupError:
            spec = brains.default
        if not paid_brain(spec):
            return NOTHING
        usage = Usage(
            input_tokens=-(-(chars + len(message)) // CHARS_PER_TOKEN)
            + (pictures * PICTURE_TOKENS if spec.sees_pictures else 0),
            output_tokens=int(self._ctx.s.work_output_tokens) // TYPICAL_OUTPUT_SHARE,
        )
        now = self._tier(tier)
        inr = await billing.inr(cost_usd(spec.tiers[now], usage))
        up = STRONGER.get(now)
        up_inr = await billing.inr(cost_usd(spec.tiers[up], usage)) if up is not None else None
        if inr < SHOW_FROM_INR:
            return Estimate(show=False, tier=now.value, inr=round(inr, 2))
        line = f"About {_about(inr)} on the {now.value} tier"
        if up_inr is not None:
            line += f"; about {_about(up_inr)} on the stronger tier"
        hard = _complex(sheets=sheets, rows=rows, pictures=pictures)
        return Estimate(
            show=True,
            tier=now.value,
            inr=round(inr, 2),
            stronger_tier=up.value if up is not None else None,
            stronger_inr=round(up_inr, 2) if up_inr is not None else None,
            suggest=up.value if hard and up is not None else now.value,
            line=line + ".",
        )


__all__ = [
    "LARGE_CHARS",
    "MANY_PICTURES",
    "MANY_ROWS",
    "MANY_SHEETS",
    "PICTURE_TOKENS",
    "SHOW_FROM_INR",
    "Estimate",
    "Estimator",
    "is_large",
]
