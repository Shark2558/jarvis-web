# src/jarvis/api/app.py
"""FastAPI application factory (Layer 1 surface: web/desktop clients hit this).

Build with `create_app()` so tests can inject a mock provider and an in-memory store. It is a
short list of named steps (slice 12 final review): the lifespan wires the core (`_wire_core`),
the slice 10–11 features, the slice 12 ones (`_wire_slice12`: Maps + YouTube, Drive), R2's
personal data (`api/personal.py`: vault, notes, things, DigiLocker inbox), R3's home, camera and
faces (`api/home_wiring.py`; its one alert policy is wired in the core, before anything takes the
alert sink), R4's vitals, self-health, connectors, people research and the one no-AI switch
(`api/r4_wiring.py`), the gateway with the owner's rules and the Brain, then the privacy dashboard
and tick jobs; then the middleware, the error mapping and the routers.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from jarvis.activity.service import ActivityService
from jarvis.activity.store import ActivityStore
from jarvis.alerts import AlertSink
from jarvis.api.activity import install_activity
from jarvis.api.auth import CSRFRejected, auth_router, build_oauth
from jarvis.api.belongings import install_belongings
from jarvis.api.body import MAX_BODY_BYTES, BodySizeLimit, BodyTooLarge, too_large_body
from jarvis.api.brief import internal_router as brief_internal_router
from jarvis.api.brief import router as brief_router
from jarvis.api.camera import install_camera
from jarvis.api.console import router as console_router
from jarvis.api.deleted import router as deleted_router
from jarvis.api.documents import ATTACH_BODY_BYTES, ATTACH_PATH, install_documents
from jarvis.api.drive import install_drive
from jarvis.api.faces import install_faces
from jarvis.api.family import install_family
from jarvis.api.home import install_home
from jarvis.api.home_wiring import check_job_names, notify_tick_jobs, wire_home, wire_notify
from jarvis.api.identity import LEGACY_USER_ID, adopt_legacy_sessions, user_id_for_email
from jarvis.api.integrations import router as integrations_router
from jarvis.api.media import router as media_router
from jarvis.api.memory import router as memory_router
from jarvis.api.notes import install_notes
from jarvis.api.notify import install_notify
from jarvis.api.offline import install_offline
from jarvis.api.permissions import build_permissions, install_permissions
from jarvis.api.personal import personal_tick_jobs, wire_personal, wire_privacy
from jarvis.api.privacy import install_privacy
from jarvis.api.r4_wiring import install_r4_routes, r4_tick_jobs, vitals_brief, wire_r4
from jarvis.api.ratelimit import RateLimiter, make_middleware
from jarvis.api.routes import conflict_body
from jarvis.api.routes import router as v1_router
from jarvis.api.scheduler_auth import GoogleOIDCVerifier, SchedulerUnauthorized
from jarvis.api.telegram import build_telegram, install_telegram
from jarvis.api.usage import router as usage_router
from jarvis.api.vault import VAULT_BODY_BYTES, VAULT_UPLOAD_PATH, install_vault
from jarvis.api.vault_inbox import install_vault_inbox
from jarvis.api.voice import install_voice
from jarvis.api.web import router as web_router
from jarvis.billing import (
    Billing,
    BudgetReached,
    BudgetRejected,
    BudgetUnavailable,
    build_billing,
    fx_client,
)
from jarvis.brief.deliveries import DeliveriesBrief
from jarvis.brief.family_day import FamilyBrief
from jarvis.brief.home_overnight import HomeOvernightBrief
from jarvis.brief.service import BriefLimitReached, BriefService, SettingsRejected
from jarvis.brief.store import BriefStore
from jarvis.brief.vault_due import VaultDueBrief
from jarvis.config import AuthMode, SessionBackend, Settings, get_settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ApprovalStore, InputRejected
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.drive.service import DriveService, build_drive_service
from jarvis.home.ports import MAX_WEBHOOK_BYTES, WEBHOOK_PATH
from jarvis.integrations.google import (
    build_google_connector,
    google_tools_configured,
    google_tools_startup_note,
    register_tools_oauth,
)
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.base import LLMAuthError, LLMError, LLMOutOfCredit, LLMProvider, LLMTransientError
from jarvis.llm.brains import BrainRegistry
from jarvis.llm.fallback import FallbackFailed
from jarvis.llm.router import NO_AI_REFUSAL, BrainOff
from jarvis.logging import configure_logging, get_logger, new_trace_id, set_trace_id
from jarvis.media.service import build_media
from jarvis.memory import SessionConflict, SessionNotFound, SessionStore
from jarvis.offline.rules import wrap_offline
from jarvis.offline.service import build_local_fallback
from jarvis.packages.tools import PackageScanner
from jarvis.recall.errors import (
    ConsentRequired,
    ImportTooLarge,
    InvalidMemoryInput,
    MemoryFull,
    MemoryUnavailable,
    SensitiveRejected,
)
from jarvis.recall.service import MemoryService, build_memory_service
from jarvis.storage import Storage, build_storage
from jarvis.storage.docs import Docs, MemoryDocs
from jarvis.telegram.alerts import ALERT_TEXT
from jarvis.telegram.rules import wrap_rules
from jarvis.tools.audit import AuditLog, AuditTrail
from jarvis.tools.gateway import Gateway
from jarvis.tools.r1_tools import build_family_service
from jarvis.tools.setup import attach_activity, build_gateway
from jarvis.tools.task_marks import OutsideTasks
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.voice.service import VoiceEngines, build_voice_service
from jarvis.web.service import build_web_service

log = get_logger(__name__)


def _err(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body)


def app_docs(built: Storage | None) -> Docs:
    """The document store the brief and billing share: Firestore when configured, else
    in-process documents (dev, tests)."""
    return built.docs if built is not None and built.docs is not None else MemoryDocs()


def build_undo(s: Settings, built: Storage | None, docs: Docs) -> UndoBin | None:
    """Recently deleted (slice 11) only on persistent storage: a copy kept in process memory
    would vanish on a restart, so "Undo for 30 days" would not hold. Without it every delete
    stays R3 (card + passkey) and /v1/deleted says it isn't available."""
    if built is None or not built.persistent:
        return None
    return UndoBin(DeletedStore(docs, prefix=s.firestore_prefix))


