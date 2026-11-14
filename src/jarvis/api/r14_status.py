# src/jarvis/api/r14_status.py
"""R14 I0: the parts' status, for every R14 part's route stub, and `GET /v1/r14`.

    GET /v1/r14   {parts: {backup, selfwatch, skills, noai: ready}}   ready: "not built yet" until
                  the part is built, "setup failed" when the wiring left it out

Owner-only (`require_auth`), `no-store`. A part's routes read its services from
`app.state.r14_parts[<part>].services` per request (`part_of`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.hardening.ports import NOT_BUILT, PARTS, R14_STATUS_ROUTE, HardeningPart, PartName

NO_STORE = {"Cache-Control": "no-store"}
router = APIRouter(dependencies=[Depends(require_auth)])


def part_of(request: Request, name: PartName) -> HardeningPart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r14_parts", None) or {}
    return parts.get(name)


def ready_of(request: Request, name: PartName) -> str:
    part = part_of(request, name)
    return part.ready if part is not None else NOT_BUILT


def status_route(name: PartName) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def status(request: Request) -> JSONResponse:
        return JSONResponse({"part": name, "ready": ready_of(request, name)}, headers=NO_STORE)

    status.__name__ = f"r14_{name}_status"
    return status


@router.get(R14_STATUS_ROUTE, include_in_schema=False)
async def r14_status(request: Request) -> JSONResponse:
    return JSONResponse({"parts": {n: ready_of(request, n) for n in PARTS}}, headers=NO_STORE)


__all__ = ["NO_STORE", "part_of", "ready_of", "router", "status_route"]
