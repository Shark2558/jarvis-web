# src/jarvis/api/web.py
"""Web search status for the console's Vitals line (slice 10 B). Owner-only (`require_auth`).

GET /v1/web/usage   {configured: false}  — no Tavily key (web search is not set up), or
                    {configured: true, month, used, limit, left, reached, unreadable}
                    "Web search: N of 900 this month"; an unreadable counter is said so (used and
                    left null), never shown as 0. ₹0: the free plan only, never pay-as-you-go.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from jarvis.api.auth import require_auth
from jarvis.web.service import WebService, usage_view

router = APIRouter(prefix="/v1/web", dependencies=[Depends(require_auth)])


def _web(request: Request) -> WebService | None:
    return getattr(request.app.state, "web", None)


@router.get("/usage")
async def web_usage(web: WebService | None = Depends(_web)) -> dict[str, Any]:
    return await usage_view(web)


__all__ = ["router"]