def build_brief_service(
    app: FastAPI, s: Settings, built: Storage | None, *, docs: Docs | None = None
) -> BriefService:
    """Same storage, Google link, brains, approvals, audit chain and billing (the monthly limit
    and meter) as the rest of the app."""
    gw: Gateway | None = app.state.gateway
    docs = docs if docs is not None else app_docs(built)
    approvals: ApprovalStore | None
    audit: AuditTrail
    if gw is not None:
        approvals, audit = gw.gate.store, gw.audit
    else:
        approvals = built.approvals if built is not None else None
        audit = built.audit if built is not None else AuditLog()
    return BriefService(
        store=BriefStore(docs, prefix=s.firestore_prefix),
        google=app.state.google,
        brains=app.state.brains,
        approvals=approvals,
        audit=audit,
        owners=[user_id_for_email(e) for e in s.owner_emails] or [LEGACY_USER_ID],
        default_tz=s.user_timezone,
        ai_daily_cap=s.brief_ai_daily_cap,
        retention_days=s.brief_retention_days,
        billing=getattr(app.state, "billing", None),
        # R1 D: Deliveries and Family today (only with the Google link they read through)
        deliveries=DeliveriesBrief(PackageScanner(app.state.google))
        if getattr(app.state, "google", None) is not None
        else None,
        family_day=FamilyBrief(family) if (family := getattr(app.state, "family", None)) else None,
        # R2 D5: the Documents section (deterministic, never in the AI input)
        vault_due=VaultDueBrief(vault) if (vault := getattr(app.state, "vault", None)) else None,
        # R3 B: Home overnight (held alerts, parcels, visitors; counts and times)
        home_overnight=HomeOvernightBrief(cam.feed, cam.config)
        if (cam := getattr(app.state, "camera", None))
        else None,
        vitals=vitals_brief(app),  # R4 I1 W10: red / amber lines + AI spend; never in the AI input
    )


