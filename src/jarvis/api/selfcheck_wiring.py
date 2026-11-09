# src/jarvis/api/selfcheck_wiring.py
"""Vitals and the systems check on the app (R4 I1 parts A and B, moved out of `api/r4_wiring.py`
at R5.1 I1 so that file stays a short list of named steps). Behaviour unchanged from R4, plus the
R5.1 wiring (`docs/plans/r5-1-observations.md`):

- `vitals_sources` (D2): what Vitals reads to track JARVIS's own keys and connections -- the
  routers' own record of their last call (no model call), the Google link, the LAST stored
  systems-check report, the web vendor's free usage report, the GitHub token's facts and the
  home link. `wire_vitals` therefore runs AFTER the health service and the GitHub client.
- `health_probes` (D4): Telegram is checked only for an owner with a paired chat ("not set up"
  otherwise, never "the check failed").
- `wire_health` (D5): the briefing reads the Vitals board. Vitals reads the health service (its
  last report) and the health service reads Vitals (the board), so the health service gets a
  live reader (`LiveVitals`) that finds the Vitals service when the briefing runs.
- `LiveHealth` (D7, D5): the streamed check and the briefing. `check_stream` stays a plain method
  returning the iterator: `HealthService.check_stream` raises `CheckBusy` synchronously and the
  route turns that into a 429.
- `shared_health_job` (D4): ONE `HealthTickJob` for the tick AND the 5-minute home watchdog, so its
  per-owner 15-minute gate is shared and an owner is never checked twice.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException

from jarvis.config import Settings
from jarvis.health import probes as P
from jarvis.health.briefing import Briefing
from jarvis.health.models import HealthReport
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.health.tick import HealthTickJob
from jarvis.logging import get_logger
from jarvis.notify.ports import DirectNotifier, Notifier
from jarvis.offline.mode import BrainMode
from jarvis.storage.docs import Docs
from jarvis.vitals.auto import AllowanceSpec
from jarvis.vitals.models import Board
from jarvis.vitals.own import BrainReader, OwnSources
from jarvis.vitals.service import VitalsService
from jarvis.vitals.store import VitalsStore
from jarvis.voice.catalogue import TYPES, PriceList

log = get_logger(__name__)

HEALTH_OFF = "The systems check is not available on this server."
VOICE_LABELS = {"chirp3-hd": "Voice (Chirp 3 HD)", "studio": "Voice (Studio)"}
VOICE_UNIT, STT_UNIT, STT_LABEL = "characters", "seconds", "Speech to text"


def _off(what: str, why: str) -> None:
    log.info("%s is OFF: %s", what, why)


def _notifier(app: FastAPI) -> Notifier:
    notify = getattr(app.state, "notify", None)
    return notify if notify is not None else DirectNotifier(app.state.alerts)


# ---- vitals (R4 A; R5.1 B: JARVIS's own keys and connections) -----------------------------------


def voice_allowances(s: Settings) -> tuple[AllowanceSpec, ...]:
    prices = PriceList.from_settings(s)
    specs = [
        AllowanceSpec(prices.tts(t).key, VOICE_LABELS[t], prices.tts(t).free_units, VOICE_UNIT)
        for t in TYPES
    ]
    specs.append(AllowanceSpec(prices.stt.key, STT_LABEL, prices.stt.free_units, STT_UNIT))
    return tuple(specs)


def vitals_sources(app: FastAPI) -> OwnSources:
    """R5.1 D2: what Vitals reads to track JARVIS's own keys and connections (all free)."""
    st = app.state
    brains = st.brains
    have = {b.id for b in brains.list()}

    def health_of(brain_id: str) -> BrainReader | None:  # the router's record: no model call
        if brain_id not in have:
            return None
        read: BrainReader = brains.router_for(brain_id).health
        return read

    web = getattr(st, "web", None)
    usage = web.provider if web is not None and hasattr(web.provider, "usage") else None
    return OwnSources(
        claude=health_of("anthropic"),
        gemini=health_of("gemini"),
        google=getattr(st, "google", None),  # GoogleConnector.status(uid)
        health=getattr(st, "health", None),  # HealthService.last(uid): the LAST stored report
        web=usage,  # TavilyProvider.usage(): the vendor's free usage report
        github=getattr(st, "github", None),  # GithubClient.status / .token_meta
        home=getattr(st, "home_store", None),  # HomeStore.status(uid)
        default_brain=brains.default.id,  # the brain the systems check's probe watches
    )


def wire_vitals(app: FastAPI, s: Settings, docs: Docs) -> VitalsService | None:
    if not s.vitals_enabled:
        _off("Vitals", "JARVIS_VITALS_ENABLED=false")
        return None
    media = getattr(app.state, "media", None)
    return VitalsService(
        VitalsStore(docs, prefix=s.firestore_prefix),
        s,
        billing=app.state.billing,
        ledger=media.ledger if media is not None else None,
        allowances=voice_allowances(s),
        own=vitals_sources(app),
    )


