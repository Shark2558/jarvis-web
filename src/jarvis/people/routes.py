# src/jarvis/people/routes.py
"""The People panel and the brain-mode switch over HTTP (R4 D10, D11, D7). Owner-only
(`require_auth` + `current_user`; cookie writes need `X-Requested-With: JARVIS`).

POST /v1/people/research   {name, context?} -> the dossier {name, context, profiles[{platform,url,
                           title}], findings[{title,domain,snippet}], summary|null, spoken,
                           ambiguous, no_ai, note}; 422 out_of_scope (plain message); 503
GET  /v1/people/last       {dossier: ... | null}   (session-only cache)
GET  /v1/settings/brain-mode   {mode: "ai"|"none", meaning}
POST /v1/settings/brain-mode   {mode} -> same; 422 for anything but ai / none

`install_people(app)` mounts them. The integrator sets `app.state.people` (a `PeopleService`, or
None). The client opens `profiles[].url` with `window.open(url, '_blank')`, one per URL.
The brain-mode switch changes the running process's setting (it is the one `Brain` reads); set
`JARVIS_BRAIN_MODE` to make it the start-up default.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.config import Settings
from jarvis.people.guard import CONTEXT_MAX, NAME_MAX
from jarvis.people.research import Dossier, PeopleService, ScopeRefused, SearchFailed

RESEARCH_PER_MINUTE = 6
NOT_SET_UP = "People research is not set up on this server."
MEANING = {
    "ai": "AI on: JARVIS reasons and writes with the model.",
    "none": "No-AI: JARVIS answers only from fixed rules; anything that needs the AI says so.",
}

router = APIRouter(prefix="/v1", dependencies=[Depends(require_auth)])


class ResearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=NAME_MAX * 4)
    context: str | None = Field(default=None, max_length=CONTEXT_MAX * 4)


class ModeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["ai", "none"]


def _err(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


def _view(d: Dossier) -> dict[str, Any]:
    return asdict(d)


def _mode(request: Request) -> dict[str, str]:
    mode = request.app.state.settings.brain_mode
    return {"mode": mode, "meaning": MEANING[mode]}


@router.post("/people/research", response_model=None)
async def research(body: ResearchBody, request: Request, uid: str = Depends(current_user)) -> Any:
    svc: PeopleService | None = getattr(request.app.state, "people", None)
    if svc is None:
        return _err(503, "unavailable", NOT_SET_UP)
    allowed, _ = request.app.state.people_limit.allow(uid)
    if not allowed:
        return _err(429, "rate_limited", "Too many lookups; wait a moment, Sir.")
    settings: Settings = request.app.state.settings
    try:
        d = await svc.research(
            uid, body.name, body.context, use_brain=settings.brain_mode != "none"
        )
    except ScopeRefused as exc:
        return _err(422, "out_of_scope", exc.verdict.message)
    except SearchFailed as exc:
        return _err(503, "unavailable", str(exc))
    return _view(d)


@router.get("/people/last", response_model=None)
async def last(request: Request, uid: str = Depends(current_user)) -> Any:
    svc: PeopleService | None = getattr(request.app.state, "people", None)
    d = svc.last(uid) if svc is not None else None
    return {"dossier": _view(d) if d is not None else None}


@router.get("/settings/brain-mode", response_model=None)
async def get_mode(request: Request) -> Any:
    return _mode(request)


@router.post("/settings/brain-mode", response_model=None)
async def set_mode(body: ModeBody, request: Request) -> Any:
    request.app.state.settings.brain_mode = body.mode
    return _mode(request)


def install_people(app: FastAPI) -> None:
    """Mount the routes and the per-owner research limit on `app`."""
    app.state.people_limit = RateLimiter(RESEARCH_PER_MINUTE)
    app.include_router(router)


__all__ = ["RESEARCH_PER_MINUTE", "install_people", "router"]
