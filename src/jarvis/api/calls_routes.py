# src/jarvis/api/calls_routes.py
"""R18 calls: the router skeleton (I0; docs/plans/r18-calls/I0-SEAMS.md). Every route is thin: it
checks the owner, the path and the body's size and shape, then calls the part wired on `app.state`
(I1 joins them), so A1, A2 and C fill the handlers from their own modules without editing this file.

    owner (require_auth + current_user), {prefix}/v1/calls:
    GET    /status                          desk + phone ready check       calls_api.status
    POST   /cards                           write a call card              calls_api.create_card
    POST   /cards/estimate                  ₹ estimate of a draft          calls_api.estimate
    GET    /cards/{card_id}                                                calls_api.get_card
    POST   /cards/{card_id}/approve         his tap (+ passkey): the call  calls_api.approve
    POST   /cards/{card_id}/cancel                                         calls_api.cancel
    GET    /records?limit=                  newest first                   calls_api.list_records
    GET    /records/{call_id}                                              calls_api.get_record
    DELETE /records/{call_id}               audio, transcript, summary     calls_api.delete_record
    PUT    /records/{call_id}/keep          {keep: bool}                   calls_api.keep_record
    GET    /records/{call_id}/audio         the recording (bytes, type)    calls_api.record_audio
    POST   /records/{call_id}/booking/undo  the calendar add's Undo        calls_api.undo_booking
    GET    /settings                                                       calls_api.get_settings
    PUT    /settings                        a subset of CallSettings       calls_api.put_settings
    GET    /languages                       the language table             calls_api.languages
    POST   /languages/check                 run the language check         calls_api.run_language_
                                                                           check
    POST   /desk/code                       a link code for the desk       calls_desk_door.code
    DELETE /desk                            unlink the desk                calls_desk_door.unlink
    GET    /desk/kit, /desk/kit/info        the call desk's kit zip        calls_desk_kit
    the desk's own request (no session; its link code is the proof):
    POST   /v1/calls/desk/link                                             calls_desk_door.link
    WebSockets:
    /v1/calls/desk/ws                       the desk (A2 checks its signed credentials)
    /v1/calls/{call_id}/live                the owner's live listen (checked here, then A2)

Not wired yet: 501 {"error": "not_built"}; a WebSocket closes 4501. `calls_enabled` off: 503
{"error": "calls_off"}. A handler refuses with `CallsRefused` -> {error, detail}. Bodies are JSON
objects of at most `BODY_MAX` bytes (422 input_rejected / 413 too_large). Every answer is
`no-store`. /v1 is also under the app's per-client rate limit (`api.ratelimit`).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from jarvis.api.auth import require_auth, session_email
from jarvis.api.body import BodyTooLarge, read_capped
from jarvis.api.identity import current_user, primary_user_id, user_id_for_email
from jarvis.calls.models import CALL_ID, CALL_ID_RE, CARD_ID
from jarvis.calls.ports import CallsRefused
from jarvis.calls.protocol import (
    DESK_WS_PATH,
    LIVE_WS_PATH,
    WS_GONE,
    WS_NOT_BUILT,
    WS_UNAUTHORIZED,
)
from jarvis.config import AuthMode, Settings
from jarvis.logging import get_logger

log = get_logger(__name__)

PREFIX = "/v1/calls"
BODY_MAX = 16_384
LIST_LIMIT_MAX = 200
NO_STORE = {"Cache-Control": "no-store"}
API_SLOT, DOOR_SLOT, KIT_SLOT, SOCKETS_SLOT = (
    "calls_api",
    "calls_desk_door",
    "calls_desk_kit",
    "calls_sockets",
)
NOT_BUILT = "Calls are not ready yet: this part of R18 is still being built."
CALLS_OFF = "Calls are switched off on this server (JARVIS_CALLS_ENABLED)."
NOT_AN_OBJECT = "Send a JSON object."
KIT_NAME = "JARVIS-Call-desk-kit.zip"

ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", f"{PREFIX}/status"),
    ("POST", f"{PREFIX}/cards"),
    ("POST", f"{PREFIX}/cards/estimate"),
    ("GET", f"{PREFIX}/cards/{{card_id}}"),
    ("POST", f"{PREFIX}/cards/{{card_id}}/approve"),
    ("POST", f"{PREFIX}/cards/{{card_id}}/cancel"),
    ("GET", f"{PREFIX}/records"),
    ("GET", f"{PREFIX}/records/{{call_id}}"),
    ("DELETE", f"{PREFIX}/records/{{call_id}}"),
    ("PUT", f"{PREFIX}/records/{{call_id}}/keep"),
    ("GET", f"{PREFIX}/records/{{call_id}}/audio"),
    ("POST", f"{PREFIX}/records/{{call_id}}/booking/undo"),
    ("GET", f"{PREFIX}/settings"),
    ("PUT", f"{PREFIX}/settings"),
    ("GET", f"{PREFIX}/languages"),
    ("POST", f"{PREFIX}/languages/check"),
    ("POST", f"{PREFIX}/desk/code"),
    ("DELETE", f"{PREFIX}/desk"),
    ("GET", f"{PREFIX}/desk/kit"),
    ("GET", f"{PREFIX}/desk/kit/info"),
    ("POST", f"{PREFIX}/desk/link"),
)
WEBSOCKETS: tuple[str, ...] = (DESK_WS_PATH, LIVE_WS_PATH)

router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])
open_router = APIRouter()  # the desk's link request and both WebSockets: no owner session here

CardId = Path(pattern=CARD_ID)
CallIdPath = Path(pattern=CALL_ID)


# ---- answers -------------------------------------------------------------------------------------
def _err(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status, headers=NO_STORE)


def _json(result: BaseModel | dict[str, Any]) -> JSONResponse:
    body = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
    return JSONResponse(body, headers=NO_STORE)


def _settings(app: Any) -> Settings:
    return cast(Settings, app.state.settings)


def _part(request: Request, slot: str) -> tuple[Any, JSONResponse | None]:
    if not _settings(request.app).calls_enabled:
        return None, _err(503, "calls_off", CALLS_OFF)
    part = getattr(request.app.state, slot, None)
    if part is None:
        return None, _err(501, "not_built", NOT_BUILT)
    return part, None


async def _answer(
    request: Request, slot: str, run: Callable[[Any], Awaitable[BaseModel | dict[str, Any]]]
) -> Response:
    part, refused = _part(request, slot)
    if refused is not None:
        return refused
    try:
        return _json(await run(part))
    except CallsRefused as exc:
        return _err(exc.status, exc.code, exc.words)


async def _body(request: Request) -> dict[str, Any] | JSONResponse:
    raw = await read_capped(request, BODY_MAX, too_large=lambda: BodyTooLarge(BODY_MAX))
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _err(422, "input_rejected", NOT_AN_OBJECT)
    if not isinstance(data, dict):
        return _err(422, "input_rejected", NOT_AN_OBJECT)
    return data


async def _with_body(
    request: Request,
    slot: str,
    run: Callable[[Any, dict[str, Any]], Awaitable[BaseModel | dict[str, Any]]],
) -> Response:
    _, refused = _part(request, slot)
    if refused is not None:
        return refused
    body = await _body(request)
    if isinstance(body, JSONResponse):
        return body
    return await _answer(request, slot, lambda part: run(part, body))


# ---- cards ---------------------------------------------------------------------------------------
@router.get("/status", include_in_schema=False)
async def calls_status(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.status(uid))


@router.post("/cards", include_in_schema=False)
async def create_card(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.create_card(uid, b))


@router.post("/cards/estimate", include_in_schema=False)
async def estimate_card(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.estimate(uid, b))


@router.get("/cards/{card_id}", include_in_schema=False)
async def get_card(
    request: Request, card_id: str = CardId, uid: str = Depends(current_user)
) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.get_card(uid, card_id))


@router.post("/cards/{card_id}/approve", include_in_schema=False)
async def approve_card(
    request: Request, card_id: str = CardId, uid: str = Depends(current_user)
) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.approve(uid, card_id, b))


@router.post("/cards/{card_id}/cancel", include_in_schema=False)
async def cancel_card(
    request: Request, card_id: str = CardId, uid: str = Depends(current_user)
) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.cancel(uid, card_id))


# ---- records -------------------------------------------------------------------------------------
@router.get("/records", include_in_schema=False)
async def list_records(
    request: Request,
    limit: int = Query(default=50, ge=1, le=LIST_LIMIT_MAX),
    uid: str = Depends(current_user),
) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.list_records(uid, limit))


@router.get("/records/{call_id}", include_in_schema=False)
async def get_record(
    request: Request, call_id: str = CallIdPath, uid: str = Depends(current_user)
) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.get_record(uid, call_id))


@router.delete("/records/{call_id}", include_in_schema=False)
async def delete_record(
    request: Request, call_id: str = CallIdPath, uid: str = Depends(current_user)
) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.delete_record(uid, call_id))


class _Keep(BaseModel):
    keep: bool


@router.put("/records/{call_id}/keep", include_in_schema=False)
async def keep_record(
    request: Request, body: _Keep, call_id: str = CallIdPath, uid: str = Depends(current_user)
) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.keep_record(uid, call_id, body.keep))


@router.get("/records/{call_id}/audio", include_in_schema=False)
async def record_audio(
    request: Request, call_id: str = CallIdPath, uid: str = Depends(current_user)
) -> Response:
    api, refused = _part(request, API_SLOT)
    if refused is not None:
        return refused
    try:
        data, media = await api.record_audio(uid, call_id)
    except CallsRefused as exc:
        return _err(exc.status, exc.code, exc.words)
    return Response(content=data, media_type=media, headers=NO_STORE)


@router.post("/records/{call_id}/booking/undo", include_in_schema=False)
async def undo_booking(
    request: Request, call_id: str = CallIdPath, uid: str = Depends(current_user)
) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.undo_booking(uid, call_id))


# ---- settings and languages ----------------------------------------------------------------------
@router.get("/settings", include_in_schema=False)
async def get_settings(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.get_settings(uid))


@router.put("/settings", include_in_schema=False)
async def put_settings(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.put_settings(uid, b))


@router.get("/languages", include_in_schema=False)
async def languages(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.languages(uid))


@router.post("/languages/check", include_in_schema=False)
async def language_check(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.run_language_check(uid, b))


# ---- the call desk -------------------------------------------------------------------------------
@router.post("/desk/code", include_in_schema=False)
async def desk_code(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, DOOR_SLOT, lambda door: door.code(uid))


@router.delete("/desk", include_in_schema=False)
async def desk_unlink(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, DOOR_SLOT, lambda door: door.unlink(uid))


@router.get("/desk/kit", include_in_schema=False)
async def desk_kit(request: Request, uid: str = Depends(current_user)) -> Response:
    kit, refused = _part(request, KIT_SLOT)
    if refused is not None:
        return refused
    data: bytes = kit.build()
    headers = NO_STORE | {
        "Content-Disposition": f'attachment; filename="{KIT_NAME}"',
        "X-Kit-Sha256": hashlib.sha256(data).hexdigest(),
    }
    return Response(content=data, media_type="application/zip", headers=headers)


@router.get("/desk/kit/info", include_in_schema=False)
async def desk_kit_info(request: Request, uid: str = Depends(current_user)) -> Response:
    kit, refused = _part(request, KIT_SLOT)
    if refused is not None:
        return refused
    data: bytes = kit.build()
    sha = hashlib.sha256(data).hexdigest()
    return _json({"sha256": sha, "size": len(data), "version": str(kit.version)})


@open_router.post(f"{PREFIX}/desk/link", include_in_schema=False)
async def desk_link(request: Request) -> Response:
    return await _with_body(request, DOOR_SLOT, lambda door, b: door.link(b))


# ---- WebSockets ----------------------------------------------------------------------------------
def same_origin(ws: WebSocket, s: Settings) -> bool:
    """A cookie session's socket must come from JARVIS's own page (cross-site WebSocket
    hijacking: browsers send cookies on any origin's handshake, and always send `Origin`)."""
    origin = (ws.headers.get("origin") or "").rstrip("/")
    if not origin:
        return False
    if s.public_base_url:
        want = urlsplit(s.public_base_url)
        return origin == f"{want.scheme}://{want.netloc}"
    host = ws.headers.get("host") or ""
    return bool(host) and origin in (f"http://{host}", f"https://{host}")


def ws_owner(ws: WebSocket, s: Settings) -> str | None:
    """The owner's id for a live socket: the bearer token, or his session cookie from JARVIS's
    own origin, or dev with no token (as `require_auth`); else None."""
    auth = ws.headers.get("authorization") or ""
    if s.api_token is not None and auth.startswith("Bearer "):
        if secrets.compare_digest(auth[7:], s.api_token.get_secret_value()):
            return primary_user_id(s)
        return None
    email = session_email(cast(Request, ws), s)  # reads only scope["session"], as a Request does
    if email is not None:
        return user_id_for_email(email) if same_origin(ws, s) else None
    if s.api_token is None and s.auth_mode is AuthMode.TOKEN and s.env == "dev":
        return primary_user_id(s)
    return None


@open_router.websocket(DESK_WS_PATH)
async def desk_socket(ws: WebSocket) -> None:
    sockets = getattr(ws.app.state, SOCKETS_SLOT, None)
    if sockets is None or not _settings(ws.app).calls_enabled:
        await ws.close(code=WS_NOT_BUILT)
        return
    await sockets.desk(ws)


@open_router.websocket(LIVE_WS_PATH)
async def live_socket(ws: WebSocket, call_id: str) -> None:
    s = _settings(ws.app)
    uid = ws_owner(ws, s)
    if uid is None:
        await ws.close(code=WS_UNAUTHORIZED)
        return
    if not CALL_ID_RE.fullmatch(call_id):
        await ws.close(code=WS_GONE)
        return
    sockets = getattr(ws.app.state, SOCKETS_SLOT, None)
    if sockets is None or not s.calls_enabled:
        await ws.close(code=WS_NOT_BUILT)
        return
    await sockets.live(ws, uid, call_id)


def install_calls_routes(app: FastAPI) -> None:
    """R18: /v1/calls (owner), the desk's link request and the two WebSockets."""
    app.include_router(router)
    app.include_router(open_router)


__all__ = [
    "BODY_MAX",
    "PREFIX",
    "ROUTES",
    "WEBSOCKETS",
    "install_calls_routes",
    "open_router",
    "router",
    "same_origin",
    "ws_owner",
]
