# src/jarvis/api/selfwatch.py
"""R14 Part B's route, under `/v1/selfwatch` (docs/plans/r14-hardening.md D5). Owner-only,
`no-store`.

GET /v1/selfwatch   {part, ready, clocks: {tick, watchdog, tick_outage, watchdog_outage},
                    jobs: [{name, runs, since, told}], errors_today, unrecorded: {errors,
                    outcomes}, alerts: {waiting, given_up}, deploy: {revision, version, at},
                    version}: names, counts and times only. With the part off
                    (or left out) only {part, ready}; a view that fails answers
                    {part, ready, unavailable: true} (its error is a class name in the log).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.r14_status import NO_STORE, part_of, ready_of
from jarvis.hardening.ports import PartName
from jarvis.logging import get_logger

log = get_logger(__name__)

PART: PartName = "selfwatch"


@runtime_checkable
class StatusView(Protocol):
    async def view(self) -> dict[str, Any]: ...


router = APIRouter(prefix="/v1/selfwatch", dependencies=[Depends(require_auth)])


@router.get("", include_in_schema=False)
async def selfwatch_status(request: Request) -> JSONResponse:
    body: dict[str, Any] = {"part": PART, "ready": ready_of(request, PART)}
    part = part_of(request, PART)
    status = part.services.get("status") if part is not None else None
    if isinstance(status, StatusView):
        try:
            body.update(await status.view())
        except Exception as exc:  # noqa: BLE001 - plain words, never the cause's text
            log.warning("selfwatch status unreadable", extra={"error": type(exc).__name__})
            body["unavailable"] = True
    return JSONResponse(body, headers=NO_STORE)


__all__ = ["router"]