class LiveVitals:
    """The briefing's Vitals reader (R5.1 D5), found live: Vitals is built after the health
    service (it reads the last report), so the service gets this stand-in. A Vitals that is
    switched on but failed to build answers as unreadable ("Vitals can't be read just now")."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def board(self, uid: str) -> Board:
        svc: VitalsService | None = getattr(self._app.state, "vitals", None)
        if svc is None:
            raise LookupError("vitals is not available")
        return await svc.board_cached(uid)  # int-sec M2: a 15 s old board is fine for a briefing


# ---- the systems check (R4 B; R5.1 C) -----------------------------------------------------------


def health_probes(app: FastAPI, s: Settings, docs: Docs, mode: BrainMode) -> list[P.Probe]:
    """Per `health/INTEGRATION.md` §1: the brain's FREE record (never a completion), the document
    store, then each integration only when it exists (W4)."""
    st = app.state
    router = st.brains.router_for(st.brains.default.id)
    probes = [
        P.brain_probe(router.health, mode.load),
        P.docs_probe(docs, prefix=s.firestore_prefix),
    ]
    if s.session_backend.value == "redis":
        from jarvis.health.redis_ping import redis_pinger

        probes.append(P.redis_probe(redis_pinger(s.redis_url)))
    if getattr(st, "google", None) is not None:
        probes.append(P.google_probe(st.google))
    if (tg := getattr(st, "telegram", None)) is not None:  # no bot token -> no probe at all

        async def paired(uid: str) -> bool:  # R5.1 D4: a paired chat for THIS owner
            return await tg.store.get(uid) is not None

        probes.append(P.telegram_probe(tg.client, configured=paired))
    if (home := getattr(st, "home_store", None)) is not None:
        probes.append(P.home_probe(home, clock=time.time, offline_after_s=s.home_offline_after_s))
    web = getattr(st, "web", None)
    if web is not None and hasattr(web.provider, "usage"):
        probes.append(P.web_probe(web.provider))
    return probes


def wire_health(app: FastAPI, s: Settings, docs: Docs, mode: BrainMode) -> HealthService | None:
    if not s.health_enabled:
        _off("The systems check", "JARVIS_HEALTH_ENABLED=false")
        return None
    return HealthService(
        health_probes(app, s, docs, mode),
        HealthStore(docs, prefix=s.firestore_prefix),
        notifier=_notifier(app),
        voice=getattr(app.state, "voice", None),
        vitals=LiveVitals(app) if s.vitals_enabled else None,  # R5.1 D5: the briefing's board
    )


def shared_health_job(app: FastAPI) -> HealthTickJob | None:
    """R5.1 D4: the ONE systems-check job, built once and shared by the tick and the 5-minute home
    watchdog (its per-owner 15-minute gate lives on the instance). Safe to call more than once:
    `Watchdog.extend` refuses a name it already runs, so the job is added only when built."""
    st = app.state
    if getattr(st, "health", None) is None:
        return None
    job: HealthTickJob | None = getattr(st, "health_job", None)
    if job is None:
        job = st.health_job = HealthTickJob(st.health)
        if getattr(st, "home_watchdog", None) is not None:
            st.home_watchdog.extend(job)  # around the clock, every 5 minutes
    return job


class LiveHealth:
    """`health_router` takes a service at mount time, but the service is built in the lifespan:
    this stands in and answers 503 while it does not exist."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    def _svc(self) -> HealthService:
        svc: HealthService | None = getattr(self._app.state, "health", None)
        if svc is None:
            raise HTTPException(503, {"error": "not_available", "detail": HEALTH_OFF})
        return svc

    async def last(self, uid: str) -> HealthReport | None:
        return await self._svc().last(uid)

    async def check(self, uid: str, *, force: bool = False) -> HealthReport:
        return await self._svc().check(uid, force=force)

    async def speak(self, uid: str) -> Any | None:
        return await self._svc().speak(uid)

    async def briefing(self, uid: str, report: HealthReport | None) -> Briefing:
        return await self._svc().briefing(uid, report)

    def check_stream(self, uid: str, *, force: bool = False) -> AsyncIterator[dict[str, Any]]:
        """A plain method (not `async def`): `CheckBusy` must surface when the route calls it."""
        return self._svc().check_stream(uid, force=force)  # 503 before the service exists


__all__ = [
    "HEALTH_OFF",
    "LiveHealth",
    "LiveVitals",
    "health_probes",
    "shared_health_job",
    "vitals_sources",
    "voice_allowances",
    "wire_health",
    "wire_vitals",
]
