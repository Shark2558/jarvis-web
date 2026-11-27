# src/jarvis/api/coach.py
"""R8 I0 seam S9 (docs/plans/r8-vision.md v8.0.3 sections 4.3, 4.4; D6, D7): the coaches' routes.
Owner-only (`require_auth` + `current_user`), `no-store`, JSON object bodies of at most 64 KB
(a routine: 512 KB). Errors are `{error, detail}` in plain words, never library text.

    GET    /v1/coach/usecases            the registry the panes need (no service needed)
    GET    /v1/coach/results?days&who    kept tallies, newest first (everyone's, or one who)
    POST   /v1/coach/results             {use, session, track, who, tally}: who "" is a guest
                                         ("Guest N" of that session, the owner's D6)
    DELETE /v1/coach/results/{id}        one kept tally
    GET    /v1/coach/export?who=         his own export (JSON of the tallies and the guests)
    GET    /v1/coach/people              the guests (their labels and merges)
    PATCH  /v1/coach/people/{guest}      {label} or {merge_into}
    DELETE /v1/coach/people/{who}        501 until I1: a person's whole record needs the passkey
    GET    /v1/coach/routines/{rid}      his routine or calibration (joint angles only)
    PUT    /v1/coach/routines/{rid}      {kind, angles}
    GET    /v1/coach/target              the tracking target (D6)
    PUT    /v1/coach/target              {kind, person} or {name} (a name through Faces' consent
                                         registry; "I don't know <name> yet" when nobody's)
    POST   /v1/coach/bp/readings         a confirmed reading only (D7: `BpConfirm`, who)
    GET    /v1/coach/live?use=           the home laptop's newest views (memory only; 501 until J)

`app.state.coach` is a `CoachApp` (wired by `api/r8_wiring.py`); without it every route but the
registry answers 404 `coach_off`.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from jarvis.api.auth import require_auth
from jarvis.api.body import BodyTooLarge, read_capped
from jarvis.api.identity import current_user
from jarvis.coach import usecases
from jarvis.coach.bp import BpConfirm
from jarvis.coach.people import GUEST, CoachOff, PeopleRefused, PeopleStore, is_who
from jarvis.coach.ports import HomeVision
from jarvis.coach.store import (
    BP_USE,
    KEEP_DAYS_RANGE,
    CoachStore,
    CoachUnavailable,
    DayFull,
    Dropped,
    RoutineStore,
)
from jarvis.coach.target import PeopleLookup, TargetStore, TrackTarget, resolve_name
from jarvis.logging import get_logger

log = get_logger(__name__)

BODY_MAX = 64 * 1024
ROUTINE_MAX = 512 * 1024
NO_STORE = {"Cache-Control": "no-store"}
OFF = {"error": "coach_off", "detail": "The coaches aren't set up on this server."}
UNAVAILABLE = "Your coach results couldn't be read just now, Sir."
NOT_BUILT = "That isn't built yet."
router = APIRouter(prefix="/v1/coach", dependencies=[Depends(require_auth)])


@dataclass
class CoachApp:
    store: CoachStore
    people: PeopleStore
    target: TargetStore
    routines: RoutineStore
    lookup: PeopleLookup | None = None  # I1: R3's consent registry
    home: HomeVision | None = None  # J: the home laptop's reports


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _app(request: Request) -> CoachApp | None:
    found = getattr(request.app.state, "coach", None)
    return found if isinstance(found, CoachApp) else None


async def _body(request: Request, limit: int = BODY_MAX) -> dict[str, Any]:
    raw = await read_capped(request, limit, too_large=lambda: BodyTooLarge(limit))
    data = json.loads(raw or b"null")
    if not isinstance(data, dict):
        raise ValueError("a JSON object")
    return data


Work = Callable[[CoachApp], Awaitable[JSONResponse]]


async def _do(request: Request, work: Work) -> JSONResponse:
    app = _app(request)
    if app is None:
        return _answer(404, OFF)
    try:
        return await work(app)
    except CoachOff as exc:
        return _answer(409, {"error": "not_sealed", "detail": str(exc)})
    except Dropped as exc:
        return _answer(422, {"error": "dropped", "detail": str(exc)})
    except DayFull as exc:
        return _answer(409, {"error": "day_full", "detail": str(exc)})
    except PeopleRefused as exc:
        return _answer(422, {"error": "refused", "detail": str(exc)})
    except CoachUnavailable as exc:
        return _answer(503, {"error": "unavailable", "detail": str(exc)})
    except BodyTooLarge:
        raise
    except (ValueError, ValidationError):
        return _answer(
            422, {"error": "bad_request", "detail": "That request isn't one JARVIS takes."}
        )
    except Exception as exc:  # noqa: BLE001 - plain words, the class in the log
        log.warning("coach route failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": UNAVAILABLE})


@router.get("/usecases")
async def coach_usecases() -> JSONResponse:
    return _answer(200, {"usecases": usecases.listing(), "views": list(usecases.VIEW_KINDS)})


@router.get("/results", response_model=None)
async def coach_results(
    request: Request,
    days: int = Query(default=7, ge=1, le=KEEP_DAYS_RANGE[1]),
    who: str = Query(default="", max_length=20),
    uid: str = Depends(current_user),
) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        if who and not is_who(who):
            raise ValueError("who")
        items = await a.store.list(uid, days=days, who=who or None)
        return _answer(
            200, {"sealed": a.store.sealed, "keep_days": a.store.keep_days, "results": items}
        )

    return await _do(request, work)


@router.post("/results", response_model=None)
async def coach_keep(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        body = await _body(request)
        use, session, who = (
            str(body.get("use", "")),
            str(body.get("session", "")),
            str(body.get("who", "")),
        )
        if not who:  # someone JARVIS didn't know: saved as a guest of this session (D6)
            track = body.get("track")
            if isinstance(track, bool) or not isinstance(track, int):
                raise ValueError("track")
            who = await a.people.guest_for(uid, session, track)
        who = await a.people.resolve(uid, who)
        kept = await a.store.keep(uid, use, who, session, body.get("tally"))
        return _answer(201, {"kept": {"id": kept["id"], "who": who}})

    return await _do(request, work)


@router.delete("/results/{rid}", response_model=None)
async def coach_forget(
    request: Request, rid: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        gone = await a.store.delete(uid, rid)
        return _answer(200 if gone else 404, {"deleted": gone})

    return await _do(request, work)


@router.get("/export", response_model=None)
async def coach_export(
    request: Request, who: str = Query(default="", max_length=20), uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        if who and not is_who(who):
            raise ValueError("who")
        out = await a.store.export(uid, who=who or None)
        return _answer(
            200, {**out, **(await a.people.export(uid) if a.store.sealed else {"guests": []})}
        )

    return await _do(request, work)


@router.get("/people", response_model=None)
async def coach_people(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        return _answer(200, await a.people.export(uid))

    return await _do(request, work)


@router.patch("/people/{guest}", response_model=None)
async def coach_person(
    request: Request, guest: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        if not GUEST.match(guest):
            raise ValueError("guest")
        body = await _body(request)
        if "label" in body:
            g = await a.people.rename(uid, guest, str(body["label"]))
        else:
            g = await a.people.merge(uid, guest, str(body.get("merge_into", "")))
        return _answer(200, {"guest": g.__dict__})

    return await _do(request, work)


@router.delete("/people/{who}", response_model=None)
async def coach_delete_person(who: str) -> JSONResponse:
    del who  # I1: through the privacy service's passkey proof, like every bulk delete
    return _answer(501, {"error": "not_built", "detail": NOT_BUILT})


@router.get("/routines/{rid}", response_model=None)
async def coach_routine(
    request: Request, rid: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        got = await a.routines.get(uid, rid)
        return _answer(200 if got else 404, {"routine": got.model_dump() if got else None})

    return await _do(request, work)


@router.put("/routines/{rid}", response_model=None)
async def coach_routine_put(
    request: Request, rid: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        saved = await a.routines.put(uid, rid, await _body(request, ROUTINE_MAX))
        return _answer(200, {"saved": {"kind": saved.kind, "rows": len(saved.angles)}})

    return await _do(request, work)


@router.get("/target", response_model=None)
async def coach_target(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        return _answer(200, {"target": (await a.target.get(uid)).model_dump()})

    return await _do(request, work)


@router.put("/target", response_model=None)
async def coach_target_put(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        body = await _body(request)
        if "name" in body:
            if a.lookup is None:
                return _answer(501, {"error": "not_built", "detail": NOT_BUILT})
            found = await resolve_name(uid, str(body["name"]), a.lookup)
            if isinstance(found, str):
                return _answer(404, {"error": "not_enrolled", "detail": found})
            target = found
        else:
            target = TrackTarget.model_validate(body)
        return _answer(200, {"target": (await a.target.set(uid, target)).model_dump()})

    return await _do(request, work)


@router.post("/bp/readings", response_model=None)
async def coach_bp(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        body = await _body(request)
        who, session = str(body.pop("who", "me")), str(body.pop("session", ""))
        confirm = BpConfirm.model_validate(body)  # only a confirmed reading is ever stored (D7)
        kept = await a.store.keep(uid, BP_USE, who, session, confirm.reading.model_dump())
        return _answer(201, {"kept": {"id": kept["id"], "corrected": confirm.corrected}})

    return await _do(request, work)


@router.get("/live", response_model=None)
async def coach_live(
    request: Request, use: str = Query(max_length=21), uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(a: CoachApp) -> JSONResponse:
        if a.home is None:
            return _answer(501, {"error": "not_built", "detail": NOT_BUILT})
        if use not in usecases.BY_ID:
            raise ValueError("use")
        return _answer(200, {"use": use, "bodies": list(a.home.live(uid, use))})

    return await _do(request, work)


__all__ = ["BODY_MAX", "CoachApp", "router"]
