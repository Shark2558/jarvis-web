# src/jarvis/api/offline.py
"""Offline mode settings (R1 D10-D12; Layer 1 -> 4). Owner-only: `require_auth` + `current_user`
(cookie writes need `X-Requested-With: JARVIS`, enforced by `require_auth`); changes are
rate-limited.
GET    /v1/offline       {available, configured, enabled, host, model, state, last_ok_at,
                         last_used_at}; state: off | standby | active | unreachable | refused.
                         `available`
                         false: this server has no token key, so the feature is off (nothing else
                         is returned). The key and the full address are never sent back, only
                         the host name.
PUT    /v1/offline       {url?, key?, model?, enabled?} -> the same view. The first save needs url,
                         key and model; a new url needs the key again. 422 {error, detail}:
                         invalid_url / invalid_key / invalid_model / missing, in plain words.
DELETE /v1/offline       forget the laptop -> the same view.
POST   /v1/offline/test  {ok, models, detail}: GET <url>/models with the key, 5 s at most.

404 {error: "offline_off"} on writes when the feature is not available. A change is one audit entry
(agent "offline", outcome "changed", a hash of the field names only; never the address or the key).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.logging import get_logger
from jarvis.offline.service import LocalFallback, OfflineRejected

log = get_logger(__name__)

CHANGES_PER_MINUTE = 20
TESTS_PER_MINUTE = 6
router = APIRouter(prefix="/v1/offline", dependencies=[Depends(require_auth)])

NOT_AVAILABLE_VIEW: dict[str, Any] = {
    "available": False,
    "configured": False,
    "enabled": False,
    "host": None,
    "model": None,
    "state": "off",
    "last_ok_at": None,
    "last_used_at": None,
}


class OfflineBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str | None = Field(default=None, max_length=300)
    key: SecretStr | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=100)
    enabled: StrictBool | None = None


class OfflineOff(Exception):
    pass


def _svc(request: Request) -> LocalFallback | None:
    return getattr(request.app.state, "offline", None)


def _need(svc: LocalFallback | None) -> LocalFallback:
    if svc is None:
        raise OfflineOff()
    return svc


def _limit(request: Request, uid: str, which: str) -> None:
    limiter: RateLimiter = getattr(request.app.state, which)
    if not limiter.allow(uid)[0]:
        raise OfflineRejected("rate_limited", "Too many changes; wait a moment.", status=429)


@router.get("")
async def offline_view(svc: LocalFallback | None = Depends(_svc)) -> dict[str, Any]:
    return await svc.status() if svc is not None else dict(NOT_AVAILABLE_VIEW)


@router.put("")
async def offline_change(
    body: OfflineBody,
    request: Request,
    svc: LocalFallback | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    service = _need(svc)
    _limit(request, uid, "offline_limit")
    view = await service.configure(
        uid,
        url=body.url,
        key=body.key.get_secret_value() if body.key is not None else None,
        model=body.model,
        enabled=body.enabled,
    )
    fields = sorted(k for k, v in body.model_dump().items() if v is not None)
    log.info("offline mode changed", extra={"fields": fields, "state": view["state"]})
    await record_change(
        request,
        agent="offline",
        tool="offline_config",
        args={"fields": ",".join(fields)},
        detail=view["state"],
    )
    return view


@router.delete("")
async def offline_clear(
    request: Request,
    svc: LocalFallback | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    service = _need(svc)
    _limit(request, uid, "offline_limit")
    view = await service.clear(uid)
    await record_change(
        request, agent="offline", tool="offline_config", args={"fields": "cleared"}, detail="off"
    )
    return view


@router.post("/test")
async def offline_test(
    request: Request,
    svc: LocalFallback | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    service = _need(svc)
    _limit(request, uid, "offline_test_limit")
    return await service.test()


def _err(status: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "detail": detail})


def install_offline(app: FastAPI) -> None:
    """Mount /v1/offline, its per-owner limits and its error mapping on `app`. The service itself
    is `app.state.offline` (None: the feature is off on this server)."""
    app.state.offline_limit = RateLimiter(CHANGES_PER_MINUTE)
    app.state.offline_test_limit = RateLimiter(TESTS_PER_MINUTE)
    if not hasattr(app.state, "offline"):
        app.state.offline = None

    @app.exception_handler(OfflineRejected)
    async def _rejected(_: Request, exc: OfflineRejected) -> JSONResponse:
        return _err(exc.status, exc.code, exc.detail)

    @app.exception_handler(OfflineOff)
    async def _off(_: Request, exc: OfflineOff) -> JSONResponse:
        return _err(
            404,
            "offline_off",
            "Offline mode needs the server's token key (JARVIS_TOKEN_KEY), which isn't set.",
        )

    app.include_router(router)


__all__ = ["CHANGES_PER_MINUTE", "install_offline", "router"]
