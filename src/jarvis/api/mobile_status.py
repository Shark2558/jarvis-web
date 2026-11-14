# src/jarvis/api/mobile_status.py
"""R7 I0: one owner-only `GET` that says a part's status, for every R7 part's route stub.

    {part, ready}   ready: the part's status word ("not built yet" until it is built)

Owner-only (`require_auth`), `no-store`. A part reads its services from
`app.state.r7_parts[<part>].services` per request (`part_of`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from jarvis.mobile.ports import NOT_BUILT, MobilePart, PartName

NO_STORE = {"Cache-Control": "no-store"}


def part_of(request: Request, name: PartName) -> MobilePart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r7_parts", None) or {}
    return parts.get(name)


def status_route(name: PartName) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def status(request: Request) -> JSONResponse:
        part = part_of(request, name)
        ready = part.ready if part is not None else NOT_BUILT
        return JSONResponse({"part": name, "ready": ready}, headers=NO_STORE)

    status.__name__ = f"r7_{name}_status"
    return status


__all__ = ["NO_STORE", "part_of", "status_route"]
