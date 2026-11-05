# src/jarvis/api/r4_wiring.py
"""R4 I1: vitals, self-health, Photos + connectors and people research + the no-AI switch on the
app (plan docs/plans/r4-vitals-health-people.md "Workstreams"; brief /home/claude/r4-i1-brief.md
W1-W16). Kept out of `api/app.py` so that file stays a short list of named steps, as R2's
`api/personal.py` and R3's `api/home_wiring.py` do.

- `wire_r4` (after R3's home, before the gateway): ONE `BrainMode` (W3) that `Brain`, the routes
  and `PeopleService` share; the Vitals service over billing + the Maps/YouTube ledger + the voice
  allowances (A); the health probes, only for the integrations that exist, the brain's FREE
  `router.health` record, never a completion (B, W4); the GitHub client (keyring), the owner's
  YouTube (Google link + ledger) and Photos (Google link + Faces + the home laptop) (C); people
  research (web search) (D). Each is gated on its settings flag AND its dependencies (W2): a
  missing dependency means OFF with one plain console line, never a crash at start.
- `register_r4_tools`: the tools, each through its module's factory, each only when its service
  exists; `systems_check` / `vitals_show` sit with the always-on tools so no-AI mode can route to
  them (W6). A training brain is offered no tools at all (`Brain._tools_on`), so the connector and
  people tools reach it no more than R3's did.
- `r4_tick_jobs`: `VitalsJob` (`vitals_poll`) and `HealthTickJob` (`health_check`) on the existing
  tick (D14, W5). No Cloud Scheduler job.
- `install_r4_routes`: `/v1/vitals`, `/v1/health` (through a proxy that finds the live service, so
  the router can be mounted before the lifespan builds it), `/v1/connectors`, `/v1/people` and
  `/v1/settings/brain-mode` (W7).
- `VitalsBrief`: the brief's Vitals section (W10), deterministic, never in the AI-summary input.
- `FacesAndPhotosPrivacy`: Faces "Delete all" also purges the Photos state (C's erasure hook).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, tzinfo
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from jarvis.api.auth import require_auth
from jarvis.api.identity import LEGACY_USER_ID, current_user, user_id_for_email
from jarvis.brief.models import VitalsSection
from jarvis.config import Settings
from jarvis.faces.privacy import FacesPrivacy
from jarvis.faces.service import FacesService
from jarvis.health import probes as P
from jarvis.health.models import HealthReport
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.integrations.github import GithubClient, GithubStore
from jarvis.integrations.youtube import YouTubeOwn
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.notify.ports import DirectNotifier, Notifier
from jarvis.offline.mode import BrainMode
from jarvis.people.research import PeopleService
from jarvis.photos.service import PhotosService
from jarvis.photos.tools import ConnectorDeps
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail
from jarvis.tools.registry import ToolRegistry
from jarvis.vitals.auto import AllowanceSpec
from jarvis.vitals.brief import vitals_lines
from jarvis.vitals.service import VitalsService
from jarvis.vitals.store import VitalsStore
from jarvis.voice.catalogue import TYPES, PriceList

log = get_logger(__name__)

R4_STATE = (
    "brain_mode",
    "vitals",
    "health",
    "github",
    "youtube_own",
    "photos",
    "connectors",
    "people",
    "r4_parts",
)
R4_JOB_NAMES = frozenset({"vitals_poll", "health_check"})
HEALTH_OFF = "The systems check is not available on this server."
VOICE_LABELS = {"chirp3-hd": "Voice (Chirp 3 HD)", "studio": "Voice (Studio)"}
VOICE_UNIT, STT_UNIT, STT_LABEL = "characters", "seconds", "Speech to text"


@dataclass(frozen=True)
class R4Parts:
    """What `tools/setup.build_gateway` gets: each None means that family is OFF."""

    settings: Settings
    vitals: VitalsService | None = None
    health: HealthService | None = None
    connectors: ConnectorDeps | None = None
    people: PeopleService | None = None


def _off(what: str, why: str) -> None:
    log.info("%s is OFF: %s", what, why)


def _notifier(app: FastAPI) -> Notifier:
    notify = getattr(app.state, "notify", None)
    return notify if notify is not None else DirectNotifier(app.state.alerts)


# ---- the no-AI switch (D) ------------------------------------------------------------------------


def wire_brain_mode(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> BrainMode:
    """The one persisted switch (W3): `Brain`, the routes and `PeopleService` share this object."""
    mode = BrainMode(s, docs, audit=audit, prefix=s.firestore_prefix)
    app.state.brain_mode = mode
    return mode


async def load_owner_modes(app: FastAPI, s: Settings) -> None:
    """I2 F1: read the persisted switch for every configured owner right after `wire_r4`, so the
    first tick or API call on a cold instance already sees it (until then the mode reads none)."""
    owners = [user_id_for_email(e) for e in s.owner_emails] or [LEGACY_USER_ID]
    for uid in owners:
        await app.state.brain_mode.load(uid)


# ---- vitals (A) ---------------------------------------------------------------------------------


def voice_allowances(s: Settings) -> tuple[AllowanceSpec, ...]:
    prices = PriceList.from_settings(s)
    specs = [
        AllowanceSpec(prices.tts(t).key, VOICE_LABELS[t], prices.tts(t).free_units, VOICE_UNIT)
        for t in TYPES
    ]
    specs.append(AllowanceSpec(prices.stt.key, STT_LABEL, prices.stt.free_units, STT_UNIT))
    return tuple(specs)


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
    )


# ---- self-health (B) ----------------------------------------------------------------------------


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
    if (tg := getattr(st, "telegram", None)) is not None:
        probes.append(P.telegram_probe(tg.client))
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
    )


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

    async def speak(self, uid: str) -> Any:
        return await self._svc().speak(uid)


# ---- photos + connectors (C) --------------------------------------------------------------------


def wire_github(s: Settings, docs: Docs) -> GithubClient | None:
    ring = Keyring.from_settings(s)
    if ring is None:
        _off("GitHub", "no encryption key on this server (the token is sealed in the keyring)")
        return None
    return GithubClient(GithubStore(docs, ring, prefix=s.firestore_prefix))


def wire_youtube_own(app: FastAPI) -> YouTubeOwn | None:
    google, media = getattr(app.state, "google", None), getattr(app.state, "media", None)
    if google is None or media is None:
        _off("The owner's YouTube", "needs the Google link and JARVIS's Google API key")
        return None
    return YouTubeOwn(google, media.ledger)


def wire_photos(app: FastAPI, s: Settings, docs: Docs) -> PhotosService | None:
    if not s.photos_enabled:
        _off("Photos", "JARVIS_PHOTOS_ENABLED=false")
        return None
    google = getattr(app.state, "google", None)
    faces: FacesService | None = getattr(app.state, "faces", None)
    home_client = getattr(app.state, "home_client", None)
    if google is None or faces is None or home_client is None:
        _off("Photos", "needs the Google link, Faces and the R3 home kit")
        return None
    from jarvis.contacts.client import ContactsClient
    from jarvis.photos.edge import BridgeHomeEdge
    from jarvis.photos.picker import PickerClient
    from jarvis.photos.service import PhotosState

    return PhotosService(
        PickerClient(google),
        BridgeHomeEdge(home_client),
        faces,
        ContactsClient(google),
        PhotosState(docs, prefix=s.firestore_prefix),
    )


class FacesAndPhotosPrivacy(FacesPrivacy):
    """Faces "Delete all" also ends the Picker session and drops every unnamed cluster id."""

    def __init__(self, service: FacesService | None, photos: PhotosService | None) -> None:
        super().__init__(service)
        self._photos = photos

    async def delete(self, uid: str) -> int:
        n = await super().delete(uid)
        if self._photos is not None:
            await self._photos.purge(uid)
        return n


# ---- people research (D) ------------------------------------------------------------------------


def wire_people(app: FastAPI, s: Settings, docs: Docs, mode: BrainMode) -> PeopleService | None:
    if not s.people_research_enabled:
        _off("People research", "JARVIS_PEOPLE_RESEARCH_ENABLED=false")
        return None
    web = getattr(app.state, "web", None)
    if web is None:
        _off("People research", "no web search key")
        return None
    from jarvis.people.cache import DossierCache
    from jarvis.people.model import BrainPeopleModel
    from jarvis.people.research import WebSearcher

    return PeopleService(
        WebSearcher(web),
        BrainPeopleModel(app.state.brains, app.state.billing),
        mode=mode.load,
        cache=DossierCache(docs, prefix=s.firestore_prefix),
    )


# ---- the whole of R4 ----------------------------------------------------------------------------


def _part(what: str, build: Callable[[], Any]) -> Any:
    """One part, or None: a part that fails to build is logged by class name (R3 review M9) and
    the rest of JARVIS keeps working."""
    try:
        return build()
    except Exception as exc:  # noqa: BLE001 - optional part: never fatal at start
        log.error("%s is OFF: its setup failed", what, extra={"error": type(exc).__name__})
        return None


async def wire_r4(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> None:
    """Everything R4 on `app.state` (None when off), before the gateway and the Brain."""
    st = app.state
    for name in R4_STATE:
        setattr(st, name, None)
    mode = wire_brain_mode(app, s, docs, audit)
    st.vitals = _part("Vitals", lambda: wire_vitals(app, s, docs))
    st.health = _part("The systems check", lambda: wire_health(app, s, docs, mode))
    st.github = _part("GitHub", lambda: wire_github(s, docs))
    st.youtube_own = _part("The owner's YouTube", lambda: wire_youtube_own(app))
    st.photos = _part("Photos", lambda: wire_photos(app, s, docs))
    st.connectors = ConnectorDeps(github=st.github, youtube=st.youtube_own, photos=st.photos)
    st.people = _part("People research", lambda: wire_people(app, s, docs, mode))
    st.r4_parts = R4Parts(
        settings=s, vitals=st.vitals, health=st.health, connectors=st.connectors, people=st.people
    )
    await load_owner_modes(app, s)  # I2 F1: the persisted no-AI switch, before any tick or call


def register_r4_tools(reg: ToolRegistry, parts: R4Parts | None) -> None:
    """W6: each family through its module's factory, only when its service exists."""
    if parts is None:
        return
    if parts.vitals is not None:
        from jarvis.vitals.tools import VitalsDeps, tools

        for t in tools(VitalsDeps(parts.vitals, parts.settings)):
            reg.register(t)
    if parts.health is not None:
        from jarvis.health.tools import health_tools

        for t in health_tools(parts.health):
            reg.register(t)
    if parts.connectors is not None:
        from jarvis.photos.tools import tools as connector_tools

        for t in connector_tools(parts.connectors):
            reg.register(t)
    if parts.people is not None:
        from jarvis.people.tools import PeopleDeps, people_tools

        for t in people_tools(PeopleDeps(service=parts.people)):
            reg.register(t)