def build_app_memory(
    s: Settings, docs: Docs, brains: BrainRegistry, billing: Billing, audit: AuditTrail
) -> MemoryService | None:
    """Long-term memory on the same documents, billing gate and audit chain (None when off)."""
    if not s.memory_enabled:
        return None
    return build_memory_service(
        docs=docs,
        brains=brains,
        billing=billing,
        audit=audit,
        prefix=s.firestore_prefix,
        tz=s.user_timezone,
        max_runs=s.memory_learn_daily_cap,
    )


DRAIN_TIMEOUT_S = 5.0
HOME_LINK_PATH = "/home/link"
HOME_LINK_BYTES = 4096
SERVICE_ACCOUNT_SUFFIX = ".iam.gserviceaccount.com"


def _mount_scheduler(app: FastAPI, s: Settings, verifier: GoogleOIDCVerifier | None) -> None:
    """POST /internal/brief/tick exists only when a scheduler service account is configured,
    the public URL (the token's audience) is known, and the brief store is persistent: the
    at-most-once generation claim and inbox mark live there, so with in-process storage two
    instances (or a restart) could each put a brief in the inbox."""
    if not s.brief_scheduler_sa:
        return
    if not s.public_base_url:
        log.warning(
            "JARVIS_BRIEF_SCHEDULER_SA is set without JARVIS_PUBLIC_BASE_URL: no tick route"
        )
        return
    if s.session_backend is not SessionBackend.FIRESTORE:
        log.error(
            "JARVIS_BRIEF_SCHEDULER_SA is set but storage is not persistent "
            "(JARVIS_SESSION_BACKEND=firestore is required): no tick route"
        )
        return
    if not s.brief_scheduler_sa.endswith(SERVICE_ACCOUNT_SUFFIX):
        log.warning(
            "JARVIS_BRIEF_SCHEDULER_SA does not end with .iam.gserviceaccount.com: Cloud "
            "Scheduler signs as a service account; check the value"
        )
    app.state.scheduler_verifier = verifier or GoogleOIDCVerifier(
        base_url=s.public_base_url, email=s.brief_scheduler_sa
    )  # R3 I0: one exact audience per scheduler route (the tick; the home watchdog at I1)
    app.include_router(brief_internal_router)


def friendly_llm_error(exc: LLMError) -> str:
    """Owner-facing wording. Raw vendor error bodies never reach the browser."""
    if isinstance(exc, BrainOff):  # R4 D7: the owner switched the AI off; say exactly that
        return NO_AI_REFUSAL
    if isinstance(exc, FallbackFailed):  # R1 C: the laptop's own plain-words message
        return str(exc)
    low = str(exc).lower()
    if isinstance(exc, LLMOutOfCredit) or any(
        w in low for w in ("credit balance", "billing", "quota")
    ):
        return "The AI provider account has no credit or quota left. Add credit, or switch brain."
    if isinstance(exc, LLMTransientError):
        return "The AI service is busy or rate-limited right now. Please try again in a minute."
    if "blocked" in low:
        return "The AI provider declined to answer that message."
    return "The AI service could not answer. Please try again."


@dataclass(frozen=True)
class _Injected:
    """What a test (or another host) hands `create_app` instead of having it built."""

    provider: LLMProvider | None = None
    store: SessionStore | None = None
    gateway: Gateway | None = None
    brains: BrainRegistry | None = None
    billing: Billing | None = None
    voice_engines: VoiceEngines | None = None
    undo: UndoBin | None = None
    drive: DriveService | None = None


