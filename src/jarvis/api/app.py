# src/jarvis/api/app.py
"""FastAPI application factory (Layer 1 surface: web/desktop clients hit this).

Build with `create_app()` so tests can inject a mock provider and an in-memory store.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from jarvis.api.auth import CSRFRejected, auth_router, build_oauth
from jarvis.api.brief import internal_router as brief_internal_router
from jarvis.api.brief import router as brief_router
from jarvis.api.console import router as console_router
from jarvis.api.identity import LEGACY_USER_ID, adopt_legacy_sessions, user_id_for_email
from jarvis.api.integrations import router as integrations_router
from jarvis.api.ratelimit import RateLimiter, make_middleware
from jarvis.api.routes import router as v1_router
from jarvis.api.scheduler_auth import TICK_PATH, GoogleOIDCVerifier, SchedulerUnauthorized
from jarvis.brief.service import BriefLimitReached, BriefService, SettingsRejected
from jarvis.brief.store import BriefStore
from jarvis.config import AuthMode, SessionBackend, Settings, get_settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ApprovalStore, InputRejected
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
from jarvis.memory import SessionNotFound, SessionStore
from jarvis.storage import Storage, build_storage
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog, AuditTrail
from jarvis.tools.gateway import Gateway
from jarvis.tools.setup import build_gateway

log = get_logger(__name__)


def _err(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body)


def build_brief_service(app: FastAPI, s: Settings, built: Storage | None) -> BriefService:
    """Same storage, Google link, brains, approvals and audit chain as the rest of the app;
    in-process documents when nothing persistent is configured (dev, tests)."""
    gw: Gateway | None = app.state.gateway
    docs = built.docs if built is not None and built.docs is not None else MemoryDocs()
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
    )


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
        gw: Gateway | None = gateway
        if gw is None and s.tools_enabled:
            gw = build_gateway(
                s,
                approvals=built.approvals if built else None,
                audit=built.audit if built else None,
                google=app.state.google,
            )
        app.state.gateway = gw
        app.state.brain = Brain(
            brains=app.state.brains, store=app.state.store, settings=s, gateway=app.state.gateway
        )
        app.state.brief = build_brief_service(app, s, built)
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
            },
        )
        try:
            yield
        finally:
            if app.state.google is not None:
                await app.state.google.http.aclose()
            verifier = getattr(app.state, "scheduler_verifier", None)
            if verifier is not None:
                await verifier.aclose()
            await app.state.store.close()

    app = FastAPI(title="JARVIS", version="0.0.1", lifespan=lifespan, docs_url=None, redoc_url=None)

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

    @app.exception_handler(SessionNotFound)
    async def _nf(_: Request, exc: SessionNotFound) -> JSONResponse:
        return _err(404, {"error": "session_not_found", "session_id": str(exc)})

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

    @app.exception_handler(BriefLimitReached)
    async def _brief_limit(_: Request, exc: BriefLimitReached) -> JSONResponse:
        return _err(429, {"error": "brief_limit", "detail": str(exc)})

    @app.exception_handler(SettingsRejected)
    async def _brief_settings(_: Request, exc: SettingsRejected) -> JSONResponse:
        return _err(422, {"error": "invalid_settings", "detail": str(exc)})

    @app.exception_handler(SchedulerUnauthorized)
    async def _scheduler(_: Request, exc: SchedulerUnauthorized) -> Response:
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})

    app.include_router(v1_router)
    app.include_router(brief_router)
    _mount_scheduler(app, s, scheduler_verifier)
    app.include_router(console_router)
    return app
