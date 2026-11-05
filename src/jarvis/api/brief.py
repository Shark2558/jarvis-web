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
                            the tick holds the CPU on Cloud Run), unsent uploads (slice 10 E),
                            expired Recently deleted items, expired passkey challenges (≤ 100),
                            the once-a-day Tavily usage cross-check (slice 11), Telegram's seen
                            updates and counters, and Activity days past the window (R1); then
                            the feature jobs in `app.state.tick_jobs` (R2, `jarvis.ticks`)
"""

from __future__ import annotations

from collections.abc import Awaitable
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
from jarvis.logging import get_logger
from jarvis.ticks import run_jobs

log = get_logger(__name__)

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


SweepResult = Literal["ok", "failed"]


async def _sweep(what: str, job: Awaitable[object]) -> SweepResult:
    """A housekeeping sweep never fails the tick; a failure is an error in the log (with the
    traceback) and a "failed" in the tick answer, never the exception text."""
    try:
        await job
    except Exception:  # noqa: BLE001
        log.error("tick: %s sweep failed", what, exc_info=True)
        return "failed"
    return "ok"


@internal_router.post(
    TICK_PATH,
    response_model=TickResult,
    dependencies=[Depends(require_scheduler)],
    include_in_schema=False,
)
async def tick(request: Request, svc: BriefService = Depends(_svc)) -> TickResult:
    result = await svc.tick()
    state = request.app.state
    brain: Brain = state.brain
    sweeps: dict[str, SweepResult] = {}
    sweeps["memory"] = await _sweep("memory", brain.sweep_memory(svc.owners))  # bounded
    docs = getattr(state, "documents", None)
    if docs is not None:  # unsent uploads older than a day (slice 10 E): hourly
        sweeps["documents"] = await _sweep("documents", docs.sweep_waiting())
    undo = getattr(state, "undo", None)
    if undo is not None:  # Recently deleted past 30 days (slice 11; no billed TTL)
        sweeps["undo"] = await _sweep("undo", undo.sweep(svc.owners))
    marks = getattr(state, "outside_tasks", None)
    if marks is not None:  # unfinished outside-to-do marks past an hour (slice 11 D8)
        sweeps["outside_tasks"] = await _sweep("outside_tasks", marks.sweep(svc.owners))
    perms = getattr(state, "permissions", None)
    if perms is not None:  # passkey challenges never answered (slice 11 D7 c)
        sweeps["permissions"] = await _sweep("permissions", perms.sweep_challenges())
    tg = getattr(state, "telegram", None)
    if tg is not None:  # seen update ids / counters past their time
        sweeps["telegram"] = await _sweep("telegram", tg.store.sweep())
    act = getattr(state, "activity", None)
    if act is not None:  # Activity days past the 7-day window (R1 D7)
        sweeps["activity"] = await _sweep("activity", act.sweep(svc.owners))
    web = getattr(state, "web", None)
    if web is not None:  # Tavily's own count, at most once a day (slice 11 D7 b)
        sweeps["web"] = await _sweep("web", web.check_vendor_usage())
    # R2: feature jobs (vault reminders, the DigiLocker inbox); never raises, same ok/failed words
    jobs = await run_jobs(getattr(state, "tick_jobs", ()), svc.owners)
    sweeps.update({name: res for name, res in jobs.items() if name not in sweeps})
    return result.model_copy(update={"sweeps": sweeps})


__all__ = ["internal_router", "router"]
