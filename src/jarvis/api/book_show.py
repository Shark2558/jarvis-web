# src/jarvis/api/book_show.py
"""The build book's session routes (R6 D8-D14; "Contract"; builder C). Owner-only cookie sessions
(`require_auth` + `current_user`), every answer `no-store` (api/book_http.py), 503 book_off until
I1 wires `app.state.book_service` (checked before anything else, the body included).

POST /v1/book/open {proof, audience}     {token, session_id, until, idle_until, audience} · 403
                                         console_only / passkey_setup_needed / reauth_required /
                                         passkey_required / passkey_rejected · 409
                                         guest_needs_google · 404 no_book · 429 (5 a minute)
GET  /v1/book/show/script                ● {release, audience, scenes 1-13, closing {lines,
                                         hand_back}, costs (+ month_inr, limit_inr: owner only),
                                         talk {on, why}, voice cloud|browser, session}
POST /v1/book/show/speak {line_id}       ● audio/mpeg (a beat id of this book or a lines.LINES
                                         key; the server holds the text) · 404 unknown_line · 503
                                         voice_unavailable (reason browser: Book settings) · 402
POST /v1/book/show/hear                  ● audio/wav <= 15 s, 600 KB -> {text} (never stored)
POST /v1/book/show/ask {text}            ● {reply_id, reply, refused, follow_up, left} (<= 500
                                         characters, 6 a minute a session)
POST /v1/book/show/beat                  ● {until, idle_until}
POST /v1/book/close {reason?}            ● {closed, wiped, notified} (reason closing | end)
POST /v1/book/resume {proof}             {resumed} · 403 passkey_required {lock_id} / ...

● = header X-Jarvis-Book (the token; 401 session_gone when it is unknown, closed, expired or
idle). The proofs and the guest lock: api/book_show_access.py and api/book_lock.py.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.body import read_capped
from jarvis.api.book_http import NO_STORE, TOKEN_HEADER, book_err, book_json, book_off
from jarvis.api.book_show_access import (
    json_body,
    limited,
    open_flow,
    resume_flow,
    utcnow,
)
from jarvis.api.identity import current_user
from jarvis.billing.service import BudgetError
from jarvis.buildbook.model import SessionView
from jarvis.buildbook.ports import BookUnavailable, SessionGone
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
from jarvis.voice.wav import parse_wav

log = get_logger(__name__)
router = APIRouter(prefix="/v1/book", dependencies=[Depends(require_auth)])

QUESTION_MAX = 500  # D12
HEAR_MAX_BYTES = 600 * 1024
HEAR_MAX_S = 15.0
WAV_TYPES = frozenset({"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"})
SESSION_GONE = "This build book session has ended. Open the book again from the console."
TOO_LONG = f"Keep a question under {QUESTION_MAX} characters."


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


def _voice_failure(exc: Exception) -> JSONResponse:
    if isinstance(exc, BudgetError):
        return book_err(402, "budget_reached", str(exc))
    if isinstance(exc, VoiceBusy):
        return book_err(429, "voice_busy", str(exc))
    if isinstance(exc, AudioTooLarge):
        return book_err(413, "too_large", str(exc))
    if isinstance(exc, BadAudio | NothingToSay | VoiceRejected):
        return book_err(
            422, "bad_audio" if isinstance(exc, BadAudio) else "input_rejected", str(exc)
        )
    reason = getattr(exc, "reason", "upstream_error")
    r = book_json({"error": "voice_unavailable", "detail": str(exc), "reason": reason}, 503)
    return r


@router.post("/open", response_model=None)
async def open_book(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = _svc(request)
    return book_off() if svc is None else await open_flow(request, svc, uid)


@router.get("/show/script", response_model=None)
async def show_script(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
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
    except BookUnavailable:
        return book_err(404, "no_book", "This server has no build book.")


@router.post("/show/speak", response_model=None)
async def show_speak(request: Request, uid: str = Depends(current_user)) -> Response:
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
    text = await svc.line_text(uid, view, body.line_id)
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
        out = await voice.speak(uid, SpeakRequest(text=text))
    except (VoiceError, BudgetError) as exc:
        return _voice_failure(exc)
    return Response(content=out.audio, media_type="audio/mpeg", headers=NO_STORE)


@router.post("/show/hear", response_model=None)
async def show_hear(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return book_off()
    if (r := limited(request, "hear", uid)) is not None:
        return r
    view = await _session(request, svc, uid)
    if isinstance(view, JSONResponse):
        return view
    voice = getattr(request.app.state, "voice", None)
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if voice is None:
        return book_json(
            {
                "error": "voice_unavailable",
                "detail": "Type your question.",
                "reason": "not_configured",
            },
            503,
        )
    if ctype not in WAV_TYPES:
        return book_err(422, "bad_audio", "Send the recording as audio/wav.")
    if not svc.allow_hearing(view.session_id):
        return book_json(
            {"error": "voice_unavailable", "detail": "Type your question.", "reason": "budget"}, 503
        )
    try:
        blob = await read_capped(
            request, HEAR_MAX_BYTES, too_large=lambda: AudioTooLarge(HEAR_MAX_BYTES)
        )
        if parse_wav(blob).seconds > HEAR_MAX_S:
            return book_err(413, "too_long", "Keep a spoken question under 15 seconds.")
        heard = await voice.transcribe(uid, blob)
    except (VoiceError, BudgetError) as exc:
        return _voice_failure(exc)
    return book_json({"text": heard.text})  # handed back, never kept (kept only if asked)


@router.post("/show/ask", response_model=None)
async def show_ask(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
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
    got = await svc.ask(uid, view, text, now=utcnow(request))
    return book_json(got.model_dump())


@router.post("/show/beat", response_model=None)
async def show_beat(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = _svc(request)
    if svc is None:
        return book_off()
    if (r := limited(request, "beat", uid)) is not None:
        return r
    view = await _session(request, svc, uid, beat=True)
    if isinstance(view, JSONResponse):
        return view
    return book_json({"until": view.until, "idle_until": view.idle_until})


@router.post("/close", response_model=None)
async def close(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
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


@router.post("/resume", response_model=None)
async def resume(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = _svc(request)
    return book_off() if svc is None else await resume_flow(request, svc, uid)


def install_book_show(app: FastAPI) -> None:
    app.include_router(router)


__all__ = ["install_book_show", "router"]
