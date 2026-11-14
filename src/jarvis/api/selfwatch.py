# src/jarvis/api/selfwatch.py
"""R14 Part B's route, under `/v1/selfwatch` (docs/plans/r14-hardening.md D5). Owner-only,
`no-store`.

GET /v1/selfwatch   {part, ready}  (I0's stub; Part B adds the clocks' last runs, the jobs in a
                    streak, today's error count and the last revision: names and counts only)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth
from jarvis.api.r14_status import status_route
from jarvis.hardening.ports import PartName

PART: PartName = "selfwatch"
router = APIRouter(prefix="/v1/selfwatch", dependencies=[Depends(require_auth)])
router.add_api_route("", status_route(PART), methods=["GET"], include_in_schema=False)

__all__ = ["router"]
