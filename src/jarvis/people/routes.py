# src/jarvis/people/routes.py
"""The People panel and the brain-mode switch over HTTP (R4 D10, D11, D7). Owner-only
(`require_auth` + `current_user`; cookie writes need `X-Requested-With: JARVIS`).

POST /v1/people/research   {name, context?} -> the dossier {name, context, profiles[{platform,url,
                           title}], findings[{title,domain,snippet}], summary|null, spoken,
                           ambiguous, no_ai, note, subject, cost_usd}; 422 out_of_scope (refusal:
                           private phrasing, or a subject that could not be verified as a
                           public figure / professional); 429 (the per-owner limit lives in
                           `PeopleService`, shared with the tool); 503
GET  /v1/people/last       {dossier: ... | null}   (session-only cache)
GET  /v1/settings/brain-mode   {mode: "ai"|"none", meaning}
POST /v1/settings/brain-mode   {mode} -> same; 422 for anything but ai / none

`install_people(app)` mounts them. The integrator sets `app.state.people` (a `PeopleService`, or
None). The client opens `profiles[].url` with `window.open(url, '_blank')`, one per URL.
The brain-mode switch is PERSISTED (`offline.mode.BrainMode`, the document
`<prefix>settings/<uid>`): `app.state.brain_mode` is the same object `Brain` reads, every flip
is audited, and only the owner (`current_user`) may flip it. `JARVIS_BRAIN_MODE` is the default
until the owner has chosen.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.offline.mode import BrainMode
from jarvis.people.guard import CONTEXT_MAX, NAME_MAX
from jarvis.people.models import Dossier
from jarvis.people.research import PeopleService, RateLimited, ScopeRefused, SearchFailed

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


def _brain_mode(request: Request) -> BrainMode:
    mode: BrainMode | None = getattr(request.app.state, "brain_mode", None)
    if mode is None:  # not wired by the app: the deployment setting, no persistence
        mode = BrainMode(request.app.state.settings)
        request.app.state.brain_mode = mode
    return mode


async def _mode_view(request: Request, uid: str) -> dict[str, str]:
    mode = await _brain_mode(request).load(uid)
    return {"mode": mode, "meaning": MEANING[mode]}


@router.post("/people/research", response_model=None)
async def research(body: ResearchBody, request: Request, uid: str = Depends(current_user)) -> Any:
    svc: PeopleService | None = getattr(request.app.state, "people", None)
    if svc is None:
        return _err(503, "unavailable", NOT_SET_UP)
    try:
        d = await svc.research(uid, body.name, body.context)
    except ScopeRefused as exc:
        return _err(422, "out_of_scope", exc.verdict.message)
    except RateLimited as exc:
        return _err(429, "rate_limited", str(exc))
    except SearchFailed as exc:
        return _err(503, "unavailable", str(exc))
    return _view(d)


@router.get("/people/last", response_model=None)
async def last(request: Request, uid: str = Depends(current_user)) -> Any:
    svc: PeopleService | None = getattr(request.app.state, "people", None)
    d = await svc.last(uid) if svc is not None else None
    return {"dossier": _view(d) if d is not None else None}


@router.get("/settings/brain-mode", response_model=None)
async def get_mode(request: Request, uid: str = Depends(current_user)) -> Any:
    return await _mode_view(request, uid)


@router.post("/settings/brain-mode", response_model=None)
async def set_mode(body: ModeBody, request: Request, uid: str = Depends(current_user)) -> Any:
    await _brain_mode(request).set(uid, body.mode, by=uid)
    return await _mode_view(request, uid)


def install_people(app: FastAPI) -> None:
    """Mount the routes on `app`."""
    app.include_router(router)


__all__ = ["install_people", "router"]
