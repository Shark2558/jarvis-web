# src/jarvis/api/activity.py
"""Activity over HTTP (R1 plan D7/D8; Layer 1 -> 3). Owner-only: `require_auth` + `current_user`
(no client user id is read); read-only. Undo is NOT a route here: the console's Undo button calls
the existing `POST /v1/deleted/{id}/restore`.

GET /v1/activity?day=today|yesterday
    {day, items: [{id, at, words, outcome: done|waiting|refused|failed|declined,
                   channel: console|voice|telegram, offline,
                   undo: {id, state: available|restored|expired|gone} | null, undo_note}],
     verified, available}
    `words` and `undo_note` are plain text (the console renders them with textContent).
    `verified`: the audit chain verifies. `available: false`: nothing is recorded on this server.
    Wiring (I1): `app.state.activity = ActivityService(...)`; `gw.observers = [ActivityRecorder]`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request

from jarvis.activity.models import ActivityView, Day
from jarvis.activity.service import ActivityService
from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/v1/activity", dependencies=[Depends(require_auth)])
AUDIT_WINDOW = 50


async def _verified(request: Request) -> bool:
    gw = getattr(request.app.state, "gateway", None)
    if gw is None:
        return True
    try:
        return bool((await gw.audit.tail(AUDIT_WINDOW)).verified)
    except Exception as exc:  # noqa: BLE001 - unknown is not "verified"
        log.warning("audit tail unreadable", extra={"error": type(exc).__name__})
        return False


@router.get("", response_model=ActivityView)
async def activity(
    request: Request, day: Day = "today", uid: str = Depends(current_user)
) -> ActivityView:
    svc: ActivityService | None = getattr(request.app.state, "activity", None)
    verified = await _verified(request)
    if svc is None:
        return ActivityView(day=day, items=[], verified=verified, available=False)
    try:
        view = await svc.view(uid, day)
    except Exception as exc:  # noqa: BLE001 - a storage problem is "not available", not a 500
        log.error("activity view failed", extra={"error": type(exc).__name__})
        return ActivityView(day=day, items=[], verified=verified, available=False)
    return view.model_copy(update={"verified": verified})


def install_activity(app: FastAPI) -> None:
    app.include_router(router)


__all__ = ["install_activity", "router"]
