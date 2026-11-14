# src/jarvis/api/sos.py
"""R7 Part D's SOS routes, under `/v1/sos` (docs/plans/r7-mobile.md D19, D20, D21). Owner-only
(`require_auth` + `current_user`; cookie writes need `X-Requested-With: JARVIS`), `no-store`.

Never locked by the app lock (D21: SOS must work), with one narrowing: while Part C's check says
this session is locked, the set-up cannot change (423 {error: device_locked}) and the card's view
names no one; the sheet and the send still work.

GET    /v1/sos                     {part, ready, enabled, sealed, telegram, label, label_set, max,
                                    countdown_s, hold_s, web_countdown_s, contacts: [{id, label,
                                    phone_hint, has_phone, joined, pending}], last, left, note}
GET    /v1/sos/sheet               {enabled, label, numbers, first, emergency, text, hold_s,
                                    countdown_s, note, locked, unreadable, warning?}: what the SOS
                                    sheet needs before a press (locked: numbers only, no label)
PUT    /v1/sos/label               {label} -> the view
POST   /v1/sos/contacts            {label, phone?} -> {contact: {id, label}}
DELETE /v1/sos/contacts/{id}       -> {removed: true} | 404
POST   /v1/sos/contacts/{id}/link  -> {link, until}: the one-time Telegram join link (24 hours)
POST   /v1/sos/send                {kind: real | test | safe, press_id?, location?: {lat_e6, lon_e6,
                                    accuracy_m, age_s}} -> the send's honest view, always with the
                                    SMS screen's numbers and text and 112. `press_id` (16-64 of
                                    A-Za-z0-9_-, one per hold): a repeat within an hour is answered
                                    with the first result and sends nothing. A place that does not
                                    validate is dropped (sent without it). While locked: real only
                                    (423 device_locked for test / safe), and no contact label.
                                    Errors: {error, detail, words, sent: false, call}

SOS is never a tool: this route (after the sheet's hold and countdown) and the phone's door are
the only ways in, so the brain can never reach it. The place travels only in the POST body and
the reply; nothing here logs or stores it. Errors are plain words.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.mobile_status import NO_STORE, part_of
from jarvis.api.ratelimit import RateLimiter
from jarvis.logging import get_logger
from jarvis.mobile.ports import NOT_BUILT, PartName
from jarvis.sos.models import CONTACT_ID, parse_press
from jarvis.sos.service import NOT_A_SERVICE, SosRefused, SosService
from jarvis.sos.store import SosOff, SosUnavailable

log = get_logger(__name__)
PART: PartName = "body"
CHANGES_PER_MINUTE = 20
SENDS_PER_MINUTE = 12  # far above a hold plus a countdown; the service's own limits still apply
SEND_FAILED = "The SOS could not be sent from the server. Use the SMS screen or call 112."
LOCKED = "JARVIS is locked on this device: unlock it to change your SOS set-up, Sir."
LOCKED_SEND = (
    "JARVIS is locked on this device, Sir: only a real SOS can be sent now. Unlock it to send a "
    "test or \u201cI\u2019m safe\u201d."
)
UNREADABLE = "JARVIS could not read that SOS request, Sir. Use the SMS screen or call 112."
router = APIRouter(prefix="/v1/sos", dependencies=[Depends(require_auth)])
_changes = RateLimiter(CHANGES_PER_MINUTE)
_sends = RateLimiter(SENDS_PER_MINUTE)


class LabelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=200)


class ContactBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=200)
    phone: str | None = Field(default=None, max_length=40)


def _json(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _err(code: str, detail: str, status: int) -> JSONResponse:
    return _json({"error": code, "detail": detail}, status)


def _service(request: Request) -> tuple[str, SosService | None]:
    part = part_of(request, PART)
    svc = part.services.get("sos") if part is not None else None
    ready = part.ready if part is not None else NOT_BUILT
    return ready, svc if isinstance(svc, SosService) else None


async def _locked(request: Request) -> bool:
    """Part C's app-lock check for this session (False until Part C wires it). A check that
    fails counts as locked: the set-up never changes on an unreadable lock."""
    phone = part_of(request, "phone")
    check = phone.services.get("app_lock") if phone is not None else None
    if not callable(check):
        return False
    try:
        return bool(await check(request.scope))
    except Exception as exc:  # noqa: BLE001 - fail closed for the set-up only
        log.warning("SOS: the app lock couldn't be read", extra={"error": type(exc).__name__})
        return True


async def _for_change(request: Request, uid: str) -> SosService | JSONResponse:
    _, svc = _service(request)
    if svc is None:
        return _err("sos_off", "Emergency SOS isn't set up on this server, Sir.", 503)
    if await _locked(request):
        return _err("device_locked", LOCKED, 423)
    allowed, _ = _changes.allow(uid)
    if not allowed:
        return _err("busy", "Too many changes at once, Sir. Try again in a minute.", 429)
    return svc


def _refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, SosRefused):
        return _err("invalid", str(exc), 422)
    if isinstance(exc, SosOff):
        return _err("sos_off", SosOff.WORDS, 503)
    return _err("unavailable", SosUnavailable.WORDS, 503)


@router.get("", include_in_schema=False)
async def sos_view(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    ready, svc = _service(request)
    head: dict[str, Any] = {"part": PART, "ready": ready}
    if svc is None:
        return _json(head)
    if await _locked(request):
        return _json({**head, "enabled": svc.enabled, "locked": True, "note": NOT_A_SERVICE})
    if not svc.store.sealed:
        return _json({**head, "enabled": svc.enabled, "sealed": False, "note": SosOff.WORDS})
    try:
        return _json({**head, "locked": False, **await svc.view(uid)})
    except SosUnavailable:
        return _err("unavailable", SosUnavailable.WORDS, 503)


@router.get("/sheet", include_in_schema=False)
async def sos_sheet(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    _, svc = _service(request)
    if svc is None:
        return _json({"enabled": False, "numbers": [], "first": None, "emergency": "112"})
    return _json(await svc.sheet(uid, locked=await _locked(request)))


@router.put("/label", include_in_schema=False)
async def sos_label(
    body: LabelBody, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    svc = await _for_change(request, uid)
    if isinstance(svc, JSONResponse):
        return svc
    try:
        await svc.set_label(uid, body.label)
        return _json({"part": PART, "locked": False, **await svc.view(uid)})
    except (SosRefused, SosOff, SosUnavailable) as exc:
        return _refusal(exc)


@router.post("/contacts", include_in_schema=False)
async def sos_add(
    body: ContactBody, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    svc = await _for_change(request, uid)
    if isinstance(svc, JSONResponse):
        return svc
    try:
        c = await svc.add_contact(uid, body.label, body.phone)
    except (SosRefused, SosOff, SosUnavailable) as exc:
        return _refusal(exc)
    return _json({"contact": {"id": c.id, "label": c.label}})


@router.delete("/contacts/{cid}", include_in_schema=False)
async def sos_remove(cid: str, request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = await _for_change(request, uid)
    if isinstance(svc, JSONResponse):
        return svc
    if not re.fullmatch(CONTACT_ID, cid):
        return _err("not_found", "That contact is not on your list, Sir.", 404)
    try:
        removed = await svc.remove_contact(uid, cid)
    except (SosRefused, SosOff, SosUnavailable) as exc:
        return _refusal(exc)
    if not removed:
        return _err("not_found", "That contact is not on your list, Sir.", 404)
    return _json({"removed": True})


@router.post("/contacts/{cid}/link", include_in_schema=False)
async def sos_link(cid: str, request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = await _for_change(request, uid)
    if isinstance(svc, JSONResponse):
        return svc
    try:
        return _json(await svc.join_link(uid, cid))
    except SosRefused as exc:
        return _err(exc.code, str(exc), 503 if exc.code == "telegram_off" else 422)
    except (SosOff, SosUnavailable) as exc:
        return _refusal(exc)


@router.post("/send", include_in_schema=False)
async def sos_send(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    """After the sheet's hold and countdown. Every outcome is 200 with the honest view, so the
    sheet always shows the SMS screen and 112; every other answer carries plain `words` and
    `detail` (the console shows `detail`). The body is read here, not by FastAPI, so a bad body is
    one plain 422 and never a list of validation objects; a place that does not validate is
    dropped and the SOS still goes. While locked only a real SOS goes."""
    _, svc = _service(request)
    if svc is None:
        return _not_sent(
            "Emergency SOS isn't set up on this server, Sir. Call 112.", "sos_off", 503
        )
    try:
        press = parse_press(await request.json())
    except (ValueError, RecursionError):
        press = None
    if press is None:
        return _not_sent(UNREADABLE, "invalid", 422)
    allowed, _ = _sends.allow(uid)
    if not allowed:
        words = "Too many presses at once, Sir. Call 112 now if you need help."
        return _not_sent(words, "busy", 429)
    locked = await _locked(request)
    if locked and press.kind != "real":
        return _not_sent(LOCKED_SEND, "device_locked", 423)
    try:
        result = await svc.send(
            uid,
            press.kind,
            press.location,
            via="web",
            press_id=press.press_id,
            locked=locked,
            location_dropped=press.dropped,
        )
    except Exception as exc:  # noqa: BLE001 - never a bare 500: the sheet must offer SMS and 112
        log.error("SOS: the send failed", extra={"error": type(exc).__name__})
        return _not_sent(SEND_FAILED, "failed", 500)
    return _json(result.view())


def _not_sent(words: str, code: str, status: int) -> JSONResponse:
    """A send the server could not even try: never "sent", always 112 and plain `words` (also as
    `detail`, which the console shows). The SMS numbers are the console's own, from the sheet."""
    body = {
        "sent": False,
        "error": code,
        "outcome": "unavailable",
        "words": words,
        "detail": words,
        "sms": {"numbers": [], "text": ""},
        "call": {"first": None, "emergency": "112"},
    }
    return _json(body, status)


__all__ = ["PART", "router"]
