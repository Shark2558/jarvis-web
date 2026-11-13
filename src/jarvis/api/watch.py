# src/jarvis/api/watch.py
"""R7 Part D's watch and sleep routes, under `/v1/watch` (D17, D18). Owner-only, `no-store`.

I0 stub: `GET /v1/watch` answers {part, ready}. Part D adds its routes here
(docs/plans/r7-mobile.md; docs/plans/r7-integration/BRIEF-COMMON.md).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth
from jarvis.api.mobile_status import status_route
from jarvis.mobile.ports import PartName

PART: PartName = "body"
router = APIRouter(prefix="/v1/watch", dependencies=[Depends(require_auth)])
router.add_api_route("", status_route(PART), methods=["GET"], include_in_schema=False)

__all__ = ["PART", "router"]
