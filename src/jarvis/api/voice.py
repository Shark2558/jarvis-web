# src/jarvis/api/voice.py
"""Voice HTTP surface (slice 9 §3; Layer 1 → 2 / 8). Owner-only: `require_auth` + `current_user`
(no client user id is read); cookie writes need `X-Requested-With: JARVIS` (enforced by
`require_auth`); speak ≤ 60, transcribe ≤ 30, GET /v1/voice ≤ 60 and PUT settings ≤ 60 calls a
minute per owner, on top of the /v1 per-client limit. Text, transcripts and audio are never
logged (lengths only).

GET  /v1/voice             VoiceView {cloud {tts, stt, reason}, settings {voice, rate, wit,
                           phrases}, phrase_limits {items: 50, chars: 40},
                           voices [{id, label, style, type, available}], wit_levels [{id, label,
                           description}], allowance {tts {type, used_chars, free_chars, by_type
                           {chirp3-hd {used, free}, studio {used, free}}}, stt {used_seconds,
                           free_seconds}, month, resets_at, scope: "deployment"}, month {month,
                           voice_inr}, language}. The allowance is JARVIS's share of Google's
                           free tier (90 % by default) for the whole deployment, Pacific-time
                           months; 503 budget_unavailable when its counter can't be read.
PUT  /v1/voice/settings    {voice?, rate?, wit?, phrases?} → settings; 422 input_rejected (the
                           words are never echoed; a change to them is audited as a count)
POST /v1/voice/speak       {text, voice?, rate?} | {preview: true, voice?} → 200 audio/mpeg with
                           X-Jarvis-Chars, X-Jarvis-Cost-Inr; 422 nothing_to_say / input_rejected,
                           402 budget_reached, 503 voice_unavailable {reason}, 429
POST /v1/voice/transcribe  body audio/wav (16 kHz mono PCM16, 0.3–60 s, ≤ 2,000,000 bytes) →
                           {text, confidence, seconds, cost_inr, language, no_speech,
                           alternatives}; 413 too_large (Content-Length checked before reading),
                           422 bad_audio, 402, 503, 429. R11.1 D9: `alternatives` are the
                           engine's other guesses (at most two); optional header
                           X-Jarvis-Session: <conversation id> adds that conversation's attached
                           file names and the owner's own nouns to this turn's recognition hints
                           (his waiting files' names are always added). A bad id is ignored.

Errors use the app's shape {"error": code, "detail": plain words}; 503 voice_unavailable adds
"reason" (api_disabled | not_configured | upstream_error | timeout); 429 adds Retry-After.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.body import read_capped
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.logging import get_logger
from jarvis.voice.ports import (
    AudioTooLarge,
    BadAudio,
    NothingToSay,
    VoiceBusy,
    VoiceRejected,
    VoiceUnavailable,
)
from jarvis.voice.service import SpeakRequest, TranscriptView, VoiceService, VoiceView
from jarvis.voice.settings import VoiceSettings, VoiceSettingsPatch

log = get_logger(__name__)
router = APIRouter(prefix="/v1/voice", dependencies=[Depends(require_auth)])

SPEAK_PER_MINUTE = 60
TRANSCRIBE_PER_MINUTE = 30
VIEW_PER_MINUTE = 60
SETTINGS_PER_MINUTE = 60
MAX_AUDIO_BYTES = 2_000_000
WAV_TYPES = frozenset({"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"})
SESSION_HEADER = "x-jarvis-session"  # R11.1 D9: the open conversation, for this turn's hints
HINTS_WAIT_S = 0.8  # the hints are a help: a slow read never delays what was said
_SESSION_ID = re.compile(r"[A-Za-z0-9_\-]{1,64}")


class VoiceRateLimited(Exception):
    def __init__(self, wait_s: float) -> None:
        self.retry_after = max(1, int(wait_s + 0.999))
        super().__init__("too many requests")


def _svc(request: Request) -> VoiceService:
    svc: VoiceService | None = getattr(request.app.state, "voice", None)
    if svc is None:
        raise LookupError("Voice is not available on this server.")
    return svc


def _limit(request: Request, name: str, uid: str) -> None:
    limiter: RateLimiter = request.app.state.voice_limits[name]
    allowed, wait = limiter.allow(uid)
    if not allowed:
        raise VoiceRateLimited(wait)


async def turn_hints(request: Request, uid: str) -> tuple[str, ...]:
    """This turn's recognition hints (R11.1 D9), from the files part: the owner's waiting and
    attached files' names as they are said, and his own turns' nouns. Never raises and never
    takes long: without the part, on any failure or past `HINTS_WAIT_S` there are none."""
    parts: dict[str, Any] = getattr(request.app.state, "r111_parts", None) or {}
    part = parts.get("files")
    svc = part.services.get("understand") if part is not None else None
    if svc is None:
        return ()
    raw = request.headers.get(SESSION_HEADER, "")
    sid = raw if _SESSION_ID.fullmatch(raw) else None
    try:
        found = await asyncio.wait_for(svc.hints(uid, session_id=sid), HINTS_WAIT_S)
    except Exception as exc:  # noqa: BLE001 — never a reason to refuse a recording
        log.warning("turn hints unavailable", extra={"reason": type(exc).__name__})
        return ()
    return tuple(found.turn)


@router.get("", response_model=VoiceView)
async def get_voice(
    request: Request, svc: VoiceService = Depends(_svc), uid: str = Depends(current_user)
) -> VoiceView:
    _limit(request, "view", uid)
    return await svc.view(uid)


@router.put("/settings", response_model=VoiceSettings)
async def put_settings(
    patch: VoiceSettingsPatch,
    request: Request,
    svc: VoiceService = Depends(_svc),
    uid: str = Depends(current_user),
) -> VoiceSettings:
    _limit(request, "settings", uid)
    new = await svc.update_settings(uid, patch)
    if patch.phrases is not None:  # the words go to Google: record that they changed, never what
        await record_change(
            request, agent="owner", tool="voice_phrases_set", args={"count": len(new.phrases)}
        )
    return new


@router.post("/speak", response_class=Response)
async def speak(
    body: SpeakRequest,
    request: Request,
    svc: VoiceService = Depends(_svc),
    uid: str = Depends(current_user),
) -> Response:
    _limit(request, "speak", uid)
    out = await svc.speak(uid, body)
    return Response(
        content=out.audio,
        media_type="audio/mpeg",
        headers={
            "X-Jarvis-Chars": str(out.chars),
            "X-Jarvis-Cost-Inr": f"{out.cost_inr:.4f}",
            "Cache-Control": "no-store",
        },
    )


@router.post("/transcribe", response_model=TranscriptView)
async def transcribe(
    request: Request, svc: VoiceService = Depends(_svc), uid: str = Depends(current_user)
) -> TranscriptView:
    _limit(request, "transcribe", uid)
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if ctype not in WAV_TYPES:
        raise BadAudio("Send the recording as audio/wav (16-bit PCM, mono, 16,000 Hz).")
    blob = await read_capped(
        request, MAX_AUDIO_BYTES, too_large=lambda: AudioTooLarge(MAX_AUDIO_BYTES)
    )
    return await svc.transcribe(uid, blob, turn_hints=await turn_hints(request, uid))


def _err(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=headers)


def install_voice(app: FastAPI) -> None:
    """Mount /v1/voice, its per-owner limits and its error mapping on `app`."""
    app.state.voice_limits = {
        "speak": RateLimiter(SPEAK_PER_MINUTE),
        "transcribe": RateLimiter(TRANSCRIBE_PER_MINUTE),
        "view": RateLimiter(VIEW_PER_MINUTE),
        "settings": RateLimiter(SETTINGS_PER_MINUTE),
    }

    @app.exception_handler(VoiceUnavailable)
    async def _unavailable(_: Request, exc: VoiceUnavailable) -> JSONResponse:
        return _err(503, {"error": "voice_unavailable", "detail": str(exc), "reason": exc.reason})

    @app.exception_handler(VoiceBusy)
    async def _busy(_: Request, exc: VoiceBusy) -> JSONResponse:
        retry = {"Retry-After": str(VoiceBusy.RETRY_AFTER_S)}
        return _err(429, {"error": "voice_busy", "detail": str(exc)}, retry)

    @app.exception_handler(VoiceRejected)
    async def _rejected(_: Request, exc: VoiceRejected) -> JSONResponse:
        return _err(422, {"error": "input_rejected", "detail": str(exc)})

    @app.exception_handler(NothingToSay)
    async def _silent(_: Request, exc: NothingToSay) -> JSONResponse:
        return _err(422, {"error": "nothing_to_say", "detail": str(exc)})

    @app.exception_handler(BadAudio)
    async def _bad_audio(_: Request, exc: BadAudio) -> JSONResponse:
        return _err(422, {"error": "bad_audio", "detail": str(exc)})

    @app.exception_handler(AudioTooLarge)
    async def _too_large(_: Request, exc: AudioTooLarge) -> JSONResponse:
        return _err(413, {"error": "too_large", "detail": str(exc)})

    @app.exception_handler(VoiceRateLimited)
    async def _limited(_: Request, exc: VoiceRateLimited) -> JSONResponse:
        retry = {"Retry-After": str(exc.retry_after)}
        return _err(429, {"error": "rate_limited", "detail": "too many requests"}, retry)

    app.include_router(router)


__all__ = ["MAX_AUDIO_BYTES", "install_voice", "read_capped", "router"]
