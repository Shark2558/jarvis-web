# src/jarvis/api/belongings.py
"""Things ("Where did I keep it?") over HTTP (R2 D11; Layer 1 -> 3). Owner-only: `require_auth` +
`current_user`; cookie writes need `X-Requested-With: JARVIS`; <= 60 changes a minute per owner.
Everything is encrypted by JARVIS in storage; without an encryption key the list says so.

GET    /v1/things?q=        {available, reason?, things: [ThingView], holders: [label], total}
POST   /v1/things           {name, place, note?, holder?} adds or moves -> 201 / 200 {thing,
                            previous_place, moved}
PATCH  /v1/things/{id}      {name?, place?, note?, holder?} -> {thing, previous_place, moved}
DELETE /v1/things/{id}      -> {undo_id, kind: "thing", title}   (Recently deleted, 30 days)
GET    /v1/things/{id}/history  {thing, earlier: [{place, from_at, to_at}]}  (<= 10)
GET    /v1/things/export    JSON attachment of every thing and its history (console only: a bearer
                            token alone gets 403 console_only when Google sign-in is in force)

ThingView {id, name, place, note, holder, updated_at, moves}. Errors {error, detail}: 404
not_found, 409 things_full / holders_full, 422 no_name / no_place / too_long / sensitive, 503
unavailable. Stored text is the owner's own and is shown with textContent.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth, session_email
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.belongings.models import HOLDER_MAX, NAME_MAX, NOTE_MAX, PLACE_MAX, State, Thing
from jarvis.belongings.service import BelongingsService, PutResult, ThingRejected
from jarvis.belongings.store import ThingsUnavailable
from jarvis.config import AuthMode, Settings
from jarvis.logging import get_logger, get_trace_id

log = get_logger(__name__)

CHANGES_PER_MINUTE = 60
NOT_AVAILABLE = "Not available on this server (no encryption key)."
router = APIRouter(prefix="/v1/things", dependencies=[Depends(require_auth)])


class NewThing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=NAME_MAX * 4)
    place: str = Field(max_length=PLACE_MAX * 4)
    note: str | None = Field(default=None, max_length=NOTE_MAX * 4)
    holder: str | None = Field(default=None, max_length=HOLDER_MAX * 4)


class EditThing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=NAME_MAX * 4)
    place: str | None = Field(default=None, max_length=PLACE_MAX * 4)
    note: str | None = Field(default=None, max_length=NOTE_MAX * 4)
    holder: str | None = Field(default=None, max_length=HOLDER_MAX * 4)


def _svc(request: Request) -> BelongingsService | None:
    return getattr(request.app.state, "belongings", None)


def _need(svc: BelongingsService | None) -> BelongingsService:
    if svc is None:
        raise ThingRejected("unavailable", NOT_AVAILABLE, status=503)
    return svc


def _view(t: Thing, state: State) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "place": t.place,
        "note": t.note,
        "holder": state.holder_label(t.holder_id),
        "updated_at": t.updated_at,
        "moves": t.moves,
    }


def _put_view(got: PutResult, state: State) -> dict[str, Any]:
    return {
        "thing": _view(got.thing, state),
        "previous_place": got.previous_place,
        "moved": got.moved,
    }


def _limit(request: Request, uid: str) -> None:
    allowed, _ = request.app.state.belongings_limit.allow(uid)
    if not allowed:
        raise ThingRejected("rate_limited", "Too many changes; wait a moment.", status=429)


@router.get("")
async def things_list(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    svc: BelongingsService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    if svc is None:
        return {
            "available": False,
            "reason": NOT_AVAILABLE,
            "things": [],
            "holders": [],
            "total": 0,
        }
    items, state = await svc.list(uid, q=q, limit=500)
    return {
        "available": True,
        "things": [_view(t, state) for t in items],
        "holders": [h.label for h in state.holders],
        "total": len(state.live()),
    }


@router.post("", response_model=None)
async def things_put(
    body: NewThing,
    request: Request,
    svc: BelongingsService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> JSONResponse:
    s = _need(svc)
    _limit(request, uid)
    got = await s.put(uid, body.name, body.place, note=body.note, holder=body.holder)
    return JSONResponse(
        status_code=201 if got.created else 200, content=_put_view(got, await s.state(uid))
    )


@router.get("/export", response_model=None)
async def things_export(
    request: Request,
    svc: BelongingsService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> Response:
    s = _need(svc)
    settings: Settings = request.app.state.settings
    if settings.auth_mode is AuthMode.GOOGLE and session_email(request, settings) is None:
        raise ThingRejected(
            "console_only", "Export is only available from the signed-in console.", status=403
        )
    data = await s.export(uid)
    await record_change(
        request,
        agent="owner",
        tool="things_export",
        args={"count": len(data["things"])},
        detail="exported",
    )
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="jarvis-things.json"',
            "Cache-Control": "no-store",
        },
    )


@router.patch("/{thing_id}")
async def things_edit(
    thing_id: str,
    body: EditThing,
    request: Request,
    svc: BelongingsService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    s = _need(svc)
    _limit(request, uid)
    got = await s.update(
        uid, thing_id, name=body.name, place=body.place, note=body.note, holder=body.holder
    )
    return _put_view(got, await s.state(uid))


@router.delete("/{thing_id}")
async def things_remove(
    thing_id: str,
    request: Request,
    svc: BelongingsService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    s = _need(svc)
    _limit(request, uid)
    trace = get_trace_id()
    thing, kept = await s.remove(uid, thing_id, trace_id=None if trace == "-" else trace)
    return {"undo_id": kept.id, "kind": "thing", "title": kept.title, "id": thing.id}


@router.get("/{thing_id}/history")
async def things_history(
    thing_id: str,
    request: Request,
    svc: BelongingsService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    s = _need(svc)
    thing, moves, state = await s.history(uid, thing_id)
    return {
        "thing": _view(thing, state),
        "earlier": [{"place": m.place, "from_at": m.from_at, "to_at": m.to_at} for m in moves],
    }


def install_belongings(app: FastAPI) -> None:
    """Mount /v1/things, its per-owner change limit and its error mapping on `app`. The service
    is `app.state.belongings` (None: the routes say it is not available)."""
    app.state.belongings_limit = RateLimiter(CHANGES_PER_MINUTE)

    @app.exception_handler(ThingRejected)
    async def _rejected(_: Request, exc: ThingRejected) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "detail": str(exc)})

    @app.exception_handler(ThingsUnavailable)
    async def _unavailable(_: Request, exc: ThingsUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": "unavailable", "detail": str(exc)})

    app.include_router(router)


__all__ = ["CHANGES_PER_MINUTE", "install_belongings", "router"]
