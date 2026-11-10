# src/jarvis/api/book_show_access.py
"""Who may open the build book, and who may lift a guest lock (R6 D8, D10; used by
api/book_show.py). Every refusal and every grant is audited first (content-free).

Open (`POST /v1/book/open {proof, audience}`), in this order:
  console only (a signed-in browser; token-mode dev only for the owner) -> 5 a minute -> a book
  on this server (404 no_book) -> Google mode: passkeys in force (403 passkey_setup_needed; NEVER
  a sign-in-only fallback) -> a Google sign-in from the last 5 minutes (403 reauth_required) ->
  `check_purpose(uid, "book_open", audience, proof)` (the proof is bound to its audience) ->
  audit -> open. Token mode has no guest lock, so a guest open is 409 guest_needs_google. A guest
  open consumes this browser's fresh sign-in: the guest can't use it for anything (a passkey
  reset, say) while the owner's back is turned.

Resume (`POST /v1/book/resume {proof}`): a signed-in browser of the owner whose lock it is ->
`check_purpose(uid, "book_resume", lock_id, proof)` -> audit -> lift + end the live session.
Without a proof the answer carries `lock_id` (the target the console proves). Only when NO
passkey is in force any more (the 24-hour passkey reset, the one recovery for a passkey lost
mid-show, has completed) does a Google sign-in from the last 5 minutes lift it instead: the
same proof the reset itself needed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from jarvis.api.auth import SESSION_AUTH_AT_KEY, fresh_sign_in_left, session_email
from jarvis.api.book_http import book_err, book_json
from jarvis.api.book_lock import GUEST_FLAG
from jarvis.buildbook.model import Audience
from jarvis.buildbook.ports import BookOff, LockUnreadable
from jarvis.buildbook.service import BookService
from jarvis.config import AuthMode, Settings
from jarvis.logging import get_logger
from jarvis.permissions.errors import (
    PasskeyDataUnreadable,
    PasskeyRejected,
    PasskeyRequired,
    ProofRequired,
)
from jarvis.permissions.groups import PermissionRejected
from jarvis.permissions.models import PasskeyProof
from jarvis.permissions.service import PermissionsService

log = get_logger(__name__)

MAX_JSON_BYTES = 64 * 1024
CONSOLE_ONLY = "The build book opens only in the JARVIS console, not from a script."
NO_BOOK = "This server has no build book."
SETUP = "Set up a passkey in Approvals → Permissions first: the build book opens only with one."
REAUTH = "Sign in with Google again to open the build book (it counts for 5 minutes)."
REAUTH_RESUME = "Sign in with Google again to unlock JARVIS (no passkey is set up any more)."
GUEST_GOOGLE = "A guest show needs Google sign-in, so every console of yours can be locked."
NOTHING_LOCKED = "Nothing is locked."
LOCK_CHANGED = "That lock has changed. Try Resume again."


class OpenBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    audience: Literal["owner", "guest"]
    proof: PasskeyProof | None = None


class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    proof: PasskeyProof | None = None


def utcnow(request: Request) -> datetime:
    """The clock (`app.state.book_clock` when set: the tests and evals move it)."""
    clock = getattr(request.app.state, "book_clock", None)
    return clock() if callable(clock) else datetime.now(UTC)


def settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def console(request: Request) -> bool:
    s = settings(request)
    if session_email(request, s) is not None:
        return True
    return s.auth_mode is AuthMode.TOKEN and s.env == "dev"


def limited(request: Request, name: str, key: str) -> JSONResponse | None:
    limits = getattr(request.app.state, "book_show_limits", None)
    if limits is None:
        return None
    ok, wait = limits[name].allow(key)
    if ok:
        return None
    r = book_err(429, "rate_limited", "Too many requests; wait a moment.")
    r.headers["Retry-After"] = str(max(1, int(wait + 0.999)))
    return r


async def json_body(request: Request, model: type[BaseModel]) -> Any:
    """The body as `model`, or a 422 that never echoes what was sent."""
    raw = await request.body()
    if len(raw) > MAX_JSON_BYTES:
        return book_err(413, "too_large", "That request is too large.")
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError:
        return book_err(422, "input_rejected", "That request isn't one the build book takes.")


def _proof_failure(exc: Exception, **extra: Any) -> JSONResponse:
    if isinstance(exc, PasskeyRequired):
        r = book_err(403, "passkey_required", str(exc))
    elif isinstance(exc, PasskeyRejected):
        r = book_err(403, "passkey_rejected", str(exc))
        extra["reason"] = exc.reason
    elif isinstance(exc, ProofRequired):
        r = book_err(403, "proof_required", str(exc))
        extra["reason"] = exc.reason
    elif isinstance(exc, PermissionRejected):
        r = book_err(422, "input_rejected", str(exc))
    else:
        r = book_err(503, "passkeys_unreadable", "Your passkeys can't be read right now.")
    return _with(r, **extra)


def _with(r: JSONResponse, **extra: Any) -> JSONResponse:
    if not extra:
        return r
    body = {**json.loads(bytes(r.body)), **extra}
    return book_json(body, r.status_code)


async def _refuse(
    svc: BookService, uid: str, audience: str, now: datetime, r: JSONResponse, code: str
) -> JSONResponse:
    await svc.record_open(uid, audience, granted=False, how=code, now=now)
    return r


_PROOF_ERRORS = (
    PasskeyRequired,
    PasskeyRejected,
    ProofRequired,
    PasskeyDataUnreadable,
    PermissionRejected,
)


async def _prove_open(
    request: Request, svc: BookService, uid: str, body: OpenBody, now: datetime
) -> str | JSONResponse:
    """Google mode: passkeys in force AND a fresh sign-in AND a book_open proof for this
    audience. The passkey that answered (for the audit) or the refusal."""
    perms: PermissionsService | None = getattr(request.app.state, "permissions", None)  # live
    a = body.audience
    try:
        ready = perms is not None and perms.available and await perms.passkey_required(uid)
    except Exception as exc:  # noqa: BLE001 - can't tell: refuse, never fall back to the sign-in
        log.warning(
            "passkey state unreadable; the book stays shut", extra={"error": type(exc).__name__}
        )
        ready = False
    if perms is None or not ready:
        r = book_err(403, "passkey_setup_needed", SETUP)
        return await _refuse(svc, uid, a, now, r, "passkey_setup_needed")
    if not fresh_sign_in_left(request, settings(request)):
        r = _with(book_err(403, "reauth_required", REAUTH), reason="reauth")
        return await _refuse(svc, uid, a, now, r, "reauth_required")
    try:
        how = await perms.check_purpose(uid, "book_open", a, body.proof)
    except _PROOF_ERRORS as exc:
        return await _refuse(svc, uid, a, now, _proof_failure(exc), type(exc).__name__)
    if how is None:  # passkeys went out of force in between: still no sign-in-only path
        r = book_err(403, "passkey_setup_needed", SETUP)
        return await _refuse(svc, uid, a, now, r, "passkey_setup_needed")
    return str(how)


async def open_flow(request: Request, svc: BookService, uid: str) -> JSONResponse:
    now, s = utcnow(request), settings(request)
    if not console(request):
        return book_err(403, "console_only", CONSOLE_ONLY)
    if (r := limited(request, "open", uid)) is not None:
        return r
    body = await json_body(request, OpenBody)
    if isinstance(body, JSONResponse):
        return body
    rel = svc.source.current()
    if rel is None or not rel.ok:
        return book_err(404, "no_book", NO_BOOK)
    if s.auth_mode is AuthMode.GOOGLE:
        how = await _prove_open(request, svc, uid, body, now)
        if isinstance(how, JSONResponse):
            return how
    elif body.audience == "guest":
        r = book_err(409, "guest_needs_google", GUEST_GOOGLE)
        return await _refuse(svc, uid, "guest", now, r, "guest_needs_google")
    else:
        how = "token-mode dev, no passkey"
    return await _granted(request, svc, uid, body.audience, how, now)


async def _granted(
    request: Request, svc: BookService, uid: str, audience: Audience, how: str, now: datetime
) -> JSONResponse:
    try:
        opened = await svc.open(uid, audience, how=how, now=now)
    except BookOff as exc:
        return book_err(503, "book_off", str(exc))
    if audience == "guest" and "session" in request.scope:
        request.session.pop(SESSION_AUTH_AT_KEY, None)  # the guest can't reuse the owner's
        request.session[GUEST_FLAG] = True  # held at once on every instance (book_lock.py)
    v = opened.session
    return book_json(
        {
            "token": opened.token,
            "session_id": v.session_id,
            "until": v.until,
            "idle_until": v.idle_until,
            "audience": v.audience,
        }
    )


async def _resume_proof(
    request: Request, svc: BookService, uid: str, lock_id: str, proof: PasskeyProof | None
) -> str | JSONResponse:
    perms = getattr(request.app.state, "permissions", None)
    if perms is None:
        return book_err(503, "passkeys_unavailable", "Passkeys aren't available right now.")
    now = utcnow(request)
    try:
        how = await perms.check_purpose(uid, "book_resume", lock_id, proof)
    except _PROOF_ERRORS as exc:
        await svc.record_resume(uid, granted=False, how=type(exc).__name__, now=now)
        return _proof_failure(exc, lock_id=lock_id)
    if how is not None:
        return str(how)
    if not fresh_sign_in_left(request, settings(request)):
        return _with(
            book_err(403, "reauth_required", REAUTH_RESUME), reason="reauth", lock_id=lock_id
        )
    return "a fresh Google sign-in (no passkey in force)"


async def resume_flow(request: Request, svc: BookService, uid: str) -> JSONResponse:
    s = settings(request)
    if s.auth_mode is not AuthMode.GOOGLE or session_email(request, s) is None:
        return book_err(403, "console_only", CONSOLE_ONLY)
    if (r := limited(request, "resume", uid)) is not None:
        return r
    body = await json_body(request, ResumeBody)
    if isinstance(body, JSONResponse):
        return body
    try:
        state = await svc.lock_state(uid)
    except LockUnreadable as exc:
        return book_err(503, "show_lock_unreadable", str(exc))
    if state is None:
        return book_json({"resumed": False, "detail": NOTHING_LOCKED})
    how = await _resume_proof(request, svc, uid, state.id, body.proof)
    if isinstance(how, JSONResponse):
        return how
    now = utcnow(request)
    if not await svc.record_resume(uid, granted=True, how=how, now=now):
        return book_err(503, "book_off", "The unlock couldn't be recorded, so it didn't happen.")
    if not await svc.resume(uid, state.id, now=now):
        return book_err(409, "lock_changed", LOCK_CHANGED)
    request.session.pop(GUEST_FLAG, None)
    return book_json({"resumed": True})


__all__ = [
    "OpenBody",
    "ResumeBody",
    "console",
    "json_body",
    "limited",
    "open_flow",
    "resume_flow",
    "settings",
    "utcnow",
]
