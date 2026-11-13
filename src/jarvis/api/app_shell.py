# src/jarvis/api/app_shell.py
"""R7 Part A (The app on the web side; D3, D8, D9 web, D15): the part's one join with the app
(`jarvis.mobile.ports`) and its routes: `GET /manifest.webmanifest` and the icons (public, no
cookies), `GET /app/share/sw.js` and `POST /app/share/in` (the share tray's worker and the route
that discards a share the worker did not catch).

I0 stub: `build` returns an empty part and `GET /app/status` answers {part, ready}. Part A
replaces both and adds its routes here; see docs/plans/r7-mobile.md and
docs/plans/r7-integration/BRIEF-COMMON.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth
from jarvis.api.mobile_status import status_route
from jarvis.mobile.ports import MobileContext, MobilePart, PartName

PART: PartName = "shell"
router = APIRouter()
router.add_api_route(
    "/app/status",
    status_route(PART),
    methods=["GET"],
    include_in_schema=False,
    dependencies=[Depends(require_auth)],
)


def build(ctx: MobileContext) -> MobilePart:
    del ctx
    return MobilePart(PART)


__all__ = ["PART", "build", "router"]
