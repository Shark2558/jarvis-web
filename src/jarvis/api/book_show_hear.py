# src/jarvis/api/book_show_hear.py
"""A spoken question in the build book's show (R6 D12; R6.2 Part 1 and owner decision 4 of 15 Nov
2026: the Book's voice costs nothing by default). Kept beside `api/book_show.py` (its 400-line
cap); `r6_wiring.install_r6_routes` mounts both. Each route takes the presenting browser's
show-only marker (SEC-4) and the book token (●), answers `no-store`, never stores or logs the
words, and is on the guest lock's allow-list (`api/book_lock.ALLOWED`).

POST /v1/book/show/hear    ● audio/wav <= 15 s, 600 KB -> {text, heard, changed, no_speech,
                           charged (owner only)} through the CLOUD recogniser, and only when the
                           owner set Listening to Cloud in Book settings: else 409
                           listening_browser and no speech-to-text call at all. A guest's cloud
                           question is free-only (`free_only`: never charged; 503 free_used) ·
                           503 voice_unavailable / 402 / 429 / 413 / 422 in the Book's own words
POST /v1/book/show/heard   ● {text <= 500 characters} -> the same answer for what THIS BROWSER's
                           own recogniser heard (the default, Rs 0): the console's free R11.1
                           rules only (`buildbook/hear.understood`), no model and no cloud call ·
                           422 too_long / input_rejected

Both: 10 a minute per owner each, and the session's 30 spoken questions between them. The
correction uses the book's own public words, plus the owner's "Words to recognise" for an OWNER
session only (R6 D1: for a guest they are never even read).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.body import read_capped
from jarvis.api.book_http import book_err, book_json, book_off
from jarvis.api.book_show import (
    QUESTION_MAX,
    SHOW,
    SPOKEN_TOO_LONG,
    _session,
    _svc,
    _unavailable,
    _voice_failure,
)
from jarvis.api.book_show_access import json_body, limited
from jarvis.api.book_show_auth import show_user
from jarvis.billing.service import BudgetError, FreeAllowanceUsed
from jarvis.buildbook import hear
from jarvis.buildbook.model import SessionView
from jarvis.buildbook.service import BookService
from jarvis.logging import get_logger
from jarvis.voice.ports import AudioTooLarge, VoiceError
from jarvis.voice.wav import parse_wav

log = get_logger(__name__)
router = APIRouter(prefix="/v1/book")

HEAR_MAX_BYTES = 600 * 1024
HEAR_MAX_S = 15.0
HEARD_BODY_MAX = 4_000  # characters the JSON may carry; the question itself is QUESTION_MAX
WAV_TYPES = frozenset({"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"})
TOO_LONG_HEARD = f"Keep a spoken question under {QUESTION_MAX} characters."


class HeardBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(max_length=HEARD_BODY_MAX)


async def _owner_words(voice: Any, uid: str) -> tuple[str, ...]:
    """The owner's "Words to recognise", for an OWNER session only (D1); none when unreadable."""
    read = getattr(voice, "settings_of", None)
    if read is None:
        return ()
    try:
        return tuple((await read(uid)).phrases)
    except Exception as exc:  # noqa: BLE001 - the book's own words still help
        log.warning("voice settings unreadable for the book", extra={"error": type(exc).__name__})
        return ()


async def _answer(request: Request, svc: BookService, uid: str, owner: bool, said: str) -> Any:
    """{text, heard, changed, no_speech}: the free rules on `said`, against the book's words and
    (an owner session only) his own."""
    words = svc.words()
    voice = getattr(request.app.state, "voice", None)
    got = hear.understood(said, (*words, *await _owner_words(voice, uid)) if owner else words)
    return {"text": got.text, "heard": got.heard, "changed": got.changed, "no_speech": not got.text}


async def _spoken(
    request: Request, uid: str, name: str
) -> tuple[BookService, SessionView] | JSONResponse:
    """The checks both routes share: the book on, the rate limit, the live session."""
    svc = _svc(request)
    if svc is None:
        return book_off()
    if (r := limited(request, name, uid)) is not None:
        return r
    view = await _session(request, svc, uid)
    return view if isinstance(view, JSONResponse) else (svc, view)


def _no_more(svc: BookService, view: SessionView, owner: bool) -> JSONResponse | None:
    """The session's 30 spoken questions, shared by both routes."""
    if svc.allow_hearing(view.session_id):
        return None
    detail = hear.words("session_budget", owner=owner)
    return book_json({"error": "voice_unavailable", "detail": detail, "reason": "budget"}, 503)


@router.post("/show/hear", response_model=None, dependencies=SHOW)
async def show_hear(request: Request, uid: str = Depends(show_user)) -> JSONResponse:
    got = await _spoken(request, uid, "hear")
    if isinstance(got, JSONResponse):
        return got
    svc, view = got
    owner = view.audience == "owner"
    if await svc.show.listening(uid) != "cloud":  # decision 4: the browser listens; Rs 0
        detail = hear.words("listening_browser", owner=owner)
        return book_err(409, "listening_browser", detail)
    voice = getattr(request.app.state, "voice", None)
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if voice is None:  # nothing listens instead: never "the browser's voice is used"
        return _unavailable("not_configured", owner=owner, hearing=True)
    if ctype not in WAV_TYPES:
        return book_err(422, "bad_audio", "Send the recording as audio/wav.")
    if (r := _no_more(svc, view, owner)) is not None:
        return r
    try:
        blob = await read_capped(
            request, HEAR_MAX_BYTES, too_large=lambda: AudioTooLarge(HEAR_MAX_BYTES)
        )
        if parse_wav(blob).seconds > HEAR_MAX_S:
            return book_err(413, "too_long", SPOKEN_TOO_LONG)
        # D1: a guest's words are never biased toward the owner's own phrases (names, places);
        # decision 4: a guest's cloud question stays inside the free allowance, never charged
        heard = await voice.transcribe(
            uid, blob, owner_phrases=owner, public_hints=svc.words(), free_only=not owner
        )
    except FreeAllowanceUsed:
        return _unavailable("free_used", owner=owner, hearing=True)
    except (VoiceError, BudgetError) as exc:
        return _voice_failure(exc, owner=owner, hearing=True)
    body = await _answer(request, svc, uid, owner, heard.text)
    if owner and getattr(heard, "cost_inr", 0) > 0:  # G13: past the free minutes it is charged
        body["charged"] = True
    return book_json(body)  # handed back, never kept


@router.post("/show/heard", response_model=None, dependencies=SHOW)
async def show_heard(request: Request, uid: str = Depends(show_user)) -> JSONResponse:
    """What this browser's own recogniser heard (decision 4's default): free corrections only."""
    got = await _spoken(request, uid, "heard")
    if isinstance(got, JSONResponse):
        return got
    svc, view = got
    owner = view.audience == "owner"
    body = await json_body(request, HeardBody)
    if isinstance(body, JSONResponse):
        return body
    said = " ".join(body.text.split())
    if len(said) > QUESTION_MAX:
        return book_err(422, "too_long", TOO_LONG_HEARD)
    if (r := _no_more(svc, view, owner)) is not None:
        return r
    return book_json(await _answer(request, svc, uid, owner, said))


def install_book_hear(app: FastAPI) -> None:
    app.include_router(router)


__all__ = ["install_book_hear", "router"]
