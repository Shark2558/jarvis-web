# src/jarvis/api/book_show.py
"""The build book's session routes (R6 D8-D14; "Contract"; builder C). Owner-only cookie sessions
(`require_auth` + `current_user`; the show routes, the lock and Resume also take the presenting
browser's show-only marker, SEC-4: `book_show_auth`), every answer `no-store` (api/book_http.py),
503 book_off until I1 wires `app.state.book_service` (checked before anything else, the body
included).

POST /v1/book/open {proof, audience}     {token, session_id, until, idle_until, audience} · 403
                                         google_needed (token mode, R6.2 G11) / console_only /
                                         passkey_setup_needed / reauth_required /
                                         passkey_required / passkey_rejected · 404 no_book · 429
                                         (5 a minute)
GET  /v1/book/show/script                ● {release, audience, scenes 1-13, closing {lines,
                                         hand_back}, costs (+ month_inr, limit_inr: owner only),
                                         talk {on, why}, voice and listening browser|cloud (R6.2:
                                         the browser's unless the owner switched), session}
POST /v1/book/show/speak {line_id}       ● audio/mpeg (a beat id of this book or a lines.LINES
                                         key; the server holds the text) · 404 unknown_line · 503
                                         voice_unavailable (reason browser: Book settings;
                                         free_used: a guest past the free allowance) · 402
POST /v1/book/show/hear | /show/heard    ● a spoken question: api/book_show_hear.py (R6.2)
POST /v1/book/show/ask {text}            ● {reply_id, reply, refused, follow_up, left} (<= 500
                                         characters, 6 a minute a session)
POST /v1/book/show/beat                  ● {until, idle_until}
POST /v1/book/close {reason?}            ● {closed, wiped, notified} (reason closing | end)
POST /v1/book/resume {proof}             {resumed} · 403 passkey_required {lock_id} / ...
GET  /v1/book/show/lock                  {on, id?, line?} (cookie only, no ●; I1 for D's show:
                                         `id` only for the owner whose lock it is; under D10's
                                         allow-list) · 503 show_lock_unreadable

● = header X-Jarvis-Book (the token; 401 session_gone when it is unknown, closed, expired or
idle). The proofs and the guest lock: api/book_show_access.py and api/book_lock.py.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.book_http import (
    NO_STORE,
    RESUME_OFF,
    TOKEN_HEADER,
    book_err,
    book_json,
    book_off,
)
from jarvis.api.book_lock import UNREADABLE, lock_for, owner_ids
from jarvis.api.book_show_access import (
    json_body,
    limited,
    open_flow,
    resume_flow,
    utcnow,
)
from jarvis.api.book_show_auth import require_show_auth, show_user
from jarvis.api.identity import current_user
from jarvis.billing.service import BudgetError, BudgetUnavailable, FreeAllowanceUsed
from jarvis.buildbook import hear
from jarvis.buildbook.lines import LINES
from jarvis.buildbook.model import SessionView
from jarvis.buildbook.ports import BookUnavailable, LockUnreadable, SessionGone
from jarvis.buildbook.service import BookService
from jarvis.logging import get_logger
from jarvis.voice.ports import (
    AudioTooLarge,
    BadAudio,
    NothingToSay,
    VoiceBusy,
    VoiceError,
    VoiceRejected,
)
from jarvis.voice.service import SpeakRequest

log = get_logger(__name__)
router = APIRouter(prefix="/v1/book")
OWNER_ONLY = [Depends(require_auth)]  # open: an owner's sign-in, never the show-only marker
SHOW = [Depends(require_show_auth)]  # SEC-4: an owner's sign-in or the presenting browser's marker

QUESTION_MAX = 500  # D12
SESSION_GONE = "This build book session has ended. Open the book again from the console."
TOO_LONG = f"Keep a question under {QUESTION_MAX} characters."
SPOKEN_TOO_LONG = "Keep a spoken question under 15 seconds."


class SpeakBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    line_id: str = Field(min_length=1, max_length=40)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(max_length=4_000)


class CloseBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: Literal["closing", "end"] = "end"


def _svc(request: Request) -> BookService | None:
    return getattr(request.app.state, "book_service", None)


def _gone() -> JSONResponse:
    return book_err(401, "session_gone", SESSION_GONE)


async def _session(
    request: Request, svc: BookService, uid: str, *, beat: bool = False
) -> SessionView | JSONResponse:
    token = request.headers.get(TOKEN_HEADER, "")
    try:
        if beat:
            return await svc.beat(uid, token, now=utcnow(request))
        return await svc.resolve(uid, token, now=utcnow(request))
    except SessionGone:
        return _gone()


def _said(reason: str, *, owner: bool, hearing: bool) -> str:
    """R6.2: the Book's own words, never the voice service's setup text (a Cloud Shell command,
    "the browser's voice is used"). Narration falls back to the page's own voice: it says so."""
    return hear.words(reason, owner=owner) if hearing else hear.SPEAK_OFF


