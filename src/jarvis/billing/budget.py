# src/jarvis/billing/budget.py
"""The owner's monthly limit for paid AI, in whole rupees (Layer 4 guardrail; Layer 7 storage).

    {prefix}budget/{uid}   monthly_limit_inr (int | null), updated_at

Unset = no JARVIS limit (Anthropic's own spend limit stays the hard backstop). Lowering or setting
a first limit only ever reduces what JARVIS may spend, so it needs nothing more. Raising or
removing lets JARVIS spend more: confirm-before-commit, so it needs `confirm_raise: true`. The
rule is applied inside the write transaction, against the limit as it is stored, so a stale page
cannot slip a raise through as a "lower".
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)

LIMIT_MIN = 1
LIMIT_MAX = 100_000
MSG_RANGE = "The limit must be a whole number of rupees from ₹1 to ₹1,00,000."
MSG_RAISE = (
    "Raising the monthly limit lets JARVIS spend more on the paid AI; confirm to raise it "
    "(confirm_raise)."
)
MSG_REMOVE = (
    "Removing the monthly limit lets JARVIS spend without one; confirm to remove it "
    "(confirm_raise)."
)


class BudgetRejected(ValueError):
    """A limit change that is out of range or needs a confirmation (→ 422, plain English)."""


class BudgetPatch(BaseModel):
    """PUT /v1/usage/budget. `monthly_limit_inr` must be sent: null removes the limit."""

    model_config = ConfigDict(strict=True, extra="ignore")

    monthly_limit_inr: int | None = Field(..., description="Whole rupees 1–100000, or null")
    confirm_raise: bool = Field(
        default=False, description="Required (true) to raise or remove the limit"
    )


def needs_confirm(old: int | None, new: int | None) -> bool:
    """True when the change lets JARVIS spend more than the stored limit allows."""
    return old is not None and (new is None or new > old)


def apply_limit(old: int | None, patch: BudgetPatch) -> int | None:
    new = patch.monthly_limit_inr
    if new is not None and not LIMIT_MIN <= new <= LIMIT_MAX:
        raise BudgetRejected(MSG_RANGE)
    if needs_confirm(old, new) and not patch.confirm_raise:
        raise BudgetRejected(MSG_REMOVE if new is None else MSG_RAISE)
    return new


def _limit(doc: object) -> int | None:
    if not isinstance(doc, dict):
        return None
    v = doc.get("monthly_limit_inr")
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int):
        log.error("unreadable monthly limit; treating it as not set")
        return None
    return v


class BudgetStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}budget"

    def _path(self, uid: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> int | None:
        return _limit(await self._d.get(self._path(uid)))

    async def update(
        self, uid: str, patch: BudgetPatch, *, now: datetime | None = None
    ) -> int | None:
        """Apply `patch` to the stored limit in one transaction; BudgetRejected writes nothing."""
        path = self._path(uid)
        at = (now or datetime.now(UTC)).isoformat()

        async def fn(tx: DocTx) -> int | None:
            old = _limit(await tx.get(path))
            new = apply_limit(old, patch)
            tx.set(path, {"user_id": uid, "monthly_limit_inr": new, "updated_at": at})
            return new

        new = await self._d.transaction(fn)
        log.info("monthly limit changed", extra={"limit_inr": new})
        return new


__all__ = [
    "LIMIT_MAX",
    "LIMIT_MIN",
    "BudgetPatch",
    "BudgetRejected",
    "BudgetStore",
    "apply_limit",
    "needs_confirm",
]
