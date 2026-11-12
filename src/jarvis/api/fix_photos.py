# src/jarvis/api/fix_photos.py
"""R11.1 Part C's routes, under `/v1/facegroups` (docs/plans/r11-1-observations.md D14, D15,
D21-C). Owner-only (`require_auth`; cookie writes need `X-Requested-With: JARVIS`), `no-store`,
changes rate-limited per owner. They read the part's services from
`app.state.r111_parts["photos"].services` per request. Ids and counts only: this API never
receives or returns a picture, a crop or an embedding.

GET    /v1/facegroups                      {part, ready}: the part's status
GET    /v1/facegroups/groups               {available, reason?, laptop: online | offline | off,
                                           heard_at, groups: [{id, n, photos, first, last}],
                                           strays, named, engine_ready, folder, read, keep_days,
                                           names_waiting, forgets_waiting, local_url,
                                           skipped, store_ok, names_lost, min_photos}
POST   /v1/facegroups/groups/{id}/name     EITHER {name, relation, child, vip, given_by,
                                           consent_version, confirm: true} (a new person: the
                                           consent check) OR {person_id} (someone already added)
                                           -> {person_id, at_home, contact_matched}; 422
                                           consent_missing / child_needs_guardian; 404 unknown_face
POST   /v1/facegroups/groups/{id}/forget   -> {done, forgotten, left}; done is true only when
                                           the laptop confirmed it (false: it waits for the laptop)
GET    /v1/facegroups/import               {status, photos, total, faces_found, unknown, skipped,
                                           over, line, recognised: [{name, child}]}
POST   /v1/facegroups/import/step          one step of the import now -> the same shape
DELETE /v1/facegroups/import               stop the import -> {status: "no_session"}
Errors {error, detail}: 404 unknown, 409 photos_unavailable, 429 rate_limited, 503 unavailable.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.facegroups.part import PHOTOS_OFF
from jarvis.facegroups.service import FaceGroupsService, Forgotten, GroupsView
from jarvis.faces.models import NAME_MAX
from jarvis.faces.ports import FAMILY_CHILD
from jarvis.faces.service import PersonRejected
from jarvis.faces.store import FacesUnavailable
from jarvis.fixes.ports import NOT_BUILT, ROUTE_PREFIX, FixPart, PartName
from jarvis.homebridge.face_types import MIN_GROUP_PICS
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected
from jarvis.photos.errors import PickerError
from jarvis.photos.models import CLUSTER_ID, ImportResult
from jarvis.photos.picker import PhotosNotGranted
from jarvis.photos.service import NoSession, PhotosService

PART: PartName = "photos"
PREFIX = ROUTE_PREFIX[PART]
NO_STORE = {"Cache-Control": "no-store"}
LOCAL_URL = "http://localhost:8098/faces"
RATE = "Too many changes; wait a moment."
PANEL_STEP_S = 20.0
NO_GROUP = "There is no such group."
_PROBLEMS = (GoogleAPIError, GoogleNotConnected, PhotosNotGranted, PickerError, NoSession)
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])


class NameBody(BaseModel):
    """A new person (with the consent statement), or `person_id` of someone already added."""

    model_config = ConfigDict(extra="forbid")
    person_id: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=NAME_MAX * 4)
    relation: str = Field(default="family", max_length=32)
    child: StrictBool = False
    vip: StrictBool = False
    given_by: str = Field(default="self", max_length=32)
    consent_version: str = Field(default="", max_length=16)
    confirm: Any = None  # must be exactly true: the faces service checks (consent_missing)

    @model_validator(mode="after")
    def _one_way(self) -> NameBody:
        if (self.person_id is None) == (self.name is None):
            raise ValueError("give a name, or the person already added")
        return self


def part_of(request: Request) -> FixPart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r111_parts", None) or {}
    return parts.get(PART)


def _reply(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _err(status: int, code: str, detail: str) -> JSONResponse:
    return _reply({"error": code, "detail": detail}, status)


def _groups(request: Request) -> FaceGroupsService | None:
    part = part_of(request)
    found = part.services.get("groups") if part is not None else None
    return found if isinstance(found, FaceGroupsService) else None


def _photos(request: Request) -> PhotosService | None:
    part = part_of(request)
    find = part.services.get("photos") if part is not None else None
    return find() if callable(find) else None


def _limited(request: Request, uid: str) -> bool:
    part = part_of(request)
    limiter = part.services.get("limit") if part is not None else None
    return limiter is not None and not limiter.allow(uid)[0]


def _view(view: GroupsView) -> dict[str, Any]:
    return {
        "available": view.available,
        "reason": view.reason,
        "laptop": view.laptop,
        "heard_at": view.heard_at,
        "groups": [
            {"id": g.id, "n": g.n, "photos": g.photos, "first": g.first, "last": g.last}
            for g in view.groups
        ],
        "strays": view.strays,
        "named": view.named,
        "engine_ready": view.engine_ready,
        "folder": view.folder,
        "read": view.read,
        "keep_days": view.keep_days,
        "names_waiting": view.names_waiting,
        "forgets_waiting": view.forgets_waiting,
        "local_url": LOCAL_URL,
        "skipped": view.skipped,
        "store_ok": view.store_ok,
        "names_lost": view.names_lost,
        "min_photos": MIN_GROUP_PICS,
    }


def _progress(res: ImportResult) -> dict[str, Any]:
    return {
        "status": res.status,
        "photos": res.photos,
        "total": res.total,
        "faces_found": res.faces_found,
        "unknown": res.unknown,
        "skipped": res.skipped,
        "over": res.over,
        "line": res.line,
        "picker_uri": res.picker_uri,
        "recognised": [
            {"name": FAMILY_CHILD if p.child else p.name, "child": p.child}  # R4 D-C4
            for p in res.recognised
        ],
    }


@router.get("")
async def status(request: Request) -> JSONResponse:
    part = part_of(request)
    ready = part.ready if part is not None else NOT_BUILT
    if part is not None and part.services and _photos(request) is None:
        ready = PHOTOS_OFF
    return _reply({"part": PART, "ready": ready})


@router.get("/groups")
async def groups_list(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = _groups(request)
    if svc is None:
        return _reply(_view(GroupsView(False, reason=NOT_BUILT)))
    return _reply(_view(await svc.view(uid)))


@router.post("/groups/{group}/name")
async def group_name(
    group: str, body: NameBody, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    svc = _groups(request)
    if svc is None:
        return _err(503, "unavailable", NOT_BUILT)
    if _limited(request, uid):
        return _err(429, "rate_limited", RATE)
    if not CLUSTER_ID.fullmatch(group):
        return _err(404, "unknown_face", NO_GROUP)
    try:
        if body.person_id is not None:
            done = await svc.name_existing(uid, group, body.person_id)
        else:
            fields = body.model_dump(exclude={"person_id"})
            done = await svc.name(uid, group, **fields)
    except PersonRejected as exc:
        return _err(exc.status, exc.code, str(exc))
    except FacesUnavailable as exc:
        return _err(503, "unavailable", str(exc))
    return _reply(
        {
            "person_id": done.person.id,
            "at_home": done.at_home,
            "contact_matched": done.contact_matched,
        }
    )


def _forgot(done: Forgotten) -> dict[str, Any]:
    return {"done": done.done, "forgotten": done.forgotten, "left": done.left}


@router.post("/groups/{group}/forget")
async def group_forget(
    group: str, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    svc = _groups(request)
    if svc is None:
        return _err(503, "unavailable", NOT_BUILT)
    if _limited(request, uid):
        return _err(429, "rate_limited", RATE)
    if not CLUSTER_ID.fullmatch(group):
        return _err(404, "unknown_face", NO_GROUP)
    try:
        return _reply(_forgot(await svc.forget(uid, group)))
    except PersonRejected as exc:
        return _err(exc.status, exc.code, str(exc))


@router.get("/import")
async def import_progress(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    photos = _photos(request)
    if photos is None:  # R11.1 I1: a read answers the state, as /groups does (no 503 to log)
        return _reply({"status": "off", "available": False, "reason": PHOTOS_OFF})
    return _reply(_progress(await photos.progress(uid)))


@router.post("/import/step")
async def import_step(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    photos = _photos(request)
    if photos is None:
        return _err(503, "unavailable", PHOTOS_OFF)
    if _limited(request, uid):
        return _err(429, "rate_limited", RATE)
    try:
        # a short step, so the open panel's line moves; the panel asks again 5 s later
        return _reply(_progress(await photos.collect(uid, budget_s=PANEL_STEP_S)))
    except _PROBLEMS as exc:
        return _err(409, "photos_unavailable", str(exc))


@router.delete("/import")
async def import_stop(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    photos = _photos(request)
    if photos is None:
        return _err(503, "unavailable", PHOTOS_OFF)
    if _limited(request, uid):
        return _err(429, "rate_limited", RATE)
    await photos.stop(uid)
    return _reply(_progress(await photos.progress(uid)))


__all__ = ["LOCAL_URL", "PREFIX", "part_of", "router"]