def _unavailable(reason: str, *, owner: bool, hearing: bool) -> JSONResponse:
    detail = _said(reason, owner=owner, hearing=hearing)
    return book_json({"error": "voice_unavailable", "detail": detail, "reason": reason}, 503)


def _voice_failure(exc: Exception, *, owner: bool, hearing: bool) -> JSONResponse:
    if isinstance(exc, BudgetUnavailable):  # G12: the limit can't be read, so it isn't "reached"
        return _unavailable("budget_unreadable", owner=owner, hearing=hearing)
    if isinstance(exc, BudgetError):  # G13: the free minutes AND the month's limit are used up
        return book_err(
            402, "budget_reached", _said("budget_reached", owner=owner, hearing=hearing)
        )
    if isinstance(exc, VoiceBusy):
        return book_err(429, "voice_busy", _said("busy", owner=owner, hearing=hearing))
    if isinstance(exc, AudioTooLarge):
        return book_err(413, "too_large", SPOKEN_TOO_LONG)
    if isinstance(exc, BadAudio):
        return book_err(422, "bad_audio", str(exc))  # plain words about the recording itself
    if isinstance(exc, NothingToSay | VoiceRejected):
        return book_err(422, "input_rejected", _said("rejected", owner=owner, hearing=hearing))
    reason = getattr(exc, "reason", "upstream_error")
    return _unavailable(reason, owner=owner, hearing=hearing)


