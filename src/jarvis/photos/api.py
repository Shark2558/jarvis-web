# src/jarvis/photos/api.py
"""The Connectors panel over HTTP (R4 D8, D9). Owner-only (`require_auth`); cookie writes need
`X-Requested-With: JARVIS` (the app's CSRF middleware); <= 20 changes a minute per owner.

GET    /v1/connectors                 {github: {connected, login}, youtube: {connected, reason},
                                       photos: {connected, reason}, statements: {adult, child}}
PUT    /v1/connectors/github          {token} -> {connected, login}; the token is checked with
                                       GitHub, stored encrypted, never returned or logged
DELETE /v1/connectors/github          -> {connected: false}
POST   /v1/connectors/photos/start    -> {picker_uri}
POST   /v1/connectors/photos/import   -> {status, photos, faces_found, recognised: [{name, child}],
                                       unknown: [cluster ids], skipped}
POST   /v1/connectors/photos/enrol    {cluster, name, relation, child, vip, given_by,
                                       consent_version, confirm: true} -> {person_id, at_home,
                                       contact_matched}; 422 consent_missing / child_needs_guardian
Errors: {error, detail}. `install_connectors(app)` mounts it; the integrator sets
`app.state.connectors` (a `ConnectorDeps`) and `app.state.connectors_limit` is made here.
Pictures never pass through this API.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool

from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.faces import consent
from jarvis.faces.models import CONSENT_VERSION, NAME_MAX
from jarvis.faces.service import PersonRejected
from jarvis.integrations.github import MAX_TOKEN_CHARS, GithubError
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected
from jarvis.integrations.youtube import YouTubeNotGranted
from jarvis.logging import get_logger
from jarvis.photos.edge import EdgeOffline
from jarvis.photos.picker import PhotosNotGranted, PickerError
from jarvis.photos.service import NoSession
from jarvis.photos.tools import ConnectorDeps

log = get_logger(__name__)

CHANGES_PER_MINUTE = 20
NOT_BUILT = "This connector isn't available on this server."
RATE = "Too many changes; wait a moment."
_PROBLEMS = (
    GithubError,
    GoogleAPIError,
    GoogleNotConnected,
    YouTubeNotGranted,
    PhotosNotGranted,
    PickerError,
    NoSession,
    EdgeOffline,
)


def _deps(request: Request) -> ConnectorDeps:
    found = getattr(request.app.state, "connectors", None)
    return found if isinstance(found, ConnectorDeps) else ConnectorDeps(None, None, None)


def _err(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


def _limited(request: Request, uid: str) -> bool:
    limiter = getattr(request.app.state, "connectors_limit", None)
    return limiter is not None and not limiter.allow(uid)[0]


class GithubBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(max_length=MAX_TOKEN_CHARS * 2)


class EnrolBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cluster: str = Field(max_length=40)
    name: str = Field(max_length=NAME_MAX * 4)
    relation: str = Field(max_length=32)
    child: StrictBool = False
    vip: StrictBool = False
    given_by: str = Field(default="self", max_length=32)
    consent_version: str = Field(default="", max_length=16)
    confirm: Any = None  # must be exactly true: the faces service checks (consent_missing)


router = APIRouter(prefix="/v1/connectors")


def _auth_router() -> APIRouter:
    from jarvis.api.auth import require_auth

    r = APIRouter(dependencies=[Depends(require_auth)])
    r.include_router(router)
    return r


async def _status(request: Request, uid: str) -> dict[str, Any]:
    d = _deps(request)
    off = {"connected": False, "reason": "unavailable"}
    out: dict[str, Any] = {
        "github": await d.github.status(uid) if d.github else {"connected": False, "login": None},
        "youtube": await d.youtube.status(uid) if d.youtube else off,
        "photos": off,
        "statements": {
            "adult": consent.statement(CONSENT_VERSION, False),
            "child": consent.statement(CONSENT_VERSION, True),
            "version": CONSENT_VERSION,
        },
    }
    picker = getattr(d.photos, "_picker", None)
    if picker is not None and hasattr(picker, "status"):
        out["photos"] = await picker.status(uid)
    return out


@router.get("")
async def connectors_status(request: Request, uid: str = Depends(current_user)) -> dict[str, Any]:
    try:
        return await _status(request, uid)
    except _PROBLEMS as exc:
        return {"error": "unavailable", "detail": str(exc)}


@router.put("/github", response_model=None)
async def github_connect(
    body: GithubBody, request: Request, uid: str = Depends(current_user)
) -> JSONResponse | dict[str, Any]:
    gh = _deps(request).github
    if gh is None:
        return _err(503, "unavailable", NOT_BUILT)
    if _limited(request, uid):
        return _err(429, "rate_limited", RATE)
    try:
        login = await gh.connect(uid, body.token)
    except GithubError as exc:
        return _err(422, "github_refused", str(exc))
    return {"connected": True, "login": login}


@router.delete("/github", response_model=None)
async def github_disconnect(
    request: Request, uid: str = Depends(current_user)
) -> JSONResponse | dict[str, Any]:
    gh = _deps(request).github
    if gh is None:
        return _err(503, "unavailable", NOT_BUILT)
    await gh.disconnect(uid)
    return {"connected": False}


@router.post("/photos/start", response_model=None)
async def photos_start(
    request: Request, uid: str = Depends(current_user)
) -> JSONResponse | dict[str, Any]:
    svc = _deps(request).photos
    if svc is None:
        return _err(503, "unavailable", NOT_BUILT)
    if _limited(request, uid):
        return _err(429, "rate_limited", RATE)
    try:
        session = await svc.begin(uid)
    except _PROBLEMS as exc:
        return _err(409, "photos_unavailable", str(exc))
    return {"picker_uri": session.picker_uri}


@router.post("/photos/import", response_model=None)
async def photos_import(
    request: Request, uid: str = Depends(current_user)
) -> JSONResponse | dict[str, Any]:
    svc = _deps(request).photos
    if svc is None:
        return _err(503, "unavailable", NOT_BUILT)
    if _limited(request, uid):
        return _err(429, "rate_limited", RATE)
    try:
        res = await svc.collect(uid)
    except _PROBLEMS as exc:
        return _err(409, "photos_unavailable", str(exc))
    return {
        "status": res.status,
        "photos": res.photos,
        "faces_found": res.faces_found,
        "skipped": res.skipped,
        "recognised": [{"name": p.name, "child": p.child} for p in res.recognised],
        "unknown": list(res.unknown_clusters),
    }


@router.post("/photos/enrol", response_model=None)
async def photos_enrol(
    body: EnrolBody, request: Request, uid: str = Depends(current_user)
) -> JSONResponse | dict[str, Any]:
    svc = _deps(request).photos
    if svc is None:
        return _err(503, "unavailable", NOT_BUILT)
    if _limited(request, uid):
        return _err(429, "rate_limited", RATE)
    fields = body.model_dump()
    cluster = fields.pop("cluster")
    try:
        done = await svc.enrol(uid, cluster, **fields)
    except PersonRejected as exc:
        return _err(exc.status, exc.code, str(exc))
    return {
        "person_id": done.person.id,
        "at_home": done.at_home,
        "contact_matched": done.contact_matched,
    }


def install_connectors(app: FastAPI) -> None:
    app.state.connectors_limit = RateLimiter(CHANGES_PER_MINUTE)
    app.include_router(_auth_router())


__all__ = ["install_connectors", "router"]
