# src/jarvis/api/vision.py
"""R7 Part B's routes, under `/v1/vision` (D12): the results he kept (sealed, 90 days). Owner-only,
`no-store`; a picture never comes here (only results).

I0 stub: `GET /v1/vision` answers {part, ready}. Part B adds its routes here
(docs/plans/r7-mobile.md; docs/plans/r7-integration/BRIEF-COMMON.md).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth
from jarvis.api.mobile_status import status_route
from jarvis.mobile.ports import PartName

PART: PartName = "vision"
router = APIRouter(prefix="/v1/vision", dependencies=[Depends(require_auth)])
router.add_api_route("", status_route(PART), methods=["GET"], include_in_schema=False)

__all__ = ["PART", "router"]
