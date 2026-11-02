# src/jarvis/api/brief.py
"""Morning brief HTTP surface (Layer 1 → 3). Owner-only: `require_auth` + `current_user` (the
user id is never taken from the client); writes need `X-Requested-With: JARVIS` when the caller
is a browser session (enforced by `require_auth`).

GET  /v1/brief/today        TodayView
POST /v1/brief/generate     {force?, trigger?} → TodayView; 429 past the daily limit
POST /v1/brief/seen         {date} → {ok, date, seen_at}; 404 when there is no such brief
GET  /v1/brief/settings     SettingsView
PUT  /v1/brief/settings     SettingsPatch → SettingsView; 422 without a confirm flag, with an
                            out-of-range time, or inbox delivery without the gmail.insert scope
POST /internal/brief/tick   Cloud Scheduler only (Google OIDC) → {checked, generated, delivered};
                            then a learning sweep for each owner (slice 8, ≤ 20 s, awaited:
                            the tick holds the CPU on Cloud Run), unsent uploads (slice 10 E)
                            and expired Recently deleted items (slice 11)
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, ConfigDict

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.scheduler_auth import TICK_PATH, require_scheduler
from jarvis.brief.models import SeenView, SettingsPatch, SettingsView, TickResult, TodayView
from jarvis.brief.service import BriefService
from jarvis.core.brain import Brain
from jarvis.core.guardrails import InputRejected

router = APIRouter(prefix="/v1/brief", dependencies=[Depends(require_auth)])
internal_router = APIRouter()


class GenerateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    force: bool = False
    trigger: Literal["manual", "open"] | None = None  # default: manual if force, else open


class SeenRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    date: str


def _svc(request: Request) -> BriefService:
    return request.app.state.brief  # type: ignore[no-any-return]


@router.get("/today", response_model=TodayView)
async def today(svc: BriefService = Depends(_svc), uid: str = Depends(current_user)) -> TodayView:
    return await svc.today(uid)


@router.post("/generate", response_model=TodayView)
async def generate(
    req: GenerateRequest | None = Body(default=None),
    svc: BriefService = Depends(_svc),
    uid: str = Depends(current_user),
) -> TodayView:
    r = req or GenerateRequest()
    trigger = r.trigger or ("manual" if r.force else "open")
    return await svc.generate(uid, trigger=trigger, force=r.force)


@router.post("/seen", response_model=SeenView)
async def seen(
    req: SeenRequest, svc: BriefService = Depends(_svc), uid: str = Depends(current_user)
) -> SeenView:
    try:
        day = date.fromisoformat(req.date)
    except ValueError:
        raise InputRejected("date must look like YYYY-MM-DD") from None
    if day.isoformat() != req.date:
        raise InputRejected("date must look like YYYY-MM-DD")
    at = await svc.mark_seen(uid, req.date)
    if at is None:
        raise LookupError("There is no brief for that day.")
    return SeenView(ok=True, date=req.date, seen_at=at)


@router.get("/settings", response_model=SettingsView)
async def get_settings(
    svc: BriefService = Depends(_svc), uid: str = Depends(current_user)
) -> SettingsView:
    return await svc.get_settings(uid)


@router.put("/settings", response_model=SettingsView)
async def put_settings(
    patch: SettingsPatch, svc: BriefService = Depends(_svc), uid: str = Depends(current_user)
) -> SettingsView:
    return await svc.update_settings(uid, patch)


@internal_router.post(
    TICK_PATH,
    response_model=TickResult,
    dependencies=[Depends(require_scheduler)],
    include_in_schema=False,
)
async def tick(request: Request, svc: BriefService = Depends(_svc)) -> TickResult:
    result = await svc.tick()
    brain: Brain = request.app.state.brain
    await brain.sweep_memory(svc.owners)  # bounded, never raises
    docs = getattr(request.app.state, "documents", None)
    if docs is not None:  # unsent uploads older than a day (slice 10 E): hourly, never raises
        await docs.sweep_waiting()
    undo = getattr(request.app.state, "undo", None)
    if undo is not None:  # Recently deleted past 30 days (slice 11; no billed TTL): never raises
        await undo.sweep(svc.owners)
    return result


__all__ = ["internal_router", "router"]