def _wire_core(
    app: FastAPI, s: Settings, inj: _Injected, built: Storage | None
) -> tuple[Docs, AuditTrail]:
    """Sessions, brains, the Google link, billing, memory and voice; returns the shared document
    store and audit chain the rest is built on."""
    app.state.settings = s
    app.state.store = inj.store or (built.sessions if built else None)
    docs = app_docs(built)
    # Offline mode (R1 C) needs the alert sink, which needs Telegram: build those first (no
    # network here), then the brains that share the local fallback
    audit: AuditTrail = (
        inj.gateway.audit if inj.gateway is not None else built.audit if built else AuditLog()
    )
    app.state.telegram = build_telegram(s, docs, audit=audit)
    # R3 D10: every alert goes through the one policy (quiet hours, storm control, Telegram and
    # browser notifications); without the token key, R1's Telegram alerts as before
    alerts: AlertSink = wire_notify(app, s, docs, audit)
    app.state.alerts = alerts
    app.state.offline = build_local_fallback(s, docs, alerts)  # None without JARVIS_TOKEN_KEY
    app.state.brains = inj.brains or BrainRegistry.from_settings(
        s, inj.provider, local=app.state.offline
    )
    app.state.router = app.state.brains.router_for(app.state.brains.default.id)
    tokens = built.tokens if built else MemoryTokenStore()
    app.state.google = build_google_connector(s, tokens)
    # Family calendars (R1 D): None without the Google link
    app.state.family = (
        build_family_service(app.state.google, docs, s) if app.state.google is not None else None
    )
    app.state.fx_http = fx_client(s)
    app.state.billing = inj.billing or build_billing(
        s, docs, app.state.brains, http=app.state.fx_http
    )
    app.state.memory = build_app_memory(s, docs, app.state.brains, app.state.billing, audit)
    # Voice (slice 9): settings + wit level always; Google speech only when switched on.
    # No network at start-up: credentials are looked up on first use.
    app.state.voice = build_voice_service(s, docs, app.state.billing, engines=inj.voice_engines)
    return docs, audit


def _wire_features(
    app: FastAPI, s: Settings, inj: _Injected, built: Storage | None, docs: Docs
) -> None:
    """Slices 10–11 on the same documents: web search, attached files, Recently deleted and the
    to-dos JARVIS wrote from outside content."""
    app.state.web = build_web_service(s, docs)  # slice 10 B: None without a Tavily key
    # Attached files (slice 10 E): text and chunks on the same documents, deleted with the
    # conversation; the doc tools join the gateway's registry.
    app.state.documents = DocumentService(AttachmentStore(docs, prefix=s.firestore_prefix))
    # Recently deleted (slice 11): the owner's deletes keep a copy here for 30 days (undo);
    # only on persistent storage, else None and deletes stay R3
    app.state.undo = inj.undo or build_undo(s, built, docs)
    app.state.outside_tasks = OutsideTasks(docs, prefix=s.firestore_prefix)  # D8 (swept)


def _wire_slice12(app: FastAPI, s: Settings, docs: Docs, drive: DriveService | None) -> None:
    """Maps + YouTube (D2–D4) on JARVIS's own Google API key (None without one), and Drive,
    chosen folders only (D1): None unless JARVIS_DRIVE=on. Drive files go through the documents'
    ONE extraction slot (never two children at once)."""
    app.state.media = build_media(s, docs, google=app.state.google)
    one_slot = app.state.documents.extract
    app.state.drive = drive or build_drive_service(s, docs, extract=one_slot)
    if app.state.drive is not None and app.state.drive.extract is None:
        app.state.drive.extract = one_slot


def _wire_gateway(
    app: FastAPI, s: Settings, inj: _Injected, built: Storage | None, docs: Docs, audit: AuditTrail
) -> None:
    """The tool gateway with every tool family, and (slice 10 D) the owner's Allow / Ask first /
    Never rules and passkeys on the same documents: the gateway reads the rules on every call
    (one built elsewhere gets them too)."""
    gw: Gateway | None = inj.gateway
    if gw is None and s.tools_enabled:
        gw = _build_tool_gateway(app, s, built, docs, audit)
    app.state.permissions = build_permissions(
        s, docs, audit=gw.audit if gw is not None else audit, google=app.state.google
    )
    if gw is not None:
        _wrap_rules(app, gw)
    # Activity (R1 B): a per-day store and the observer that fills it, on every gateway
    app.state.activity_store = ActivityStore(docs, prefix=s.firestore_prefix)
    if gw is not None:
        attach_activity(gw, app.state.activity_store, s)
    app.state.activity = ActivityService(
        app.state.activity_store,
        app.state.undo,
        timezone=s.user_timezone,
        retention_days=s.activity_retention_days,
    )
    if app.state.documents.rules is None:  # Documents "Never": no upload, no file sent
        app.state.documents.rules = app.state.permissions
    app.state.gateway = gw


