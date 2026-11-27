# src/jarvis/api/voice_profile_routes.py
"""R5.2 "Your voice": the router skeleton (I0; docs/plans/r5-2-integration/I0-SEAMS.md). Every route
is thin: it checks the owner, the path and the body's size and shape, then calls the part wired on
`app.state` (I1 joins them), so V2, V3 and V4 fill the handlers from their own modules without
editing this file. Mounted by `jarvis.api.voice.install_voice` (app.py stays under its guard).

    owner (require_auth + current_user), /v1/voice/profile:
    GET  ""                          the profile: engines ranked, the chosen one   api.view
    PUT  ""                          choose an engine, corrections on / off, ...  api.update
    GET  /session                    prompts, blocks, progress                    api.session
    POST /session/start                                                           api.start
    PUT  /session/clips/{prompt_id}  {audio: base64 WAV, browser_heard?}          api.put_clip
    POST /session/score              the comparison; 402 needs_yes with the ₹     api.score
    GET  /session/results                                                         api.results
    POST /recheck                    "Check again"                                api.recheck
    POST /recordings/delete          {confirm: "DELETE", wakeword?: true}: "Delete  api.delete_
                                     my recordings" (and the wake-word files)     recordings
    GET  /laptop                     the laptop speech kit's health               laptop.status
    GET  /wakeword                   stage 1 and stage 2, their jobs              wakeword.status
    POST /wakeword/train             {artifact: "verifier" | "owned"}             wakeword.train
    GET  /wakeword/verifier          stage 1's plain weights (bytes, type)        wakeword.verifier
    GET  /wakeword/model             stage 2's ONNX model (bytes, type)           wakeword.model

(api = `app.state.voice_profile_api` V3, laptop = `voice_laptop` V2, wakeword = `voice_wakeword`
V4.) Not wired yet: 501 {"error": "not_built"}. `voice_profile_enabled` off: 503
{"error": "voice_profile_off"}. A handler refuses with `ProfileRefused` -> {error, detail}. Bodies
are JSON objects of at most `BODY_MAX` bytes (a clip: `CLIP_BODY_MAX`; 422 input_rejected / 413
too_large). Every answer is `no-store`: a profile, a wake-word file or a voice's results are the
owner's, never cached. /v1 is under the app's per-client rate limit (`api.ratelimit`).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Final, cast

from fastapi import APIRouter, Depends, FastAPI, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from jarvis.api.auth import require_auth
from jarvis.api.body import BodyTooLarge, read_capped
from jarvis.api.identity import current_user
from jarvis.config import Settings
from jarvis.localspeech.protocol import PROMPT_ID
from jarvis.voice.profile_ports import ProfileRefused

PREFIX: Final = "/v1/voice/profile"
BODY_MAX: Final = 16_384
CLIP_BODY_MAX: Final = 1_000_000  # 20 s of 16 kHz PCM16 WAV as base64 is ~854 KB (app cap 2.1 MB)
NO_STORE: Final = {"Cache-Control": "no-store"}
API_SLOT, LAPTOP_SLOT, WAKE_SLOT = "voice_profile_api", "voice_laptop", "voice_wakeword"
CONFIRM_WORD: Final = "DELETE"  # as the privacy dashboard's deletes
NOT_BUILT = "Your voice is not ready yet: this part of R5.2 is still being built."
PROFILE_OFF = "Your voice is switched off on this server (JARVIS_VOICE_PROFILE_ENABLED)."
NOT_AN_OBJECT = "Send a JSON object."
CONFIRM_NEEDED = f'Deleting your recordings needs {{"confirm": "{CONFIRM_WORD}"}}.'
DELETE_KEYS: Final = frozenset({"confirm", "wakeword"})
BAD_DELETE = 'Send {"confirm": "DELETE"} and, to delete the wake-word files too, "wakeword": true.'

# (method, path) -> (slot, the part's method): the route table and its seams
SLOTS: Final[dict[tuple[str, str], tuple[str, str]]] = {
    ("GET", PREFIX): (API_SLOT, "view"),
    ("PUT", PREFIX): (API_SLOT, "update"),
    ("GET", f"{PREFIX}/session"): (API_SLOT, "session"),
    ("POST", f"{PREFIX}/session/start"): (API_SLOT, "start"),
    ("PUT", f"{PREFIX}/session/clips/{{prompt_id}}"): (API_SLOT, "put_clip"),
    ("POST", f"{PREFIX}/session/score"): (API_SLOT, "score"),
    ("GET", f"{PREFIX}/session/results"): (API_SLOT, "results"),
    ("POST", f"{PREFIX}/recheck"): (API_SLOT, "recheck"),
    ("POST", f"{PREFIX}/recordings/delete"): (API_SLOT, "delete_recordings"),
    ("GET", f"{PREFIX}/laptop"): (LAPTOP_SLOT, "status"),
    ("GET", f"{PREFIX}/wakeword"): (WAKE_SLOT, "status"),
    ("POST", f"{PREFIX}/wakeword/train"): (WAKE_SLOT, "train"),
    ("GET", f"{PREFIX}/wakeword/verifier"): (WAKE_SLOT, "verifier"),
    ("GET", f"{PREFIX}/wakeword/model"): (WAKE_SLOT, "model"),
}
ROUTES: Final[tuple[tuple[str, str], ...]] = tuple(SLOTS)

router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])
PromptIdPath = Path(pattern=PROMPT_ID)
Run = Callable[[Any], Awaitable[BaseModel | dict[str, Any]]]


# ---- answers -------------------------------------------------------------------------------------
def _err(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status, headers=NO_STORE)


def _json(result: BaseModel | dict[str, Any]) -> JSONResponse:
    body = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
    return JSONResponse(body, headers=NO_STORE)


def _part(request: Request, slot: str) -> tuple[Any, JSONResponse | None]:
    if not cast(Settings, request.app.state.settings).voice_profile_enabled:
        return None, _err(503, "voice_profile_off", PROFILE_OFF)
    part = getattr(request.app.state, slot, None)
    if part is None:
        return None, _err(501, "not_built", NOT_BUILT)
    return part, None


async def _answer(request: Request, slot: str, run: Run) -> Response:
    part, refused = _part(request, slot)
    if refused is not None:
        return refused
    try:
        return _json(await run(part))
    except ProfileRefused as exc:
        return _err(exc.status, exc.code, exc.words)


async def _body(request: Request, cap: int) -> dict[str, Any] | JSONResponse:
    raw = await read_capped(request, cap, too_large=lambda: BodyTooLarge(cap))
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
    *,
    cap: int = BODY_MAX,
) -> Response:
    _, refused = _part(request, slot)
    if refused is not None:
        return refused
    body = await _body(request, cap)
    if isinstance(body, JSONResponse):
        return body
    return await _answer(request, slot, lambda part: run(part, body))


async def _file(request: Request, slot: str, method: str, uid: str) -> Response:
    part, refused = _part(request, slot)
    if refused is not None:
        return refused
    try:
        data, media = await getattr(part, method)(uid)
    except ProfileRefused as exc:
        return _err(exc.status, exc.code, exc.words)
    return Response(content=data, media_type=media, headers=NO_STORE)


# ---- the profile and the session (V3) ------------------------------------------------------------
@router.get("", include_in_schema=False)
async def view(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.view(uid))


@router.put("", include_in_schema=False)
async def update(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.update(uid, b))


@router.get("/session", include_in_schema=False)
async def session(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.session(uid))


@router.post("/session/start", include_in_schema=False)
async def start(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.start(uid, b))


@router.put("/session/clips/{prompt_id}", include_in_schema=False)
async def put_clip(
    request: Request, prompt_id: str = PromptIdPath, uid: str = Depends(current_user)
) -> Response:
    return await _with_body(
        request, API_SLOT, lambda api, b: api.put_clip(uid, prompt_id, b), cap=CLIP_BODY_MAX
    )


@router.post("/session/score", include_in_schema=False)
async def score(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.score(uid, b))


@router.get("/session/results", include_in_schema=False)
async def results(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, API_SLOT, lambda api: api.results(uid))


@router.post("/recheck", include_in_schema=False)
async def recheck(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: api.recheck(uid, b))


async def _confirmed_delete(api: Any, body: dict[str, Any], uid: str) -> BaseModel | dict[str, Any]:
    if body.get("confirm") != CONFIRM_WORD:
        raise ProfileRefused(422, "confirm_needed", CONFIRM_NEEDED)
    wakeword = body.get("wakeword", False)
    if not set(body) <= DELETE_KEYS or not isinstance(wakeword, bool):
        raise ProfileRefused(422, "input_rejected", BAD_DELETE)
    result: BaseModel | dict[str, Any] = await api.delete_recordings(uid, wakeword=wakeword)
    return result


@router.post("/recordings/delete", include_in_schema=False)
async def delete_recordings(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, API_SLOT, lambda api, b: _confirmed_delete(api, b, uid))


# ---- the laptop kit (V2) and the wake word (V4) --------------------------------------------------
@router.get("/laptop", include_in_schema=False)
async def laptop(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, LAPTOP_SLOT, lambda part: part.status(uid))


@router.get("/wakeword", include_in_schema=False)
async def wakeword(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _answer(request, WAKE_SLOT, lambda part: part.status(uid))


@router.post("/wakeword/train", include_in_schema=False)
async def wakeword_train(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _with_body(request, WAKE_SLOT, lambda part, b: part.train(uid, b))


@router.get("/wakeword/verifier", include_in_schema=False)
async def wakeword_verifier(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _file(request, WAKE_SLOT, "verifier", uid)


@router.get("/wakeword/model", include_in_schema=False)
async def wakeword_model(request: Request, uid: str = Depends(current_user)) -> Response:
    return await _file(request, WAKE_SLOT, "model", uid)


def install_voice_profile_routes(app: FastAPI) -> None:
    """R5.2: /v1/voice/profile (owner)."""
    app.include_router(router)


__all__ = [
    "BODY_MAX",
    "CLIP_BODY_MAX",
    "CONFIRM_WORD",
    "PREFIX",
    "ROUTES",
    "SLOTS",
    "install_voice_profile_routes",
    "router",
]
