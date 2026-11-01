# src/jarvis/billing/budget.py
"""The owner's monthly limit for paid AI, in whole rupees (Layer 4 guardrail; Layer 7 storage).

    {prefix}budget/{uid}   monthly_limit_inr (int | null), updated_at

Unset = no JARVIS limit (Anthropic's own spend limit stays the hard backstop). Lowering or setting
a first limit only ever reduces what JARVIS may spend, so it needs nothing more. Raising or
removing lets JARVIS spend more: confirm-before-commit, so it needs `confirm_raise: true`. The
rule is applied inside the write transaction, against the limit as it is stored, so a stale page
cannot slip a raise through as a "lower".

Fail closed: a stored value that is not a whole number of rupees in range (or a document without
the field) is UNREADABLE, never "no limit". `get` raises LimitUnreadable (the spending gate then
makes no paid call), and any change to it needs `confirm_raise` (nobody can tell a lower from a
raise).
"""

from __future__ import annotations

import math
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
MSG_UNREADABLE = (
    "The stored monthly limit can't be read, so this change may let JARVIS spend more; confirm "
    "to set it (confirm_raise)."
)
FIELD = "monthly_limit_inr"


class BudgetRejected(ValueError):
    """A limit change that is out of range or needs a confirmation (→ 422, plain English)."""


class LimitUnreadable(RuntimeError):
    """The stored limit is not a whole number of rupees in range: fail closed, never "unset"."""


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


def apply_limit(old: int | None, patch: BudgetPatch, *, readable: bool = True) -> int | None:
    """The new limit, or BudgetRejected. `readable=False`: the stored limit couldn't be read, so
    every change needs the confirmation."""
    new = patch.monthly_limit_inr
    if new is not None and not LIMIT_MIN <= new <= LIMIT_MAX:
        raise BudgetRejected(MSG_RANGE)
    if patch.confirm_raise:
        return new
    if not readable:
        raise BudgetRejected(MSG_UNREADABLE)
    if needs_confirm(old, new):
        raise BudgetRejected(MSG_REMOVE if new is None else MSG_RAISE)
    return new


def _limit(doc: object) -> int | None:
    """None = no document or an explicit null (no limit); else a limit in range. Anything else
    raises LimitUnreadable."""
    if doc is None:
        return None
    if not isinstance(doc, dict) or FIELD not in doc:
        raise LimitUnreadable("budget document without a limit field")
    v = doc[FIELD]
    if v is None:
        return None
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or not LIMIT_MIN <= v <= LIMIT_MAX:
        raise LimitUnreadable("stored limit is not a whole number of rupees in range")
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
        """The owner's limit (None = not set). Raises LimitUnreadable: never guess "not set"."""
        try:
            return _limit(await self._d.get(self._path(uid)))
        except LimitUnreadable:
            log.error("MONTHLY LIMIT UNREADABLE; paid calls stay off until it is set again")
            raise

    async def update(
        self, uid: str, patch: BudgetPatch, *, now: datetime | None = None
    ) -> int | None:
        """Apply `patch` to the stored limit in one transaction; BudgetRejected writes nothing."""
        path = self._path(uid)
        at = (now or datetime.now(UTC)).isoformat()

        async def fn(tx: DocTx) -> int | None:
            raw = await tx.get(path)
            try:
                old, readable = _limit(raw), True
            except LimitUnreadable:
                old, readable = None, False
            new = apply_limit(old, patch, readable=readable)
            tx.set(path, {"user_id": uid, FIELD: new, "updated_at": at})
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
    "LimitUnreadable",
    "apply_limit",
    "needs_confirm",
]
