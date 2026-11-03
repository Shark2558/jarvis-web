# src/jarvis/api/app.py
"""FastAPI application factory (Layer 1 surface: web/desktop clients hit this).

Build with `create_app()` so tests can inject a mock provider and an in-memory store. It is a
short list of named steps (slice 12 final review): the lifespan wires the core (`_wire_core`),
the slice 10–11 features, the slice 12 ones (`_wire_slice12`: Maps + YouTube, Drive), the gateway
with the owner's rules and the Brain; then the middleware, the error mapping and the routers.
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

from jarvis.api.auth import CSRFRejected, auth_router, build_oauth
from jarvis.api.body import MAX_BODY_BYTES, BodySizeLimit, BodyTooLarge, too_large_body
from jarvis.api.brief import internal_router as brief_internal_router
from jarvis.api.brief import router as brief_router
from jarvis.api.console import router as console_router
from jarvis.api.deleted import router as deleted_router
from jarvis.api.documents import ATTACH_BODY_BYTES, ATTACH_PATH, install_documents
from jarvis.api.drive import install_drive
from jarvis.api.identity import LEGACY_USER_ID, adopt_legacy_sessions, user_id_for_email
from jarvis.api.integrations import router as integrations_router
from jarvis.api.media import router as media_router
from jarvis.api.memory import router as memory_router
from jarvis.api.permissions import build_permissions, install_permissions
from jarvis.api.ratelimit import RateLimiter, make_middleware
from jarvis.api.routes import conflict_body
from jarvis.api.routes import router as v1_router
from jarvis.api.scheduler_auth import TICK_PATH, GoogleOIDCVerifier, SchedulerUnauthorized
from jarvis.api.usage import router as usage_router
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
from jarvis.brief.service import BriefLimitReached, BriefService, SettingsRejected
from jarvis.brief.store import BriefStore
from jarvis.config import AuthMode, SessionBackend, Settings, get_settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ApprovalStore, InputRejected
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.drive.service import DriveService, build_drive_service
from jarvis.integrations.google import (
    build_google_connector,
    google_tools_configured,
    google_tools_startup_note,
    register_tools_oauth,
)
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.base import LLMAuthError, LLMError, LLMProvider, LLMTransientError
from jarvis.llm.brains import BrainRegistry
from jarvis.logging import configure_logging, get_logger, new_trace_id, set_trace_id
from jarvis.media.service import build_media
from jarvis.memory import SessionConflict, SessionNotFound, SessionStore
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
from jarvis.tools.audit import AuditLog, AuditTrail
from jarvis.tools.gateway import Gateway
from jarvis.tools.setup import build_gateway
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
        audience=s.public_base_url.rstrip("/") + TICK_PATH, email=s.brief_scheduler_sa
    )
    app.include_router(brief_internal_router)


def friendly_llm_error(exc: LLMError) -> str:
    """Owner-facing wording. Raw vendor error bodies never reach the browser."""
    low = str(exc).lower()
    if "credit balance" in low or "billing" in low or "quota" in low:
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
    app.state.brains = inj.brains or BrainRegistry.from_settings(s, inj.provider)
    app.state.router = app.state.brains.router_for(app.state.brains.default.id)
    tokens = built.tokens if built else MemoryTokenStore()
    app.state.google = build_google_connector(s, tokens)
    docs = app_docs(built)
    app.state.fx_http = fx_client(s)
    app.state.billing = inj.billing or build_billing(
        s, docs, app.state.brains, http=app.state.fx_http
    )
    audit: AuditTrail = (
        inj.gateway.audit if inj.gateway is not None else built.audit if built else AuditLog()
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
        gw = build_gateway(
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
        )
    app.state.permissions = build_permissions(
        s, docs, audit=gw.audit if gw is not None else audit, google=app.state.google
    )
    if gw is not None and gw.rules is None:
        gw.rules = app.state.permissions
    if gw is not None and gw.approval_guard is None:
        gw.approval_guard = app.state.permissions
    if app.state.documents.rules is None:  # Documents "Never": no upload, no file sent
        app.state.documents.rules = app.state.permissions
    app.state.gateway = gw


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
    )
    app.state.brief = build_brief_service(app, s, built, docs=docs)


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
        },
    )


async def _shut_down(app: FastAPI) -> None:
    """Close what the app opened, in the order it was opened."""
    if app.state.memory is not None:  # let a learning run that is under way finish
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(app.state.memory.drain(), DRAIN_TIMEOUT_S)
    if app.state.google is not None:
        await app.state.google.http.aclose()
    if app.state.fx_http is not None:
        await app.state.fx_http.aclose()
    await app.state.voice.aclose()
    if app.state.web is not None:
        await app.state.web.aclose()
    if app.state.drive is not None:
        await app.state.drive.aclose()
    if app.state.media is not None:
        await app.state.media.aclose()
    verifier = getattr(app.state, "scheduler_verifier", None)
    if verifier is not None:
        await verifier.aclose()
    await app.state.store.close()


def _lifespan(
    s: Settings, inj: _Injected
) -> Callable[[FastAPI], contextlib.AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        built = build_storage(s) if inj.store is None else None
        docs, audit = _wire_core(app, s, inj, built)
        _wire_features(app, s, inj, built, docs)
        _wire_slice12(app, s, docs, inj.drive)
        _wire_gateway(app, s, inj, built, docs, audit)
        _wire_brain(app, s, built, docs)
        await adopt_legacy_sessions(app.state.store, s)
        _log_up(app, s)
        try:
            yield
        finally:
            await _shut_down(app)

    return lifespan


def _install_middleware(app: FastAPI, s: Settings) -> None:
    """In this order (Starlette wraps outward, so the last added runs first): the body cap, the
    rate limit, the Google sign-in session (with its routes), then the trace id."""
    # Every body is size-capped before it is parsed or authenticated (innermost of the http
    # middlewares, so the trace id still goes on a 413). Tighter per-route caps apply first.
    # Only the attachment upload has a larger cap (its own 10 MB, checked again by the route).
    app.add_middleware(
        BodySizeLimit, max_bytes=MAX_BODY_BYTES, routes={ATTACH_PATH: ATTACH_BODY_BYTES}
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
