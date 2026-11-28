# src/jarvis/api/coach_day.py
"""R8 rows 182 and 183 (docs/plans/r8-vision.md 4.7, D12; builder C): Camera -> Desk -> "Your
day". Owner-only (`require_auth` + `current_user`), `no-store`, errors `{error, detail}` in plain
words.

    GET /v1/coach/day?day=yyyy-mm-dd&who=me   the day strip (desk, away, phone, eating, off),
                                              its totals, the longest sitting stretch and screen
                                              time (per-program minutes, never a window title)

`app.state.coach_day` is a `jarvis.coach.day.DayService` (I1 builds it beside `app.state.coach`
and adds this router to `api/r8_wiring.ROUTERS`); without it the route answers 404 `coach_off`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.coach.day import DayService
from jarvis.coach.people import CoachOff, is_who
from jarvis.coach.store import CoachUnavailable
from jarvis.logging import get_logger

log = get_logger(__name__)

NO_STORE = {"Cache-Control": "no-store"}
OFF = {"error": "coach_off", "detail": "The coaches aren't set up on this server."}
BAD = {"error": "bad_request", "detail": "Pick a day from your kept days, Sir."}
UNAVAILABLE = {"error": "unavailable", "detail": "Your day couldn't be read just now, Sir."}
router = APIRouter(prefix="/v1/coach", dependencies=[Depends(require_auth)])


def _answer(status: int, body: Mapping[str, object]) -> JSONResponse:
    return JSONResponse(status_code=status, content=dict(body), headers=NO_STORE)


@router.get("/day", response_model=None)
async def coach_day(
    request: Request,
    day: str = Query(default="", max_length=10),
    who: str = Query(default="me", max_length=20),
    uid: str = Depends(current_user),
) -> JSONResponse:
    days = getattr(request.app.state, "coach_day", None)
    if not isinstance(days, DayService):
        return _answer(404, OFF)
    try:
        when = date.fromisoformat(day) if day else days.today()
        if not is_who(who):
            raise ValueError("who")
        got = await days.day(uid, when, who=who)
    except CoachOff as exc:
        return _answer(409, {"error": "not_sealed", "detail": str(exc)})
    except CoachUnavailable:
        return _answer(503, UNAVAILABLE)
    except ValueError:
        return _answer(422, BAD)
    except Exception as exc:  # noqa: BLE001 - plain words, the class in the log
        log.warning("day strip failed", extra={"error": type(exc).__name__})
        return _answer(503, UNAVAILABLE)
    return _answer(200, {"day": got.as_json()})


__all__ = ["router"]