def _build_tool_gateway(
    app: FastAPI, s: Settings, built: Storage | None, docs: Docs, audit: AuditTrail
) -> Gateway:
    return build_gateway(
        s,
        approvals=built.approvals if built else None,
        audit=audit,
        google=app.state.google,
        memory=app.state.memory,
        web=app.state.web,
        documents=app.state.documents,
        undo=app.state.undo,
        # D8: to-dos JARVIS wrote from outside content, on the same documents
        marks=app.state.outside_tasks,
        drive=app.state.drive,
        media=app.state.media,
        docs=docs,  # R1 D: groceries, family, packages, digest
        # R2: each only when on (the server's token key; api/personal.py)
        vault=app.state.vault,
        notes=app.state.notes,
        belongings=app.state.belongings,
        home=app.state.home_parts,  # R3: home, camera and faces tools (only when on)
        r4=app.state.r4_parts,  # R4: vitals, systems check, connectors, people (each when on)
    )


def _wrap_rules(app: FastAPI, gw: Gateway) -> None:
    """The owner's rules (and passkeys for approvals), wrapped by Telegram's, wrapped by
    offline mode's."""
    if gw.rules is None:
        gw.rules = app.state.permissions
    if app.state.telegram is not None:
        # D4: the Telegram privacy rules wrap the owner's rules (the only supported way; the
        # service refuses Telegram turns without them)
        gw.rules = wrap_rules(gw.rules, app.state.telegram.store)
    # R1 C: offline mode's rules are the OUTERMOST layer, outside telegram's (an inner one
    # would be dropped by the channel wrapper); the Telegram marker stays visible through it
    assert gw.rules is not None  # set from the permissions service just above
    gw.rules = wrap_offline(gw.rules)
    if gw.approval_guard is None:
        gw.approval_guard = app.state.permissions


def _wire_brain(app: FastAPI, s: Settings, built: Storage | None, docs: Docs) -> None:
    app.state.brain = Brain(
        brains=app.state.brains,
        store=app.state.store,
        settings=s,
        gateway=app.state.gateway,
        billing=app.state.billing,
        memory=app.state.memory,
        wit=app.state.voice,
        documents=app.state.documents,
        brain_mode=app.state.brain_mode,  # R4 W3: the ONE switch the routes and People share
    )
    if app.state.brain.mode is not app.state.brain_mode:  # one object, or the HUD could lie
        raise RuntimeError("the Brain and the app must share one BrainMode")
    if app.state.telegram is not None:
        app.state.telegram.bind(app.state.brain)
    app.state.brief = build_brief_service(app, s, built, docs=docs)
    alerts: AlertSink = app.state.alerts

    async def brief_ready(uid: str) -> None:  # the alert's own toggle and limits apply
        await alerts.send(uid, ALERT_TEXT["brief_ready"], kind="brief_ready")

    app.state.brief.ready_hook = brief_ready


def _log_up(app: FastAPI, s: Settings) -> None:
    log.info(
        "jarvis up",
        extra={
            "env": s.env,
            "llm": app.state.router.provider.name,
            "brains": [b.id for b in app.state.brains.list()],
            "session_backend": s.session_backend.value,
            "google_tools": app.state.google is not None,
            "brief_scheduler": getattr(app.state, "scheduler_verifier", None) is not None,
            "voice_cloud": app.state.voice.engines is not None,
            "web_search": app.state.web is not None,
            "drive": app.state.drive is not None,
            "maps_youtube": app.state.media is not None,
            "vault": app.state.vault is not None,
            "notes": app.state.notes is not None,
            "things": app.state.belongings is not None,
            "home": app.state.home_store is not None,
            "faces": app.state.faces is not None,
            "browser_push": app.state.push is not None,
            # R4: each OFF-until-connected part says so here (and in its own console line)
            "brain_mode": app.state.brain_mode.state,
            "vitals": app.state.vitals is not None,
            "systems_check": app.state.health is not None,
            "github": app.state.github is not None,
            "photos": app.state.photos is not None,
            "people_research": app.state.people is not None,
        },
    )


