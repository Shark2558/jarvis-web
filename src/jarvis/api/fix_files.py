# src/jarvis/api/fix_files.py
"""R11.1 Part B's routes, under `/v1/input` (docs/plans/r11-1-observations.md). Owner-only
(`require_auth`; cookie writes need `X-Requested-With: JARVIS`), `no-store`. They read the part's
services from `app.state.r111_parts["files"].services` per request.

GET /v1/input    {part, ready}: the part's status. I0 stub: Part B adds its routes here
            (POST /v1/input/understand: heard words in, understood words out;
            POST /v1/input/estimate: the rupee estimate before a costly reply).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.fixes.ports import NOT_BUILT, ROUTE_PREFIX, FixPart, PartName

PART: PartName = "files"
PREFIX = ROUTE_PREFIX[PART]
NO_STORE = {"Cache-Control": "no-store"}
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])


def part_of(request: Request) -> FixPart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r111_parts", None) or {}
    return parts.get(PART)


@router.get("")
async def status(request: Request) -> JSONResponse:
    part = part_of(request)
    ready = part.ready if part is not None else NOT_BUILT
    return JSONResponse({"part": PART, "ready": ready}, headers=NO_STORE)


__all__ = ["PREFIX", "part_of", "router"]
