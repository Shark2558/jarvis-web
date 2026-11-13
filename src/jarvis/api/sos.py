# src/jarvis/api/sos.py
"""R7 Part D's SOS routes, under `/v1/sos` (D19, D20): contacts, join links, send, test, I'm safe.
Owner-only, `no-store`; never locked by the app lock (D21).

I0 stub: `GET /v1/sos` answers {part, ready}. Part D adds its routes here
(docs/plans/r7-mobile.md; docs/plans/r7-integration/BRIEF-COMMON.md).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth
from jarvis.api.mobile_status import status_route
from jarvis.mobile.ports import PartName

PART: PartName = "body"
router = APIRouter(prefix="/v1/sos", dependencies=[Depends(require_auth)])
router.add_api_route("", status_route(PART), methods=["GET"], include_in_schema=False)

__all__ = ["PART", "router"]