def _tick_jobs(app: FastAPI) -> tuple[Any, ...]:
    """R2's feature jobs, the alert policy's when the home watchdog doesn't run them, and R4's
    vitals poll and health check (D14: on the existing tick, no new Cloud Scheduler job)."""
    jobs = (*personal_tick_jobs(app), *notify_tick_jobs(app), *r4_tick_jobs(app))
    check_job_names(jobs)
    return jobs


async def _drain_memory(app: FastAPI) -> None:
    """Let a learning run that is under way finish (bounded)."""
    if app.state.memory is not None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(app.state.memory.drain(), DRAIN_TIMEOUT_S)


# (state attribute, closer path under it). Resolved when the close runs, so what is closed is
# whatever the app holds at that time. Listed in the order the wiring opens them.
_CLOSABLES: tuple[tuple[str, str], ...] = (
    ("store", "close"),
    ("google", "http.aclose"),
    ("fx_http", "aclose"),
    ("voice", "aclose"),
    ("telegram", "client.aclose"),
    ("web", "aclose"),
    ("drive", "aclose"),
    ("media", "aclose"),
    ("scheduler_verifier", "aclose"),
    ("push", "aclose"),  # R3 D11: Web Push's pinned client
    ("github", "aclose"),  # R4 C: the GitHub client's one httpx client
)


def _closer(app: FastAPI, attr: str, path: str) -> Callable[[], Awaitable[None]]:
    async def close() -> None:
        obj = getattr(app.state, attr, None)
        if obj is None:
            return
        for part in path.split("."):
            obj = getattr(obj, part)
        await obj()

    return close


class _Closers:
    """Registers each close on an AsyncExitStack as its resource appears, so a failing close
    never skips the rest and a wiring failure closes what was already opened. The stack runs
    them last-in first-out: the session store, opened first, closes last."""

    def __init__(self, app: FastAPI, stack: contextlib.AsyncExitStack) -> None:
        self._app, self._stack, self._seen = app, stack, set[str]()

    def register_new(self) -> None:
        for attr, path in _CLOSABLES:
            if attr not in self._seen and getattr(self._app.state, attr, None) is not None:
                self._seen.add(attr)
                self._stack.push_async_callback(_closer(self._app, attr, path))


