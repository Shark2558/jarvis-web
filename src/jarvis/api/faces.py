# src/jarvis/api/faces.py
"""The Faces panel over HTTP (R3 D13; Layer 1 -> 3). Owner-only: `require_auth` + `current_user`;
cookie writes need `X-Requested-With: JARVIS`; <= 30 changes a minute per owner. Names, relation
and consent records only: this API never receives or returns a picture.

GET  /v1/faces               {available, reason?, people: [PersonView], total, limit, statements}
POST /v1/faces               {name, relation, child, vip, given_by, consent_version, confirm: true}
                             -> 201 {person}; 422 consent_missing / child_needs_guardian / no_name /
                             too_long / bad_relation; 409 people_full / duplicate_name
PATCH /v1/faces/{id}         {name?, relation?, vip?, reconfirm?} -> {person}
POST /v1/faces/{id}/delete   {proof?} -> {id, deleting: true, waiting_for_laptop}. A passkey check
                             made for purpose `privacy_delete`, target `face:<id>` (or, with no
                             passkeys in force, a Google sign-in under 5 minutes old). Console only.
GET  /v1/faces/local         {url: "http://localhost:8098/faces", laptop_online}

PersonView {id, name, relation, child, vip, state: consented | enrolled | deleting, consent_at,
consent_version, renewal_due, pictures, laptop_code}. `laptop_code` is the id the laptop page
shows (the laptop is told ids, never names). Errors {error, detail, reason?}.

`install_faces(app)` mounts the routes. I1 sets `app.state.faces` (a `FacesService`, or None) and
optionally `app.state.faces_laptop` (`async (uid) -> bool`, whether the laptop is online) and
`app.state.permissions`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from jarvis.api.auth import fresh_sign_in_left, require_auth, session_email
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.config import AuthMode
from jarvis.faces import consent
from jarvis.faces.models import CONSENT_VERSION, NAME_MAX
from jarvis.faces.ports import is_person_id
from jarvis.faces.service import FacesService, PersonRejected, PersonView
from jarvis.faces.store import FacesUnavailable
from jarvis.logging import get_logger
from jarvis.permissions.errors import (
    PasskeyDataUnreadable,
    PasskeyRejected,
    PasskeyRequired,
    ProofRequired,
)
from jarvis.permissions.models import PasskeyProof

log = get_logger(__name__)

CHANGES_PER_MINUTE = 30
LOCAL_URL = "http://localhost:8098/faces"
NOT_AVAILABLE = "Not available on this server (no encryption key)."
REAUTH = "Sign in with Google again (within 5 minutes) to delete this person."
PROOF_NEEDED = (
    "Deleting a person needs a passkey or a recent Google sign-in; this server has neither."
)
CONSOLE_ONLY = "Open the JARVIS console in your browser to do this."
router = APIRouter(prefix="/v1/faces", dependencies=[Depends(require_auth)])


class NewPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=NAME_MAX * 4)
    relation: str = Field(max_length=32)
    child: StrictBool = False
    vip: StrictBool = False
    given_by: str = Field(default="self", max_length=32)
    consent_version: str = Field(default="", max_length=16)
    confirm: Any = None  # must be exactly true: checked by the service (consent_missing)


class EditPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=NAME_MAX * 4)
    relation: str | None = Field(default=None, max_length=32)
    vip: StrictBool | None = None
    reconfirm: StrictBool = False


class DeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof: PasskeyProof | None = None


def _svc(request: Request) -> FacesService | None:
    return getattr(request.app.state, "faces", None)


def _need(svc: FacesService | None) -> FacesService:
    if svc is None:
        raise PersonRejected("unavailable", NOT_AVAILABLE, status=503)
    return svc


def _limit(request: Request, uid: str) -> None:
    allowed, _ = request.app.state.faces_limit.allow(uid)
    if not allowed:
        raise PersonRejected("rate_limited", "Too many changes; wait a moment.", status=429)


def _view(p: PersonView) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "relation": p.relation,
        "child": p.child,
        "vip": p.vip,
        "state": p.state,
        "consent_at": p.consent_at,
        "consent_version": p.consent_version,
        "renewal_due": p.renewal_due,
        "pictures": p.pictures,
        "laptop_code": p.id,
    }


def _statements() -> dict[str, Any]:
    return {
        "version": CONSENT_VERSION,
        "adult": consent.statement(CONSENT_VERSION, False),
        "child": consent.statement(CONSENT_VERSION, True),
    }


def _err(status: int, code: str, detail: str, reason: str | None = None) -> JSONResponse:
    body = {"error": code, "detail": detail}
    if reason:
        body["reason"] = reason
    return JSONResponse(status_code=status, content=body)


async def _one(svc: FacesService, uid: str, person_id: str) -> PersonView:
    view = await svc.view(uid)
    found = next((p for p in view.people if p.id == person_id), None)
    if found is None:
        raise PersonRejected("not_found", "There is no such person.", status=404)
    return found


@router.get("")
async def faces_list(
    svc: FacesService | None = Depends(_svc), uid: str = Depends(current_user)
) -> dict[str, Any]:
    if svc is None:
        return {
            "available": False,
            "reason": NOT_AVAILABLE,
            "people": [],
            "total": 0,
            "limit": 30,
            "statements": _statements(),
        }
    view = await svc.view(uid)
    return {
        "available": True,
        "people": [_view(p) for p in view.people],
        "total": view.total,
        "limit": view.limit,
        "statements": _statements(),
    }


@router.get("/local")
async def faces_local(request: Request, uid: str = Depends(current_user)) -> dict[str, Any]:
    probe = getattr(request.app.state, "faces_laptop", None)
    online = False
    if probe is not None:
        try:
            online = bool(await probe(uid))
        except Exception as exc:  # noqa: BLE001 - unknown means "not online"
            log.warning("laptop probe failed", extra={"error": type(exc).__name__})
    return {"url": LOCAL_URL, "laptop_online": online}


@router.post("", response_model=None)
async def faces_add(
    body: NewPerson,
    request: Request,
    svc: FacesService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> JSONResponse:
    s = _need(svc)
    _limit(request, uid)
    person = await s.add(uid, **body.model_dump())
    return JSONResponse(status_code=201, content={"person": _view(await _one(s, uid, person.id))})


@router.patch("/{person_id}")
async def faces_edit(
    person_id: str,
    body: EditPerson,
    request: Request,
    svc: FacesService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    s = _need(svc)
    _limit(request, uid)
    if not is_person_id(person_id):
        raise PersonRejected("not_found", "There is no such person.", status=404)
    await s.update(
        uid,
        person_id,
        name=body.name,
        relation=body.relation,
        vip=body.vip,
        reconfirm=body.reconfirm,
    )
    return {"person": _view(await _one(s, uid, person_id))}


def _proof_failure(exc: Exception) -> JSONResponse:
    if isinstance(exc, PasskeyRequired):
        return _err(403, "passkey_required", str(exc))
    if isinstance(exc, PasskeyRejected):
        return _err(403, "passkey_rejected", str(exc), exc.reason)
    if isinstance(exc, ProofRequired):
        return _err(403, "proof_required", str(exc), exc.reason)
    return _err(503, "passkeys_unreadable", "Your passkeys can't be read right now.")


async def _prove(
    request: Request, uid: str, person_id: str, proof: PasskeyProof | None
) -> str | JSONResponse:
    """Passkey check for exactly (privacy_delete, face:<id>); else a Google sign-in < 5 minutes
    old; token-mode dev only: nothing. Fails closed. Returns the audit note, or the refusal."""
    perms = getattr(request.app.state, "permissions", None)
    if perms is not None:
        try:
            how = await perms.check_purpose(uid, "privacy_delete", f"face:{person_id}", proof)
        except (PasskeyRequired, PasskeyRejected, ProofRequired, PasskeyDataUnreadable) as exc:
            return _proof_failure(exc)
        if how is not None:
            return str(how)
    s = request.app.state.settings
    if s.auth_mode is AuthMode.GOOGLE:
        if not fresh_sign_in_left(request, s):
            return _err(403, "proof_required", REAUTH, "reauth")
        return "sign-in"
    if s.env == "dev":
        return "no passkeys (token-mode dev)"
    return _err(403, "proof_required", PROOF_NEEDED, "reauth")


@router.post("/{person_id}/delete", response_model=None)
async def faces_delete(
    person_id: str,
    request: Request,
    svc: FacesService | None = Depends(_svc),
    uid: str = Depends(current_user),
    body: DeleteBody | None = Body(default=None),  # noqa: B008 - FastAPI's way
) -> JSONResponse | dict[str, Any]:
    s = _need(svc)
    _limit(request, uid)
    settings = request.app.state.settings
    if settings.auth_mode is AuthMode.GOOGLE and session_email(request, settings) is None:
        return _err(403, "console_only", CONSOLE_ONLY)
    if not is_person_id(person_id):
        raise PersonRejected("not_found", "There is no such person.", status=404)
    person = await _one(s, uid, person_id)  # never a proof for someone who isn't there
    if person.state == "deleting":
        return {"id": person_id, "deleting": True, "waiting_for_laptop": True}
    checked = await _prove(request, uid, person_id, body.proof if body else None)
    if isinstance(checked, JSONResponse):
        return checked
    removed = await s.remove(uid, person_id)
    await s.record(uid, "faces_delete", 1, f"person deleted ({checked})")
    return {"id": person_id, "deleting": True, "waiting_for_laptop": not removed.pushed}


def install_faces(app: FastAPI) -> None:
    """Mount /v1/faces, its per-owner change limit and its error mapping on `app`."""
    app.state.faces_limit = RateLimiter(CHANGES_PER_MINUTE)

    @app.exception_handler(PersonRejected)
    async def _rejected(_: Request, exc: PersonRejected) -> JSONResponse:
        return _err(exc.status, exc.code, str(exc))

    @app.exception_handler(FacesUnavailable)
    async def _unavailable(_: Request, exc: FacesUnavailable) -> JSONResponse:
        return _err(503, "unavailable", str(exc))

    app.include_router(router)


__all__ = ["CHANGES_PER_MINUTE", "LOCAL_URL", "install_faces", "router"]
