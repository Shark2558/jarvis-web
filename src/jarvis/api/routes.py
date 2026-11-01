# src/jarvis/api/routes.py
"""HTTP surface for Phase 0.

POST /v1/chat                 one turn (JSON)
POST /v1/chat/stream          one turn, text/plain streamed deltas (402 first if the monthly
                              limit refuses it: a stream that already said 200 can't)
GET  /v1/sessions             list the caller's sessions (+ total_cost_inr)
GET  /v1/sessions/{id}        full transcript (audit / replay) (+ total_cost_inr)
DELETE /v1/sessions/{id}      forget a session (owner's delete right)
GET  /health                  liveness + dependency check (unauthenticated)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.models import (
    ChatRequest,
    ChatResponse,
    PendingApproval,
    SessionSummary,
    SessionView,
)
from jarvis.memory.base import SessionNotFound, SessionStore
from jarvis.tools.audit import AuditEntry

router = APIRouter()


# ---- dependencies --------------------------------------------------------------------------


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _brain(request: Request) -> Brain:
    return request.app.state.brain  # type: ignore[no-any-return]


def _store(request: Request) -> SessionStore:
    return request.app.state.store  # type: ignore[no-any-return]


# ---- routes --------------------------------------------------------------------------------


class Health(BaseModel):
    status: str
    env: str
    llm: str
    session_backend: str
    session_store_ok: bool


@router.get("/health", response_model=Health)
async def health(request: Request) -> Health:
    s = _settings(request)
    ok = await _store(request).ping()
    return Health(
        status="ok" if ok else "degraded",
        env=s.env,
        llm=request.app.state.router.provider.name,
        session_backend=s.session_backend.value,
        session_store_ok=ok,
    )


class BrainInfo(BaseModel):
    id: str
    label: str
    default: bool
    trains_on_content: bool
    tools_allowed: bool
    warning: str
    models: dict[str, str]


@router.get("/v1/brains", response_model=list[BrainInfo], dependencies=[Depends(require_auth)])
async def list_brains(brain: Brain = Depends(_brain)) -> list[BrainInfo]:
    """Every configured brain; the console builds its dropdown from this."""
    reg = brain.brains
    return [
        BrainInfo(
            id=b.id,
            label=b.label,
            default=b.id == reg.default.id,
            trains_on_content=b.trains_on_content,
            tools_allowed=b.tools_allowed,
            warning=b.warning,
            models={t.value: m for t, m in b.tiers.items()},
        )
        for b in reg.list()
    ]


@router.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_auth)])
async def chat(
    req: ChatRequest, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> ChatResponse:
    return await brain.chat(req.model_copy(update={"user_id": uid}))


@router.post("/v1/chat/stream", dependencies=[Depends(require_auth)])
async def chat_stream(
    req: ChatRequest, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> StreamingResponse:
    req = req.model_copy(update={"user_id": uid})
    await brain.check_budget(req)  # 402 now; the stream checks again before its model call
    return StreamingResponse(brain.chat_stream(req), media_type="text/plain; charset=utf-8")


@router.get(
    "/v1/sessions", response_model=list[SessionSummary], dependencies=[Depends(require_auth)]
)
async def list_sessions(
    limit: int = 50,
    store: SessionStore = Depends(_store),
    brain: Brain = Depends(_brain),
    uid: str = Depends(current_user),
) -> list[SessionSummary]:
    rows = await store.list_for_user(uid, limit=max(1, min(limit, 200)))
    return [
        r.model_copy(update={"total_cost_inr": round(await brain.billing.inr(r.total_cost_usd), 4)})
        for r in rows
    ]


@router.get(
    "/v1/sessions/{session_id}", response_model=SessionView, dependencies=[Depends(require_auth)]
)
async def get_session(
    session_id: str,
    store: SessionStore = Depends(_store),
    brain: Brain = Depends(_brain),
    uid: str = Depends(current_user),
) -> SessionView:
    s = await store.get_or_raise(session_id)
    if s.user_id != uid:
        raise SessionNotFound(session_id)
    inr = round(await brain.billing.inr(s.total_cost_usd), 4)
    return SessionView.model_validate({**dict(s), "total_cost_inr": inr})


@router.delete("/v1/sessions/{session_id}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_session(
    session_id: str, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> None:
    """Deletes the conversation and its waiting approvals. Permanent (the console confirms)."""
    if not await brain.forget(session_id, user_id=uid):
        raise HTTPException(404, "session not found")


# ---- approvals & audit (Phase 2) -----------------------------------------------------------


class Decision(BaseModel):
    session_id: str  # a client-sent user_id is ignored (pydantic drops unknown fields)


async def _pending_models(brain: Brain, uid: str) -> list[PendingApproval]:
    if brain.gateway is None:
        return []
    mine = f"{uid}:"  # approvals are scoped "<user_id>:<session_id>"
    return [
        PendingApproval.from_action(a)
        for a in await brain.gateway.pending()
        if (a.scope or "").startswith(mine)
    ]


@router.get(
    "/v1/approvals", response_model=list[PendingApproval], dependencies=[Depends(require_auth)]
)
async def list_approvals(
    brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> list[PendingApproval]:
    return await _pending_models(brain, uid)


@router.post(
    "/v1/approvals/{approval_id}/approve",
    response_model=ChatResponse,
    dependencies=[Depends(require_auth)],
)
async def approve(
    approval_id: str, d: Decision, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> ChatResponse:
    return await brain.approve(approval_id, session_id=d.session_id, user_id=uid)


@router.post(
    "/v1/approvals/{approval_id}/decline",
    response_model=ChatResponse,
    dependencies=[Depends(require_auth)],
)
async def decline(
    approval_id: str, d: Decision, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> ChatResponse:
    return await brain.decline(approval_id, session_id=d.session_id, user_id=uid)


AUDIT_MAX_LIMIT = 200


class AuditView(BaseModel):
    verified: bool
    entries: list[AuditEntry]


@router.get("/v1/audit", response_model=AuditView, dependencies=[Depends(require_auth)])
async def audit(brain: Brain = Depends(_brain), limit: int = 50) -> AuditView:
    """The newest `limit` entries and whether that window verifies (O(limit) reads)."""
    if brain.gateway is None:
        return AuditView(verified=True, entries=[])
    tail = await brain.gateway.audit.tail(max(1, min(limit, AUDIT_MAX_LIMIT)))
    return AuditView(verified=tail.verified, entries=tail.entries)