def _lifespan(
    s: Settings, inj: _Injected
) -> Callable[[FastAPI], contextlib.AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            closers = _Closers(app, stack)
            built = build_storage(s) if inj.store is None else None
            docs, audit = _wire_core(app, s, inj, built)
            closers.register_new()
            _wire_features(app, s, inj, built, docs)
            closers.register_new()
            _wire_slice12(app, s, docs, inj.drive)
            closers.register_new()
            wire_personal(app, s, docs)  # R2: vault, notes, things, DigiLocker inbox
            wire_home(app, s, docs, audit)  # R3: home link, camera, faces (tools need them)
            await wire_r4(app, s, docs, audit)  # R4: brain mode (loaded), vitals, health, people
            closers.register_new()
            _wire_gateway(app, s, inj, built, docs, audit)
            closers.register_new()
            _wire_brain(app, s, built, docs)
            closers.register_new()
            wire_privacy(app, s, docs, audit)  # R2 D14: after the gateway and the brief
            app.state.tick_jobs = _tick_jobs(app)  # R2 + R3 H3: run after the tick's sweeps
            stack.push_async_callback(_drain_memory, app)  # runs first on the way out
            await adopt_legacy_sessions(app.state.store, s)
            _log_up(app, s)
            yield

    return lifespan


def _install_middleware(app: FastAPI, s: Settings) -> None:
    """In this order (Starlette wraps outward, so the last added runs first): the body cap, the
    rate limit, the Google sign-in session (with its routes), then the trace id."""
    # Every body is size-capped before it is parsed or authenticated (innermost of the http
    # middlewares, so the trace id still goes on a 413). Tighter per-route caps apply first.
    # Only the attachment and vault uploads have a larger cap (10 MB each, checked again by the
    # route).
    app.add_middleware(
        BodySizeLimit,
        max_bytes=MAX_BODY_BYTES,
        routes={
            ATTACH_PATH: ATTACH_BODY_BYTES,
            VAULT_UPLOAD_PATH: VAULT_BODY_BYTES,
            WEBHOOK_PATH: MAX_WEBHOOK_BYTES,  # R3: the bridge's signed events (128 KB)
            HOME_LINK_PATH: HOME_LINK_BYTES,  # R3: a link request is a few hundred bytes
        },
    )
    if s.rate_limit_per_minute > 0:
        app.middleware("http")(make_middleware(RateLimiter(s.rate_limit_per_minute)))
    if s.auth_mode is AuthMode.GOOGLE:
        _install_google_sign_in(app, s)

    @app.middleware("http")
    async def trace_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-trace-id")
        tid = incoming if incoming and len(incoming) <= 64 else new_trace_id()
        set_trace_id(tid)
        response = await call_next(request)
        response.headers["x-trace-id"] = tid
        response.headers["X-Content-Type-Options"] = "nosniff"
        if s.cookie_secure:  # i.e. not dev: we are behind TLS
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def _install_google_sign_in(app: FastAPI, s: Settings) -> None:
    s._require_google_auth_config()
    assert s.session_secret is not None
    # Added after the http middlewares so it runs *before* them (Starlette wraps outward).
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.session_secret.get_secret_value(),
        session_cookie="jarvis_session",
        max_age=s.session_cookie_max_age_s,
        same_site="lax",
        https_only=s.cookie_secure,
    )
    app.state.oauth = build_oauth(s)
    app.include_router(auth_router)
    if google_tools_configured(s):  # off (404 → "Not available") without a vault key
        register_tools_oauth(app.state.oauth, s)
        app.include_router(integrations_router)


def _install_core_errors(app: FastAPI) -> None:
    """Error mapping: never leak stack traces, always carry the trace id."""

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default echoes each bad `input` back: a NaN / Infinity in the JSON body
        # (Python's reader accepts them) then can't be rendered and became a 500. Same shape,
        # without echoing what was sent.
        errors = [{k: e[k] for k in ("type", "loc", "msg") if k in e} for e in exc.errors()]
        return _err(422, {"detail": errors})

    @app.exception_handler(SessionNotFound)
    async def _nf(_: Request, exc: SessionNotFound) -> JSONResponse:
        return _err(404, {"error": "session_not_found", "session_id": str(exc)})

    @app.exception_handler(SessionConflict)
    async def _conflict(_: Request, exc: SessionConflict) -> JSONResponse:
        # another window (on another instance) changed this conversation first; the body says
        # whether the owner's message was stored (MessageNotSaved) or only the reply was lost
        return _err(409, conflict_body(exc))

    @app.exception_handler(LookupError)
    async def _lookup(_: Request, exc: LookupError) -> JSONResponse:
        return _err(404, {"error": "not_found", "detail": str(exc)})

    @app.exception_handler(InputRejected)
    async def _bad(_: Request, exc: InputRejected) -> JSONResponse:
        return _err(422, {"error": "input_rejected", "detail": str(exc)})

    @app.exception_handler(LLMAuthError)
    async def _auth(_: Request, exc: LLMAuthError) -> JSONResponse:
        log.error("llm auth error", extra={"detail": str(exc)[:200]})
        return _err(502, {"error": "llm_auth", "detail": "LLM credentials rejected"})

    @app.exception_handler(BrainOff)
    async def _brain_off(_: Request, exc: BrainOff) -> JSONResponse:
        return _err(409, {"error": "brain_off", "detail": NO_AI_REFUSAL})

    @app.exception_handler(LLMError)
    async def _llm(_: Request, exc: LLMError) -> JSONResponse:
        log.error("llm error", extra={"detail": str(exc)[:500]})  # vendor text stays in logs
        return _err(503, {"error": "llm_unavailable", "detail": friendly_llm_error(exc)})

    @app.exception_handler(CSRFRejected)
    async def _csrf(_: Request, exc: CSRFRejected) -> JSONResponse:
        return _err(403, {"error": "csrf", "detail": "missing X-Requested-With header"})

    @app.exception_handler(BodyTooLarge)
    async def _body_too_large(_: Request, exc: BodyTooLarge) -> JSONResponse:
        return _err(413, too_large_body(str(exc.detail)))

    @app.exception_handler(SchedulerUnauthorized)
    async def _scheduler(_: Request, exc: SchedulerUnauthorized) -> Response:
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})


