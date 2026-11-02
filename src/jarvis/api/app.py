# src/jarvis/api/app.py
"""FastAPI application factory (Layer 1 surface: web/desktop clients hit this).

Build with `create_app()` so tests can inject a mock provider and an in-memory store.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
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
from jarvis.api.identity import LEGACY_USER_ID, adopt_legacy_sessions, user_id_for_email
from jarvis.api.integrations import router as integrations_router
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
) -> FastAPI:
    s = settings or get_settings()
    configure_logging(s.log_level, s.log_json)
    if provider is None and brains is None:
        s.require_prod_invariants()
    if note := google_tools_startup_note(s):
        log.warning(note)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = s
        built = build_storage(s) if store is None else None
        app.state.store = store or (built.sessions if built else None)
        app.state.brains = brains or BrainRegistry.from_settings(s, provider)
        app.state.router = app.state.brains.router_for(app.state.brains.default.id)
        tokens = built.tokens if built else MemoryTokenStore()
        app.state.google = build_google_connector(s, tokens)
        docs = app_docs(built)
        app.state.fx_http = fx_client(s)
        app.state.billing = billing or build_billing(
            s, docs, app.state.brains, http=app.state.fx_http
        )
        audit: AuditTrail = (
            gateway.audit if gateway is not None else built.audit if built else AuditLog()
        )
        app.state.memory = build_app_memory(s, docs, app.state.brains, app.state.billing, audit)
        # Voice (slice 9): settings + wit level always; Google speech only when switched on.
        # No network at start-up: credentials are looked up on first use.
        app.state.voice = build_voice_service(s, docs, app.state.billing, engines=voice_engines)
        app.state.web = build_web_service(s, docs)  # slice 10 B: None without a Tavily key
        # Attached files (slice 10 E): text and chunks on the same documents, deleted with the
        # conversation; the doc tools join the gateway's registry.
        app.state.documents = DocumentService(AttachmentStore(docs, prefix=s.firestore_prefix))
        # Recently deleted (slice 11): the owner's deletes keep a copy here for 30 days (undo);
        # only on persistent storage, else None and deletes stay R3
        app.state.undo = undo or build_undo(s, built, docs)
        gw: Gateway | None = gateway
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
            )
        # slice 10 D: the owner's Allow / Ask first / Never rules and passkeys, on the same
        # documents; the gateway reads the rules on every call (one built elsewhere gets them too)
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
        await adopt_legacy_sessions(app.state.store, s)
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
            },
        )
        try:
            yield
        finally:
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
            verifier = getattr(app.state, "scheduler_verifier", None)
            if verifier is not None:
                await verifier.aclose()
            await app.state.store.close()

    app = FastAPI(title="JARVIS", version="0.0.1", lifespan=lifespan, docs_url=None, redoc_url=None)

    # Every body is size-capped before it is parsed or authenticated (innermost of the http
    # middlewares, so the trace id still goes on a 413). Tighter per-route caps apply first.
    # Only the attachment upload has a larger cap (its own 10 MB, checked again by the route).
    app.add_middleware(
        BodySizeLimit, max_bytes=MAX_BODY_BYTES, routes={ATTACH_PATH: ATTACH_BODY_BYTES}
    )

    if s.rate_limit_per_minute > 0:
        app.middleware("http")(make_middleware(RateLimiter(s.rate_limit_per_minute)))

    if s.auth_mode is AuthMode.GOOGLE:
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

    # ---- error mapping: never leak stack traces, always carry the trace id ----------------

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

    @app.exception_handler(BudgetReached)
    async def _budget(_: Request, exc: BudgetReached) -> JSONResponse:
        return _err(402, {"error": "budget_reached", "detail": str(exc)})

    @app.exception_handler(BudgetUnavailable)
    async def _budget_unknown(_: Request, exc: BudgetUnavailable) -> JSONResponse:
        return _err(503, {"error": "budget_unavailable", "detail": str(exc)})

    @app.exception_handler(BudgetRejected)
    async def _budget_bad(_: Request, exc: BudgetRejected) -> JSONResponse:
        return _err(422, {"error": "invalid_budget", "detail": str(exc)})

    @app.exception_handler(BriefLimitReached)
    async def _brief_limit(_: Request, exc: BriefLimitReached) -> JSONResponse:
        return _err(429, {"error": "brief_limit", "detail": str(exc)})

    @app.exception_handler(SettingsRejected)
    async def _brief_settings(_: Request, exc: SettingsRejected) -> JSONResponse:
        return _err(422, {"error": "invalid_settings", "detail": str(exc)})

    @app.exception_handler(ConsentRequired)
    async def _consent(_: Request, exc: ConsentRequired) -> JSONResponse:
        return _err(409, {"error": "consent_required", "detail": str(exc)})

    @app.exception_handler(SensitiveRejected)
    async def _sensitive(_: Request, exc: SensitiveRejected) -> JSONResponse:
        return _err(422, {"error": "sensitive", "detail": str(exc)})

    @app.exception_handler(InvalidMemoryInput)
    async def _memory_input(_: Request, exc: InvalidMemoryInput) -> JSONResponse:
        return _err(422, {"error": "input_rejected", "detail": str(exc)})

    @app.exception_handler(MemoryFull)
    async def _memory_full(_: Request, exc: MemoryFull) -> JSONResponse:
        return _err(409, {"error": "memory_full", "detail": str(exc)})

    @app.exception_handler(MemoryUnavailable)
    async def _memory_down(_: Request, exc: MemoryUnavailable) -> JSONResponse:
        return _err(503, {"error": "memory_unavailable", "detail": str(exc)})

    @app.exception_handler(ImportTooLarge)
    async def _too_large(_: Request, exc: ImportTooLarge) -> JSONResponse:
        return _err(413, {"error": "too_large", "detail": str(exc)})

    @app.exception_handler(BodyTooLarge)
    async def _body_too_large(_: Request, exc: BodyTooLarge) -> JSONResponse:
        return _err(413, too_large_body(str(exc.detail)))

    @app.exception_handler(SchedulerUnauthorized)
    async def _scheduler(_: Request, exc: SchedulerUnauthorized) -> Response:
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})

    app.include_router(v1_router)
    app.include_router(brief_router)
    app.include_router(usage_router)
    app.include_router(memory_router)
    app.include_router(web_router)
    app.include_router(deleted_router)
    install_voice(app)
    install_permissions(app)
    install_documents(app)
    _mount_scheduler(app, s, scheduler_verifier)
    app.include_router(console_router)
    return app
