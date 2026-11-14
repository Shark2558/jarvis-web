# src/jarvis/api/skills.py
"""R14 Part C's routes (docs/plans/r14-hardening.md D8, D11). Owner-only, `no-store`.

GET /v1/skills         {part, ready}  (I0's stub; Part C adds the register: the 11 skills, each
                       with its tools' count and what works with the AI off)
GET /v1/costs/ledger   {part, ready}  (I0's stub; Part C adds this month's tokens and ₹ by part)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth
from jarvis.api.r14_status import status_route
from jarvis.hardening.ports import PartName

PART: PartName = "skills"
router = APIRouter(dependencies=[Depends(require_auth)])
router.add_api_route("/v1/skills", status_route(PART), methods=["GET"], include_in_schema=False)
router.add_api_route(
    "/v1/costs/ledger", status_route(PART), methods=["GET"], include_in_schema=False
)

__all__ = ["router"]