@router.post("/open", response_model=None, dependencies=OWNER_ONLY)
async def open_book(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = _svc(request)
    return book_off() if svc is None else await open_flow(request, svc, uid)


@router.get("/show/script", response_model=None, dependencies=SHOW)
async def show_script(request: Request, uid: str = Depends(show_user)) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return book_off()
    if (r := limited(request, "script", uid)) is not None:
        return r
    view = await _session(request, svc, uid)
    if isinstance(view, JSONResponse):
        return view
    try:
        return book_json(await svc.script(uid, view))
    except BookUnavailable as exc:
        return book_err(404, "no_book", str(exc))


@router.post("/show/speak", response_model=None, dependencies=SHOW)
async def show_speak(request: Request, uid: str = Depends(show_user)) -> Response:
    svc = _svc(request)
    if svc is None:
        return book_off()
    if (r := limited(request, "speak", uid)) is not None:
        return r
    view = await _session(request, svc, uid)
    if isinstance(view, JSONResponse):
        return view
    body = await json_body(request, SpeakBody)
    if isinstance(body, JSONResponse):
        return body
    try:
        text = await svc.line_text(uid, view, body.line_id)
    except BookUnavailable as exc:
        return book_err(404, "no_book", str(exc))
    if text is None:
        return book_err(404, "unknown_line", "That isn't a line of this show.")
    voice = getattr(request.app.state, "voice", None)
    if voice is None or await svc.voice(uid) == "browser":
        why = "browser" if voice is not None else "not_configured"
        return book_json(
            {"error": "voice_unavailable", "detail": "Use the browser's voice.", "reason": why}, 503
        )
    if not svc.allow_speech(view.session_id, len(text)):
        return book_json(
            {
                "error": "voice_unavailable",
                "detail": "Use the browser's voice.",
                "reason": "budget",
            },
            503,
        )
    try:
        # a guest's narration stays inside the free allowance, as a guest's listening does
        out = await voice.speak(uid, SpeakRequest(text=text), free_only=view.audience != "owner")
    except FreeAllowanceUsed:
        return _unavailable("free_used", owner=view.audience == "owner", hearing=False)
    except (VoiceError, BudgetError) as exc:
        return _voice_failure(exc, owner=view.audience == "owner", hearing=False)
    return Response(content=out.audio, media_type="audio/mpeg", headers=NO_STORE)


@router.post("/show/ask", response_model=None, dependencies=SHOW)
async def show_ask(request: Request, uid: str = Depends(show_user)) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return book_off()
    view = await _session(request, svc, uid)
    if isinstance(view, JSONResponse):
        return view
    if (r := limited(request, "ask", view.session_id)) is not None:
        return r
    body = await json_body(request, AskBody)
    if isinstance(body, JSONResponse):
        return body
    text = body.text.strip()
    if not text:
        return book_err(422, "input_rejected", "Ask a question first.")
    if len(text) > QUESTION_MAX:
        return book_err(422, "too_long", TOO_LONG)
    try:
        got = await svc.ask(uid, view, text, now=utcnow(request))
    except SessionGone:  # it closed while the brain was thinking (End, the sweep, a new open)
        return _gone()
    except BookUnavailable as exc:
        return book_err(404, "no_book", str(exc))
    return book_json(got.model_dump())


@router.post("/show/beat", response_model=None, dependencies=SHOW)
async def show_beat(request: Request, uid: str = Depends(show_user)) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return book_off()
    if (r := limited(request, "beat", uid)) is not None:
        return r
    view = await _session(request, svc, uid, beat=True)
    if isinstance(view, JSONResponse):
        return view
    return book_json({"until": view.until, "idle_until": view.idle_until})


@router.post("/close", response_model=None, dependencies=SHOW)
async def close(request: Request, uid: str = Depends(show_user)) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return book_off()
    if (r := limited(request, "close", uid)) is not None:
        return r
    view = await _session(request, svc, uid)
    if isinstance(view, JSONResponse):
        return view
    body = await json_body(request, CloseBody)
    if isinstance(body, JSONResponse):
        return body
    try:
        done = await svc.close(uid, view.session_id, reason=body.reason, now=utcnow(request))
    except SessionGone:
        return _gone()
    return book_json({"closed": True, "wiped": done.wiped, "notified": done.notified})


@router.post("/resume", response_model=None, dependencies=SHOW)
async def resume(request: Request, uid: str = Depends(show_user)) -> JSONResponse:
    svc = _svc(request)
    if svc is None:  # the lock may still hold (SEC-3): the emergency unlock is the way out
        return book_err(503, "book_off", RESUME_OFF)
    return await resume_flow(request, svc, uid)


@router.get("/show/lock", response_model=None, dependencies=SHOW)
async def show_lock(request: Request, uid: str = Depends(show_user)) -> JSONResponse:
    """Whether a guest lock holds this owner's consoles (D10), for the show page with no book
    token (another console tab, or the presenting tab after the close)."""
    store = getattr(request.app.state, "book_lock", None)
    if store is None:
        return book_json({"on": False})
    try:
        state, own = await lock_for(store, owner_ids(request.app.state.settings), uid)
    except LockUnreadable:
        return book_err(503, "show_lock_unreadable", UNREADABLE)
    if state is None:
        return book_json({"on": False})
    body = {"on": True, "line": LINES["hand_back"]}
    return book_json({**body, "id": state.id} if own else body)


def install_book_show(app: FastAPI) -> None:
    app.include_router(router)


__all__ = ["install_book_show", "router"]
