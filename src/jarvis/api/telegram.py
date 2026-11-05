# src/jarvis/api/telegram.py
"""Telegram routes (R1 D1/D2/D6; Layer 1).

POST /telegram/webhook      Telegram only. Outside /v1, no `require_auth`. 404 when Telegram is not
                            set up (no token or no webhook secret); a missing or wrong
                            `X-Telegram-Bot-Api-Secret-Token` (hmac.compare_digest) is a BARE 401:
                            nothing is parsed, it is logged and not audited; body <= 64 KB (413).
                            Everything accepted or ignored is 200 (Telegram repeats non-2xx
                            replies); only a storage failure while claiming the update is 503.
GET  /v1/telegram           {configured: false} or {configured, bot_username, paired, paired_at,
                            pairing_pending (a code is alive; the console says when it is not),
                            account_hint: "••1234", webhook: {registered, pending, last_error},
                            allow_private_reads, allow_personal_reads, allow_home_reads,
                            alerts: {approval_waiting, offline, brief_ready, vault_expiry}}
POST /v1/telegram/pair      {code, link, expires_in_s}   (409 already_paired, 503
                            telegram_unavailable)
DELETE /v1/telegram/pair    unpair (audited) -> the view
PUT  /v1/telegram/settings  {allow_private_reads?, allow_personal_reads?, allow_home_reads?,
                            alerts?} -> the view (409 not_paired). R2 D12: allow_personal_reads is
                            the vault list, notes and things switch, separate from the private-reads
                            one. R3 D15: allow_home_reads (home devices, camera history, faces) is
                            a third, opened by neither of the others.
POST /v1/telegram/test-alert {sent, reason?}

All /v1 routes: `require_auth` + `current_user`, errors {error, detail}. Telegram's own error text
and the bot token never appear. `build_telegram` returns None unless BOTH secrets are set.
"""

from __future__ import annotations

import hmac
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool

from jarvis.api.auth import require_auth
from jarvis.api.body import BodyTooLarge, read_capped
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs
from jarvis.telegram.alerts import ALERT_TEXT
from jarvis.telegram.client import TelegramClient, TelegramError
from jarvis.telegram.models import AlertToggles, TelegramLink, parse_update
from jarvis.telegram.pairing import deep_link
from jarvis.telegram.service import TelegramService
from jarvis.telegram.store import TelegramStore
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)
WEBHOOK_PATH = "/telegram/webhook"
WEBHOOK_BODY_BYTES = 64 * 1024
SECRET_HEADER = "x-telegram-bot-api-secret-token"
PAIR_PER_MINUTE = 10
CHANGES_PER_MINUTE = 20
router = APIRouter(prefix="/v1/telegram", dependencies=[Depends(require_auth)])
hook_router = APIRouter()


def build_telegram(
    s: Settings, docs: Docs, *, audit: AuditTrail, http: httpx.AsyncClient | None = None
) -> TelegramService | None:
    """The service, or None (feature OFF) unless the bot token and webhook secret are both set."""
    if s.telegram_bot_token is None or s.telegram_webhook_secret is None:
        return None
    if (
        not s.telegram_bot_token.get_secret_value()
        or not s.telegram_webhook_secret.get_secret_value()
    ):
        return None
    client = TelegramClient(s.telegram_bot_token, http=http)
    return TelegramService(client, TelegramStore(docs, prefix=s.firestore_prefix), audit)


def _svc(request: Request) -> TelegramService | None:
    return getattr(request.app.state, "telegram", None)


def _err(status: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "detail": detail})


def _off() -> JSONResponse:
    return _err(404, "telegram_off", "Telegram isn't set up on this server yet.")


def _secret_ok(request: Request) -> bool:
    s: Settings = request.app.state.settings
    if s.telegram_webhook_secret is None:
        return False
    want = s.telegram_webhook_secret.get_secret_value().encode()
    if not want:
        return False  # an empty secret never matches an empty header
    got = request.headers.get(SECRET_HEADER, "").encode()
    return hmac.compare_digest(got, want)  # always compared, constant time


@hook_router.post(WEBHOOK_PATH, response_model=None)
async def webhook(request: Request) -> Response:
    svc = _svc(request)
    s: Settings = request.app.state.settings
    if svc is None or s.telegram_webhook_secret is None or s.telegram_bot_token is None:
        return Response(status_code=404)
    if not _secret_ok(request):
        log.warning("telegram webhook: wrong or missing secret")
        return Response(status_code=401)
    try:
        body = await read_capped(request, WEBHOOK_BODY_BYTES, too_large=lambda: BodyTooLarge())
    except BodyTooLarge:
        return Response(status_code=413)
    update = parse_update(body)
    if update is None:
        return Response(status_code=200)
    if svc.brain is None:
        svc.bind(request.app.state.brain)
    try:
        await svc.handle(update)
    except Exception as exc:  # noqa: BLE001 - only the claim can raise: Telegram should retry
        log.error("telegram webhook: update not taken", extra={"error": type(exc).__name__})
        return Response(status_code=503)
    return Response(status_code=200)


# ---- the owner's console routes ----------------------------------------------------------------


class AlertsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_waiting: StrictBool | None = None
    offline: StrictBool | None = None
    brief_ready: StrictBool | None = None
    vault_expiry: StrictBool | None = None


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_private_reads: StrictBool | None = None
    allow_personal_reads: StrictBool | None = None
    allow_home_reads: StrictBool | None = None
    alerts: AlertsPatch | None = None


def _hint(link: TelegramLink) -> str:
    return "••" + str(link.tg_user_id)[-4:]


async def _view(svc: TelegramService, uid: str) -> dict[str, Any]:
    link = await svc.store.get(uid)
    try:
        username: str | None = await svc.client.get_me()
    except TelegramError:
        username = None
    try:
        webhook_state: dict[str, Any] = await svc.client.webhook_info()
    except TelegramError:
        webhook_state = {
            "registered": None,
            "pending": 0,
            "last_error": "Telegram can't be reached.",
        }
    return {
        "configured": True,
        "bot_username": username,
        "paired": link is not None,
        "paired_at": link.paired_at if link else None,
        "pairing_pending": await svc.store.has_pending(uid),
        "account_hint": _hint(link) if link else None,
        "webhook": webhook_state,
        "allow_private_reads": bool(link and link.allow_private_reads),
        "allow_personal_reads": bool(link and link.allow_personal_reads),
        "allow_home_reads": bool(link and link.allow_home_reads),
        "alerts": (link.alerts if link else AlertToggles()).model_dump(),
    }


@router.get("", response_model=None)
async def telegram_view(
    svc: TelegramService | None = Depends(_svc), uid: str = Depends(current_user)
) -> Any:
    if svc is None:
        return {"configured": False}
    return await _view(svc, uid)


@router.post("/pair", response_model=None)
async def pair(
    request: Request, svc: TelegramService | None = Depends(_svc), uid: str = Depends(current_user)
) -> Any:
    if svc is None:
        return _off()
    if not request.app.state.telegram_pair_limit.allow(uid)[0]:
        return _err(429, "rate_limited", "Too many tries; wait a moment.")
    if await svc.store.get(uid) is not None:
        return _err(409, "already_paired", "Telegram is already paired. Unpair it first.")
    try:
        username = await svc.client.get_me()
    except TelegramError:
        return _err(503, "telegram_unavailable", "Couldn't reach Telegram. Try again in a minute.")
    code, ttl = await svc.store.start_pairing(uid)
    await record_change(request, agent="telegram", tool="telegram_pair_start", args={"user": uid})
    return {"code": code, "link": deep_link(username, code), "expires_in_s": ttl}


@router.delete("/pair", response_model=None)
async def unpair(
    request: Request, svc: TelegramService | None = Depends(_svc), uid: str = Depends(current_user)
) -> Any:
    if svc is None:
        return _off()
    if await svc.store.unpair(uid):
        await record_change(request, agent="telegram", tool="telegram_unpair", args={"user": uid})
    return await _view(svc, uid)


@router.put("/settings", response_model=None)
async def settings(
    body: SettingsBody,
    request: Request,
    svc: TelegramService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> Any:
    if svc is None:
        return _off()
    if not request.app.state.telegram_change_limit.allow(uid)[0]:
        return _err(429, "rate_limited", "Too many changes; wait a moment.")
    alerts = body.alerts.model_dump(exclude_none=True) if body.alerts else None
    link = await svc.store.set_settings(
        uid,
        allow_private_reads=body.allow_private_reads,
        alerts=alerts,
        allow_personal_reads=body.allow_personal_reads,
        allow_home_reads=body.allow_home_reads,
    )
    if link is None:
        return _err(409, "not_paired", "Pair Telegram first.")
    private = "on" if link.allow_private_reads else "off"
    personal = "on" if link.allow_personal_reads else "off"
    home = "on" if link.allow_home_reads else "off"
    await record_change(
        request,
        agent="telegram",
        tool="telegram_settings",
        args={
            "private_reads": link.allow_private_reads,
            "personal_reads": link.allow_personal_reads,
            "home_reads": link.allow_home_reads,
            "alerts": sorted(alerts or {}),
        },
        detail=f"private reads {private}; personal reads {personal}; home reads {home}",
    )
    return await _view(svc, uid)


@router.post("/test-alert", response_model=None)
async def test_alert(
    svc: TelegramService | None = Depends(_svc), uid: str = Depends(current_user)
) -> Any:
    if svc is None:
        return {"sent": False, "reason": "Telegram isn't set up on this server yet."}
    res = await svc.alerts.send(uid, ALERT_TEXT["test"], kind="test")
    return {"sent": True} if res.sent else {"sent": False, "reason": res.reason}


def install_telegram(app: FastAPI) -> None:
    """Mount the webhook and /v1/telegram on `app`. The service is read from
    `app.state.telegram` at request time (None: the feature is off)."""
    app.state.telegram_pair_limit = RateLimiter(PAIR_PER_MINUTE)
    app.state.telegram_change_limit = RateLimiter(CHANGES_PER_MINUTE)
    app.include_router(hook_router)
    app.include_router(router)


__all__ = ["WEBHOOK_PATH", "build_telegram", "install_telegram"]
