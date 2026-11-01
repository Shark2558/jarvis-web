# src/jarvis/api/usage.py
"""This month's AI spend and the owner's limit (slice 7b). Owner-only: `require_auth` +
`current_user` (the user id is never taken from the client); the write needs
`X-Requested-With: JARVIS` when the caller is a browser session (enforced by `require_auth`).

GET /v1/usage           UsageView {month, used_inr, limit_inr, remaining_inr, percent, warn,
                        reached, calls, by_brain [{brain, label, used_inr}], rate {inr_per_usd,
                        as_of, source}}
PUT /v1/usage/budget    {monthly_limit_inr: int 1–100000 | null, confirm_raise?: true} →
                        UsageView; 422 {"error": "invalid_budget"} out of range, or a raise /
                        removal without confirm_raise (it lets JARVIS spend more)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.billing import Billing, BudgetPatch, UsageView

router = APIRouter(prefix="/v1/usage", dependencies=[Depends(require_auth)])


def _billing(request: Request) -> Billing:
    return request.app.state.billing  # type: ignore[no-any-return]


@router.get("", response_model=UsageView)
async def usage(
    billing: Billing = Depends(_billing), uid: str = Depends(current_user)
) -> UsageView:
    return await billing.usage(uid)


@router.put("/budget", response_model=UsageView)
async def put_budget(
    patch: BudgetPatch, billing: Billing = Depends(_billing), uid: str = Depends(current_user)
) -> UsageView:
    return await billing.set_limit(uid, patch)


__all__ = ["router"]
