# src/jarvis/api/phone.py
"""R7 Part C's routes (docs/plans/r7-mobile.md D4-D6, D21). Every answer is `no-store`.

Owner-only console routes (`require_auth`; writes need the CSRF header):
    GET  /v1/phone                       the card: linked phones, a waiting code, the limit
    POST /v1/phone/link-code {id?, proof?}   D5: with passkeys in force, first {needs: passkey,
                                         target: "pl_<12 hex>"}, then the code only for a
                                         `phone_link` check bound to that offer; with none, a
                                         Google sign-in < 5 minutes old. {code, expires_in_s: 600}
    POST /v1/phone/{device}/unlink       the door closes at once (`phone_unlinked`, info)
The session routes (D21; the app lock's own and "Sign out everywhere"):
    POST /v1/session/app                 this cookie session is the installed app's (only ON)
    POST /v1/session/here                "I'm here" (counted by the lock's check, as a write)
    GET  /v1/session/lock                {app, on, armed, waiting, minutes}
    PUT  /v1/session/lock {on, proof?}   ON takes nothing; OFF takes a device_unlock passkey check
                                         ({needs: passkey, target} first)
    POST /v1/session/unlock {proof?}     never locked; locked: {unlocked: false, target: "ss_<24>"}
                                         until a device_unlock check bound to THIS session
(A "first" answer is a 200 carrying the target, because the console's transport keeps only the
error code of a refusal; a proof that fails is a 403.)
    POST /v1/session/end-all             R6's "sessions valid after" mark: every older cookie of
                                         the owner dies within 3 s; this browser is stamped again
Public, cookie-less (D4-D6; never a cookie read or set by the door):
    POST /phone/link                     the app's link request (`PhoneService.link`)
    POST /phone/v1/{hello,health,inbox,sos}   the signed door (`jarvis.phone.door`), then the
                                         handler from `r7_wiring.door_handlers(app)`
    GET  /.well-known/assetlinks.json    linked phones only; the one package and relation
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.api.auth import (
    CSRF_HEADER,
    CSRF_VALUE,
    CSRFRejected,
    cookie_now,
    fresh_sign_in_left,
    require_auth,
    session_email,
)
from jarvis.api.book_show_auth import restamp
from jarvis.api.identity import current_user, user_id_for_email
from jarvis.api.mobile_status import NO_STORE, part_of
from jarvis.api.ratelimit import client_key
from jarvis.config import AuthMode, Settings
from jarvis.logging import get_logger
from jarvis.mobile.ports import DOOR_CAPS, PartName
from jarvis.permissions.errors import (
    PasskeyDataUnreadable,
    PasskeyRejected,
    PasskeyRequired,
    ProofRequired,
)
from jarvis.permissions.groups import PermissionRejected
from jarvis.permissions.models import PasskeyProof
from jarvis.phone.applock import (
    APP_KEY,
    DEVICE_KEY,
    DEVICE_MAX_AGE_S,
    KEEP_ACROSS_RESTAMP,
    ensure_session_id,
)
from jarvis.phone.door import Refusal, refuse, route_of
from jarvis.phone.service import LinkBody, PhoneService, check_link
from jarvis.phone.store import OFFER_ID

log = get_logger(__name__)

PART: PartName = "phone"
JSON_MAX = 64 * 1024
LINK_MAX = 4 * 1024
OFF = "The phone app isn't switched on on this server."
NEEDS_PASSKEY = "Confirm with your passkey to show a link code."
REAUTH = "Sign in with Google again first (it counts for 5 minutes), then press Link a phone."
CONSOLE_ONLY = "This works only in the JARVIS console in your browser."
LOCK_PASSKEY = "Confirm with your passkey to unlock JARVIS on this device."
OFF_PASSKEY = "Confirm with your passkey to switch the lock off."
ENDED = "Every other device is signed out, Sir. This one stays signed in."
BAD_CODE = "That code didn't work. Make a new one in JARVIS: Integrations, Phone app, Link a phone."
LINK_WORDS = {
    "input_rejected": "That isn't a link request JARVIS takes. Update the app and try again.",
    "not_this_app": "Only the JARVIS app can be linked.",
    "bad_key": "The phone's key couldn't be read. Try linking again.",
    "bad_fingerprint": "The app's signature couldn't be read. Reinstall the app and try again.",
}
_PROOF_ERRORS = (PasskeyRequired, PasskeyRejected, ProofRequired, PermissionRejected)

_M = TypeVar("_M", bound=BaseModel)

router = APIRouter()
console = APIRouter(prefix="/v1/phone", dependencies=[Depends(require_auth)])
session_router = APIRouter(prefix="/v1/session")
public = APIRouter()


# ---- small helpers ------------------------------------------------------------------------------
def _json(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _err(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    return _json(status, {"error": code, "detail": detail, **extra})


def _bare(status: int) -> Response:
    return Response(status_code=status, headers=NO_STORE)


def _svc(request: Request) -> PhoneService | None:
    part = part_of(request, PART)
    svc = part.services.get("phone") if part is not None else None
    return svc if isinstance(svc, PhoneService) else None


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


class CodeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = Field(default=None, pattern=OFFER_ID)
    proof: PasskeyProof | None = None


class ProofBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    proof: PasskeyProof | None = None


class LockBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    on: bool
    proof: PasskeyProof | None = None


async def _body(request: Request, model: type[_M], limit: int = JSON_MAX) -> _M | JSONResponse:
    raw = await _capped(request, limit)  # read no further than the cap, then parse
    if raw is None:
        return _err(413, "too_large", "That request is too large.")
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError:
        return _err(422, "input_rejected", "That request isn't one JARVIS takes.")


def _limited(svc: PhoneService, key: str, limits: Any = None) -> JSONResponse | None:
    if (svc.limits if limits is None else limits).allow(key, svc.clock()):
        return None
    return _err(429, "rate_limited", "Too many tries; wait a minute.")


def _cookie_owner(request: Request) -> str | None:
    email = session_email(request, _settings(request))
    return user_id_for_email(email) if email else None


def _proof_refused(exc: Exception, **extra: Any) -> JSONResponse:
    if isinstance(exc, PasskeyRequired):
        return _err(403, "passkey_required", str(exc), **extra)
    reason = getattr(exc, "reason", "")
    return _err(403, "passkey_rejected", str(exc) or "That passkey check didn't work.",
                reason=reason, **extra)  # fmt: skip


async def _in_force(request: Request, uid: str) -> bool:
    perms = getattr(request.app.state, "permissions", None)
    return bool(perms is not None and perms.available and await perms.passkey_required(uid))


# ---- the card -----------------------------------------------------------------------------------
@console.get("")
async def phone_view(request: Request) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        part = part_of(request, PART)
        return _json(200, {"part": PART, "ready": part.ready if part else "not built yet",
                           "enabled": False, "phones": [], "code": None})  # fmt: skip
    return _json(200, {**await svc.view(current_user(request)), "enabled": True})


@console.post("/link-code")
async def link_code(request: Request) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return _err(404, "mobile_off", OFF)
    uid, s = current_user(request), _settings(request)
    if (r := _limited(svc, f"code:{uid}", svc.code_limits)) is not None:
        return r
    body = await _body(request, CodeBody)
    if isinstance(body, JSONResponse):
        return body
    how, offer = await _code_proof(request, svc, uid, s, body)
    if isinstance(how, JSONResponse):
        return how
    issued = await svc.issue(uid, offer)
    if issued == "expired":
        return _err(409, "offer_expired", "That took too long. Press Link a phone again.")
    if not isinstance(issued, dict):
        return _err(409, "offer_unknown", "Press Link a phone again.")
    await svc.audit("phone_link_code", {"how": how})
    return _json(200, issued)


async def _code_proof(
    request: Request, svc: PhoneService, uid: str, s: Settings, body: CodeBody
) -> tuple[str | JSONResponse, str]:
    """(how the owner proved it, the offer id) or a refusal: a phone_link passkey check bound to
    the offer; with no passkey in force, a fresh Google sign-in; token-mode dev for the tests."""
    if s.auth_mode is not AuthMode.GOOGLE:
        if s.env == "dev":
            return "token-mode dev", await svc.offer(uid)
        return _err(403, "console_only", CONSOLE_ONLY), ""
    try:
        in_force = await _in_force(request, uid)
    except PasskeyDataUnreadable:
        in_force = True
    if in_force:
        if body.id is None or body.proof is None:
            target = await svc.offer(uid)
            return _json(200, {"needs": "passkey", "target": target, "detail": NEEDS_PASSKEY}), ""
        perms = request.app.state.permissions
        try:
            how = await perms.check_purpose(uid, "phone_link", body.id, body.proof)
        except _PROOF_ERRORS as exc:
            return _proof_refused(exc), ""
        except PasskeyDataUnreadable:
            return _err(503, "passkeys_unreadable", "Your passkey data can't be read."), ""
        if how is not None:
            return str(how), body.id
    if not fresh_sign_in_left(request, s):
        return _err(403, "reauth_required", REAUTH), ""
    return "fresh sign-in", await svc.offer(uid)


@console.post("/{device_id}/unlink")
async def unlink(request: Request, device_id: str) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return _err(404, "mobile_off", OFF)
    if not await svc.unlink(current_user(request), device_id):
        return _err(404, "not_found", "That phone isn't linked.")
    return _json(200, {"unlinked": True})


# ---- the session routes (D21) -------------------------------------------------------------------
def _csrf(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise CSRFRejected()


@session_router.post("/app", dependencies=[Depends(require_auth)])
async def mark_app(request: Request) -> JSONResponse:
    # I1 fixer (security L3): only the page's own call (same-origin) or a browser-started one (none; the app's
    # first launch) marks the app; a header that says "cross-site" or "same-site" marks nothing, sets no cookie.
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return _json(200, {"app": False})
    svc = _svc(request)
    uid = _cookie_owner(request) if "session" in request.scope else None
    if svc is None or uid is None:
        return _json(200, {"app": False})
    await svc.lock.mark_app(request.session, uid)
    reply = _json(200, {"app": True})
    # the lock follows the DEVICE (security review H1): sign-out and expiry never clear this cookie
    reply.set_cookie(
        DEVICE_KEY,
        svc.lock.device_cookie_value(uid),
        max_age=DEVICE_MAX_AGE_S,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_settings(request).cookie_secure,
    )
    return reply


@session_router.post("/here", dependencies=[Depends(require_auth)])
async def here() -> JSONResponse:
    return _json(200, {"ok": True})  # the lock's check already counted this write


async def _lock_state(request: Request, svc: PhoneService, uid: str) -> dict[str, Any]:
    on, _ = await svc.lock.app_keys(uid)
    armed = await svc.lock.armed(uid)
    app = "session" in request.scope and bool(request.session.get(APP_KEY))
    return {"app": app, "on": on, "armed": armed, "waiting": on and not armed,
            "minutes": svc.s.app_lock_minutes}  # fmt: skip


@session_router.get("/lock", dependencies=[Depends(require_auth)])
async def lock_view(request: Request) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return _err(404, "mobile_off", OFF)
    return _json(200, await _lock_state(request, svc, current_user(request)))


@session_router.put("/lock", dependencies=[Depends(require_auth)])
async def lock_switch(request: Request) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return _err(404, "mobile_off", OFF)
    uid = current_user(request)
    body = await _body(request, LockBody)
    if isinstance(body, JSONResponse):
        return body
    try:
        needs_proof = not body.on and await _in_force(request, uid)
    except PasskeyDataUnreadable:
        return _err(503, "passkeys_unreadable", "Your passkey data can't be read.")
    if needs_proof:
        if "session" not in request.scope or _cookie_owner(request) is None:
            return _err(403, "console_only", CONSOLE_ONLY)
        if (r := _limited(svc, f"switch:{uid}")) is not None:
            return r
        target = ensure_session_id(request.session)
        if body.proof is None:
            state = await _lock_state(request, svc, uid)
            return _json(
                200, {**state, "needs": "passkey", "target": target, "detail": OFF_PASSKEY}
            )
        try:
            how = await request.app.state.permissions.check_purpose(
                uid, "device_unlock", target, body.proof
            )
        except _PROOF_ERRORS as exc:
            return _proof_refused(exc, target=target)
        except PasskeyDataUnreadable:
            return _err(503, "passkeys_unreadable", "Your passkey data can't be read.")
        await svc.audit("app_lock_off", {"how": str(how)})
    await svc.store.set_lock(uid, body.on)
    svc.lock.forget(uid)
    return _json(200, await _lock_state(request, svc, uid))


@session_router.post("/unlock")
async def unlock(request: Request) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return _err(404, "mobile_off", OFF)
    uid = _cookie_owner(request) if "session" in request.scope else None
    if uid is None:
        if request.headers.get("authorization"):
            return _err(403, "console_only", CONSOLE_ONLY)
        return _err(401, "unauthorized", "Sign in required.")
    _csrf(request)
    target = ensure_session_id(request.session)
    if (r := _limited(svc, f"unlock:{target}")) is not None:
        return r
    body = await _body(request, ProofBody)
    if isinstance(body, JSONResponse):
        return body
    now = svc.clock()
    if not await svc.lock.locked(request.session, uid):
        svc.lock.touch(request.session, now)
        return _json(200, {"unlocked": True})
    if body.proof is None:
        return _json(200, {"unlocked": False, "target": target, "detail": LOCK_PASSKEY})
    try:
        how = await request.app.state.permissions.check_purpose(
            uid, "device_unlock", target, body.proof
        )
    except _PROOF_ERRORS as exc:
        return _proof_refused(exc, target=target)
    except PasskeyDataUnreadable:
        return _err(503, "passkeys_unreadable", "Your passkey data can't be read.")
    await svc.audit("device_unlock", {"how": str(how) if how else "no passkey in force"})
    svc.lock.touch(request.session, svc.clock())
    return _json(200, {"unlocked": True})


@session_router.post("/end-all")
async def end_all(request: Request) -> JSONResponse:
    s, svc = _settings(request), _svc(request)
    if s.auth_mode is not AuthMode.GOOGLE:
        return _err(409, "needs_google", "Signing out everywhere needs Google sign-in.")
    uid = _cookie_owner(request) if "session" in request.scope else None
    if uid is None:
        return _err(401, "unauthorized", "Sign in required.")
    _csrf(request)
    lock = getattr(request.app.state, "book_lock", None)
    end = getattr(lock, "end_sessions", None)
    if not callable(end):
        return _err(503, "unavailable", "JARVIS can't sign out everywhere right now.")
    mark = cookie_now()
    await end(uid, before=mark)
    kept = {k: request.session[k] for k in KEEP_ACROSS_RESTAMP if k in request.session}
    restamp(request.session, s, uid, mark)  # every older cookie dies; this browser goes on
    request.session.update(kept)  # ...and stays the app's, with its id and its last "I'm here"
    if svc is not None:
        await svc.audit("sessions_end_all", {"at": int(mark)})
    return _json(200, {"ended": True, "detail": ENDED})


# ---- the phone's own routes: no cookie, no header but the door's (D4-D6) -----------------------
@public.post("/phone/link")
async def phone_link(request: Request) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return _err(404, "mobile_off", OFF)
    now = svc.clock()
    if not svc.link_clients.allow(client_key(request), now) or not svc.link_all.allow("*", now):
        return _err(429, "rate_limited", "Too many tries; wait a minute.")
    body = await _body(request, LinkBody, LINK_MAX)
    if isinstance(body, JSONResponse):
        return body
    error, key, fingerprint = check_link(body)
    if error is not None:
        return _err(422, error, LINK_WORDS[error])
    out = await svc.link(body, key, fingerprint)
    if out.result == "bad_code":
        return _err(403, "bad_code", BAD_CODE)
    if out.result == "too_many":
        n = svc.s.phone_link_max
        return _err(409, "too_many_phones", f"{n} phones are linked already. Unlink one first.")
    if out.result == "already_linked" or out.phone is None:
        return _err(409, "already_linked", "This phone is linked already.")
    return _json(200, {"device_id": out.phone.id})


def _ascii_number(text: str) -> bool:
    """Only 0-9 (`str.isdigit` also says yes to "\u00b2", which `int` then refuses)."""
    return 0 < len(text) <= 12 and all("0" <= c <= "9" for c in text)


async def _capped(request: Request, cap: int) -> bytes | None:
    """The body, or None past the cap (read no further than the cap)."""
    length = request.headers.get("content-length")
    if length is not None and (not _ascii_number(length) or int(length) > cap):
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@public.api_route("/phone/v1/{route}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def phone_door(request: Request, route: str) -> Response:
    svc = _svc(request)
    name = route_of(request.method, request.scope.get("path", ""))
    if svc is None or name is None:
        return _bare(404)
    if request.scope.get("query_string") or b"?" in request.scope.get("raw_path", b""):
        return _bare(refuse("query", name).status)
    if "cookie" in request.headers:
        return _bare(refuse("cookie", name).status)
    try:
        pre = await svc.gate.precheck(name, request.headers.getlist("x-jarvis-phone"),
                                      client_key(request))  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - the phone store can't be read: never "admitted"
        log.error("phone door unreadable", extra={"route": name, "error": type(exc).__name__})
        return _bare(503)
    if isinstance(pre, Refusal):
        return _bare(pre.status)
    body = await _capped(request, DOOR_CAPS[name])  # only now is a body byte read
    if body is None:
        return _bare(refuse("cap", name).status)
    got = svc.gate.finish(pre, name, body)
    if isinstance(got, Refusal):
        return _bare(got.status)
    from jarvis.api.r7_wiring import door_handlers  # late: r7_wiring imports this module

    handler = door_handlers(request.app).get(name)
    if handler is None:
        return _bare(refuse("not_built", name, 404).status)
    await svc.handlers.seen(got)  # best-effort: it never refuses an admitted request (SOS too)
    try:
        reply = await handler(got)
    except Exception as exc:  # noqa: BLE001 - a handler that fails answers plainly, logged by kind
        log.error("phone door handler failed", extra={"route": name, "error": type(exc).__name__})
        return _err(503, "unavailable", "JARVIS couldn't take that just now. Try again later.")
    return _json(reply.status, dict(reply.body))


@public.get("/.well-known/assetlinks.json")
async def asset_links(request: Request) -> Response:
    svc = _svc(request)
    if svc is None:
        return _bare(404)
    return JSONResponse(await svc.asset_links(), headers={"Cache-Control": "public, max-age=60"})


router.include_router(console)
router.include_router(session_router)
router.include_router(public)

__all__ = ["PART", "router"]