# Plain feature errors: (exception, status, error code); the detail is the exception's own words.
_FEATURE_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (BudgetReached, 402, "budget_reached"),
    (BudgetUnavailable, 503, "budget_unavailable"),
    (BudgetRejected, 422, "invalid_budget"),
    (BriefLimitReached, 429, "brief_limit"),
    (SettingsRejected, 422, "invalid_settings"),
    (ConsentRequired, 409, "consent_required"),
    (SensitiveRejected, 422, "sensitive"),
    (InvalidMemoryInput, 422, "input_rejected"),
    (MemoryFull, 409, "memory_full"),
    (MemoryUnavailable, 503, "memory_unavailable"),
    (ImportTooLarge, 413, "too_large"),
)


def _plain(status: int, code: str) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    """A handler answering `status` {error: code, detail: the exception's own words}."""

    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return _err(status, {"error": code, "detail": str(exc)})

    return handler


def _install_feature_errors(app: FastAPI) -> None:
    """Billing, brief and memory errors: {error, detail} with the exception's own words."""
    for exc_type, status, code in _FEATURE_ERRORS:
        app.add_exception_handler(exc_type, _plain(status, code))


def _include_routers(app: FastAPI, s: Settings, verifier: GoogleOIDCVerifier | None) -> None:
    app.include_router(v1_router)
    app.include_router(brief_router)
    app.include_router(usage_router)
    app.include_router(memory_router)
    app.include_router(web_router)
    app.include_router(media_router)
    app.include_router(deleted_router)
    install_voice(app)
    install_permissions(app)
    install_documents(app)
    install_drive(app)
    install_telegram(app)
    install_activity(app)
    install_offline(app)
    install_family(app)
    install_vault_inbox(app)  # R2 (before /v1/vault, whose prefix it shares)
    install_vault(app)
    install_belongings(app)
    install_notes(app)
    install_privacy(app)
    install_home(app)  # R3: /home/link, /home/webhook, the watchdog, /v1/home
    install_camera(app)  # R3: /v1/home/alarm, arm, disarm, cameras, feed, history
    install_faces(app)
    install_notify(app)  # R3: /v1/notify, /v1/push
    install_r4_routes(app)  # R4: /v1/vitals, /v1/health, /v1/connectors, /v1/people, brain mode
    _mount_scheduler(app, s, verifier)
    app.include_router(console_router)


def create_app(
    settings: Settings | None = None,
    *,
    provider: LLMProvider | None = None,
    store: SessionStore | None = None,
    gateway: Gateway | None = None,
    brains: BrainRegistry | None = None,
    scheduler_verifier: GoogleOIDCVerifier | None = None,
    billing: Billing | None = None,
    voice_engines: VoiceEngines | None = None,
    undo: UndoBin | None = None,
    drive: DriveService | None = None,
) -> FastAPI:
    s = settings or get_settings()
    configure_logging(s.log_level, s.log_json)
    if provider is None and brains is None:
        s.require_prod_invariants()
    if note := google_tools_startup_note(s):
        log.warning(note)
    inj = _Injected(
        provider=provider,
        store=store,
        gateway=gateway,
        brains=brains,
        billing=billing,
        voice_engines=voice_engines,
        undo=undo,
        drive=drive,
    )
    app = FastAPI(
        title="JARVIS", version="0.0.1", lifespan=_lifespan(s, inj), docs_url=None, redoc_url=None
    )
    _install_middleware(app, s)
    _install_core_errors(app)
    _install_feature_errors(app)
    _include_routers(app, s, scheduler_verifier)
    return app
