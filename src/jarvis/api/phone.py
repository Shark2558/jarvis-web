# src/jarvis/api/phone.py
"""R7 Part C's console routes, under `/v1/phone` (D5, D21): link a phone, the linked phones,
unlink, sign out everywhere. Owner-only, `no-store`. The phone's own door (`/phone/link`,
`/phone/v1/*`) and `/.well-known/assetlinks.json` are public and are Part C's too.

I0 stub: `GET /v1/phone` answers {part, ready}. Part C adds its routes here
(docs/plans/r7-mobile.md; docs/plans/r7-integration/BRIEF-COMMON.md).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth
from jarvis.api.mobile_status import status_route
from jarvis.mobile.ports import PartName

PART: PartName = "phone"
router = APIRouter(prefix="/v1/phone", dependencies=[Depends(require_auth)])
router.add_api_route("", status_route(PART), methods=["GET"], include_in_schema=False)

__all__ = ["PART", "router"]
