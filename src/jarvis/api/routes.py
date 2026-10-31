# src/jarvis/api/routes.py
"""HTTP surface for Phase 0.

POST /v1/chat                 one turn (JSON)
POST /v1/chat/stream          one turn, text/plain streamed deltas
GET  /v1/sessions             list the caller's sessions
GET  /v1/sessions/{id}        full transcript (audit / replay)
DELETE /v1/sessions/{id}      forget a session (owner's delete right)
GET  /health                  liveness + dependency check (unauthenticated)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from jarvis.api.auth import require_auth
from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest, ChatResponse, PendingApproval, Session, SessionSummary
from jarvis.memory.base import SessionStore

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


@router.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_auth)])
async def chat(req: ChatRequest, brain: Brain = Depends(_brain)) -> ChatResponse:
    return await brain.chat(req)


@router.post("/v1/chat/stream", dependencies=[Depends(require_auth)])
async def chat_stream(req: ChatRequest, brain: Brain = Depends(_brain)) -> StreamingResponse:
    return StreamingResponse(brain.chat_stream(req), media_type="text/plain; charset=utf-8")


@router.get(
    "/v1/sessions", response_model=list[SessionSummary], dependencies=[Depends(require_auth)]
)
async def list_sessions(
    user_id: str = "owner", limit: int = 50, store: SessionStore = Depends(_store)
) -> list[SessionSummary]:
    return await store.list_for_user(user_id, limit=min(limit, 200))


@router.get(
    "/v1/sessions/{session_id}", response_model=Session, dependencies=[Depends(require_auth)]
)
async def get_session(session_id: str, store: SessionStore = Depends(_store)) -> Session:
    return await store.get_or_raise(session_id)


@router.delete("/v1/sessions/{session_id}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_session(session_id: str, store: SessionStore = Depends(_store)) -> None:
    if not await store.delete(session_id):
        raise HTTPException(404, "session not found")


# ---- approvals & audit (Phase 2) -----------------------------------------------------------


class Decision(BaseModel):
    session_id: str
    user_id: str = "owner"


def _pending_models(brain: Brain) -> list[PendingApproval]:
    if brain.gateway is None:
        return []
    return [
        PendingApproval(
            id=a.id,
            tool=a.tool,
            summary=a.summary,
            arguments=a.arguments,
            risk=a.risk.value,
            expires_at=a.expires_at,
        )
        for a in brain.gateway.pending()
    ]


@router.get(
    "/v1/approvals", response_model=list[PendingApproval], dependencies=[Depends(require_auth)]
)
async def list_approvals(brain: Brain = Depends(_brain)) -> list[PendingApproval]:
    return _pending_models(brain)


@router.post(
    "/v1/approvals/{approval_id}/approve",
    response_model=ChatResponse,
    dependencies=[Depends(require_auth)],
)
async def approve(approval_id: str, d: Decision, brain: Brain = Depends(_brain)) -> ChatResponse:
    return await brain.approve(approval_id, session_id=d.session_id, user_id=d.user_id)


@router.post(
    "/v1/approvals/{approval_id}/decline",
    response_model=ChatResponse,
    dependencies=[Depends(require_auth)],
)
async def decline(approval_id: str, d: Decision, brain: Brain = Depends(_brain)) -> ChatResponse:
    return await brain.decline(approval_id, session_id=d.session_id, user_id=d.user_id)


@router.get("/v1/audit", dependencies=[Depends(require_auth)])
async def audit(brain: Brain = Depends(_brain), limit: int = 200) -> dict:
    if brain.gateway is None:
        return {"verified": True, "entries": []}
    entries = brain.gateway.audit.entries()[-min(limit, 1000) :]
    return {
        "verified": brain.gateway.audit.verify(),
        "entries": [e.model_dump(mode="json") for e in entries],
    }
