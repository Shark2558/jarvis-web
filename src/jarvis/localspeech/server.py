# src/jarvis/localspeech/server.py
"""The kit's speech server (R5.2 V1; plan 3.1, D1): exactly `protocol.ROUTES` under `/v1`, on
127.0.0.1:11437 behind the Caddy gate (127.0.0.1:11436). Kit-safe: Starlette (BSD-3-Clause) and
uvicorn (BSD-3-Clause), pinned in the kit's requirements.

Every request:
- needs `Authorization: Bearer <key>` (checked in constant time) even though the gate checked it
  too: anything else on the laptop that reaches the port directly is refused, and a server
  started with no key (or one under `KEY_MIN_CHARS`) refuses everything (fail closed);
- is read up to `BODY_MAX` bytes and parsed with `protocol.parse_request` (strict, never quoted);
- answers JSON, `Cache-Control: no-store`; a refusal is `KitErrorBody` with its HTTP status.
Nothing here logs a body, audio, text, a header or the key; uvicorn's access log is off.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Final, TypeVar

from pydantic import BaseModel, ConfigDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from jarvis.localspeech.protocol import (
    API_PREFIX,
    BODY_MAX,
    CLIP,
    DELETE,
    HEALTH,
    JOB_ID_RE,
    JOBS,
    KEY_MIN_CHARS,
    RESULTS,
    ROUTES,
    SCORE,
    STT,
    TTS,
    WAKE_MODEL,
    WAKE_STATUS,
    WAKE_TRAIN,
    ClipIn,
    DeleteIn,
    KitErrorBody,
    KitErrorCode,
    KitRefused,
    ResultsIn,
    ScoreIn,
    SttRequest,
    TtsRequest,
    WakeModelIn,
    WakeTrainIn,
    parse_request,
)
from jarvis.localspeech.service import KitService

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)
STATUS: Final[dict[KitErrorCode, int]] = {
    "unauthorized": 401,
    "not_found": 404,
    "too_large": 413,
    "bad_request": 422,
    "bad_audio": 422,
    "unsupported_language": 422,
    "job_failed": 422,
    "engine_not_ready": 503,
    "busy": 503,
    "internal": 500,
}
NO_STORE: Final = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
_UNAUTHORIZED: Final = "The laptop speech kit needs its key."
_NO_KEY: Final = "The laptop speech kit has no key; start it with its start script."
_INTERNAL: Final = "The laptop speech kit had a problem."


class _Empty(BaseModel):
    """`POST /wakeword/status` takes `{}` and nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _json(model: BaseModel, status: int = 200) -> Response:
    return Response(model.model_dump_json(), status, NO_STORE, media_type="application/json")


def _refusal(code: KitErrorCode, words: str) -> Response:
    return _json(KitErrorBody(error=code, detail=words), STATUS[code])


def _key_ok(header: str, key: str) -> bool:
    scheme, _, given = header.partition(" ")
    if scheme != "Bearer" or not given:
        return False
    return hmac.compare_digest(given.encode(), key.encode())


async def _body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > BODY_MAX:
        raise KitRefused("too_large", f"Requests are limited to {BODY_MAX:,} bytes.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > BODY_MAX:
            raise KitRefused("too_large", f"Requests are limited to {BODY_MAX:,} bytes.")
        chunks.append(chunk)
    return b"".join(chunks)


Handler = Callable[[Request], Awaitable[BaseModel]]


def build_app(service: KitService, key: str) -> Starlette:
    """The kit's ASGI app; `key` is the gate's key (an empty or short one refuses everything)."""
    keyed = len(key) >= KEY_MIN_CHARS

    def endpoint(handler: Handler) -> Callable[[Request], Awaitable[Response]]:
        async def run(request: Request) -> Response:
            if not keyed:  # fail closed, as the gate does (503: nothing can be served)
                return _json(KitErrorBody(error="unauthorized", detail=_NO_KEY), 503)
            if not _key_ok(request.headers.get("authorization", ""), key):
                return _refusal("unauthorized", _UNAUTHORIZED)
            try:
                return _json(await handler(request))
            except KitRefused as refused:
                return _refusal(refused.code, refused.words)
            except Exception as exc:  # noqa: BLE001 - never a traceback, never the request
                log.error("kit request failed: %s", type(exc).__name__)
                return _refusal("internal", _INTERNAL)

        return run

    async def body(request: Request, model: type[M]) -> M:
        return parse_request(model, await _body(request))

    async def health(request: Request) -> BaseModel:
        return await service.health()

    async def stt(request: Request) -> BaseModel:
        return await service.stt(await body(request, SttRequest))

    async def tts(request: Request) -> BaseModel:
        return await service.tts(await body(request, TtsRequest))

    async def clip(request: Request) -> BaseModel:
        return await service.put_clip(await body(request, ClipIn))

    async def score(request: Request) -> BaseModel:
        return await service.score(await body(request, ScoreIn))

    async def results(request: Request) -> BaseModel:
        return await service.results(await body(request, ResultsIn))

    async def delete(request: Request) -> BaseModel:
        return await service.delete(await body(request, DeleteIn))

    async def wake_train(request: Request) -> BaseModel:
        return await service.wake_train(await body(request, WakeTrainIn))

    async def wake_status(request: Request) -> BaseModel:
        await body(request, _Empty)
        return await service.wake_status()

    async def wake_model(request: Request) -> BaseModel:
        return await service.wake_model(await body(request, WakeModelIn))

    async def job(request: Request) -> BaseModel:
        job_id = str(request.path_params.get("job_id", ""))
        if not JOB_ID_RE.fullmatch(job_id):
            raise KitRefused("not_found", "There is no such job on the laptop.")
        return await service.job(job_id)

    handlers: dict[tuple[str, str], Handler] = {
        ("GET", HEALTH): health,
        ("POST", STT): stt,
        ("POST", TTS): tts,
        ("POST", CLIP): clip,
        ("POST", SCORE): score,
        ("POST", RESULTS): results,
        ("POST", DELETE): delete,
        ("POST", WAKE_TRAIN): wake_train,
        ("POST", WAKE_STATUS): wake_status,
        ("POST", WAKE_MODEL): wake_model,
        ("GET", JOBS): job,
    }
    assert set(handlers) == set(ROUTES), "the server serves exactly protocol.ROUTES"
    routes = [
        Route(f"{API_PREFIX}{path}", endpoint(handlers[(method, path)]), methods=[method])
        for method, path in ROUTES
    ]

    @asynccontextmanager
    async def lifespan(app: Starlette):  # type: ignore[no-untyped-def]  # Starlette's shape
        yield
        await service.close()

    app = Starlette(routes=routes, lifespan=lifespan)

    async def not_found(request: Request, exc: Exception) -> Response:
        return _refusal("not_found", "The laptop speech kit has no such address.")

    app.add_exception_handler(404, not_found)
    app.add_exception_handler(405, not_found)
    return app


__all__ = ["STATUS", "build_app"]