def r4_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    """D14 / W5: the hourly vitals poll and the scheduled health check ride the existing tick."""
    st, s = app.state, app.state.settings
    jobs: list[TickJob] = []
    if getattr(st, "vitals", None) is not None:
        from jarvis.vitals.job import VitalsJob

        jobs.append(VitalsJob(st.vitals, _notifier(app), settings=s))
    if getattr(st, "health", None) is not None:
        from jarvis.health.tick import HealthTickJob

        jobs.append(HealthTickJob(st.health))
    assert {j.name for j in jobs} <= R4_JOB_NAMES  # the names the tick checks know
    return tuple(jobs)


def install_r4_routes(app: FastAPI) -> None:
    """W7: every R4 route, authed; the modules' own per-owner rate limiters stay."""
    from jarvis.health.api import health_router
    from jarvis.people.routes import install_people
    from jarvis.photos.api import install_connectors
    from jarvis.vitals.api import router as vitals_router

    app.include_router(vitals_router)
    app.include_router(
        health_router(
            LiveHealth(app),  # type: ignore[arg-type]  # the same three methods, found live
            user=current_user,
            dependencies=[Depends(require_auth)],
        )
    )
    install_connectors(app)  # after the app-wide validation handler (it wraps it)
    install_people(app)


# ---- the brief's Vitals section (W10) -----------------------------------------------------------


class VitalsBrief:
    """Red / amber lines and this month's AI spend, from `vitals.brief.vitals_lines`; None when
    there is nothing to say. Deterministic, never part of the AI-summary input."""

    def __init__(self, service: VitalsService) -> None:
        self._svc = service

    async def section(self, uid: str, tz: tzinfo, day: date) -> VitalsSection | None:
        lines = await vitals_lines(self._svc, uid)
        return VitalsSection(lines=tuple(lines)) if lines else None


def vitals_brief(app: FastAPI) -> VitalsBrief | None:
    svc = getattr(app.state, "vitals", None)
    return VitalsBrief(svc) if svc is not None else None


__all__ = [
    "R4_JOB_NAMES",
    "R4_STATE",
    "FacesAndPhotosPrivacy",
    "LiveHealth",
    "R4Parts",
    "VitalsBrief",
    "health_probes",
    "install_r4_routes",
    "load_owner_modes",
    "r4_tick_jobs",
    "register_r4_tools",
    "vitals_brief",
    "voice_allowances",
    "wire_r4",
]
