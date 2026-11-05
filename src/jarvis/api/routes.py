# src/jarvis/api/routes.py
"""HTTP surface for Phase 0.

POST /v1/chat                 one turn (JSON)
POST /v1/chat/stream          one turn, text/plain streamed deltas (402 first if the monthly
                              limit refuses it: a stream that already said 200 can't), then a
                              final event: "\x1e" + {"memory_used": [{id, text}]} (slice 8).
                              (No web `sources`: a stream has no tool round, and a reply cites
                              only what its own tool results showed — slice 10 review M5.)
                              The reply text never contains "\x1e" (stripped from the model's
                              deltas); clients parse the JSON after the LAST separator.
                              If the conversation changed in another window meanwhile
                              (slice 10), the final event is {"error": "session_conflict",
                              "detail": ...} and the reply was not saved.
GET  /v1/sessions             list the caller's sessions (+ total_cost_inr)
GET  /v1/sessions/{id}        full transcript (audit / replay) (+ total_cost_inr, + drafts: the
                              WhatsApp draft cards rebuilt from the stored results, final review)
DELETE /v1/sessions/{id}      forget a session (owner's delete right)
POST /v1/approvals/approve-all {session_id, ids ≤ 20} → ChatResponse + results (slice 11 D6)
GET  /health                  liveness + dependency check (unauthenticated)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.permissions import mark_passkey_cards
from jarvis.config import Settings
from jarvis.core.approve_all import MAX_IDS, ApprovalId, ApproveAllResponse
from jarvis.core.brain import Brain, StreamMeta
from jarvis.core.models import (
    ChatRequest,
    ChatResponse,
    PendingApproval,
    SessionSummary,
    SessionView,
)
from jarvis.memory.base import MessageNotSaved, SessionConflict, SessionNotFound, SessionStore
from jarvis.permissions.models import PasskeyProof
from jarvis.tools.audit import AuditEntry
from jarvis.tools.context import presenting_proof
from jarvis.whatsapp.restore import stored_drafts

router = APIRouter()
STREAM_FINAL = "\x1e"  # ASCII record separator: the reply text ends, the final event follows
REPLY_LOST = (
    "Your message was kept, but JARVIS's reply could not be saved because this conversation "
    "changed in another window. The conversation has been reloaded."
)
MESSAGE_LOST = (
    "Your message was not saved because this conversation changed in another window. The "
    "conversation has been reloaded: send it again if it is still needed."
)


def conflict_body(exc: SessionConflict) -> dict[str, str]:
    """The 409 body (and the stream's final event): says truthfully whether the owner's
    message was stored, so resending never duplicates it."""
    detail = MESSAGE_LOST if isinstance(exc, MessageNotSaved) else REPLY_LOST
    return {"error": "session_conflict", "detail": detail}


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


def _no_telegram(req: ChatRequest) -> None:
    """Only the Telegram service may set `channel="telegram"` (it grants no extra trust here)."""
    if req.channel == "telegram":
        raise HTTPException(422, "channel 'telegram' is set by the Telegram service only")


@router.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_auth)])
async def chat(
    req: ChatRequest, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> ChatResponse:
    _no_telegram(req)
    return await brain.chat(req.model_copy(update={"user_id": uid}))


@router.post("/v1/chat/stream", dependencies=[Depends(require_auth)])
async def chat_stream(
    req: ChatRequest, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> StreamingResponse:
    _no_telegram(req)
    req = req.model_copy(update={"user_id": uid})
    await brain.check_budget(req)  # 402 now; the stream checks again before its model call
    return StreamingResponse(_with_final_event(brain, req), media_type="text/plain; charset=utf-8")


async def _with_final_event(brain: Brain, req: ChatRequest) -> AsyncIterator[str]:
    """The reply's deltas, then one final event (only when the reply finished)."""
    meta = StreamMeta()
    try:
        async for delta in brain.chat_stream(req, meta=meta):
            text = delta.replace(STREAM_FINAL, "")  # model text can never forge the final event
            if text:
                yield text
    except SessionConflict as exc:  # the 200 is already sent: the final event says what happened
        yield STREAM_FINAL + json.dumps(conflict_body(exc), ensure_ascii=False)
        return
    used = [m.model_dump() for m in meta.memory_used]
    yield STREAM_FINAL + json.dumps({"memory_used": used}, ensure_ascii=False)


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
    # final review: the conversation's WhatsApp drafts get their Open in WhatsApp back
    drafts = stored_drafts(s)
    return SessionView.model_validate({**dict(s), "total_cost_inr": inr, "drafts": drafts})


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
    # slice 10 D: a passkey check made for this card, when the owner requires one for actions
    # that can't be undone (403 passkey_required without it; ignored on decline)
    passkey: PasskeyProof | None = None


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
    request: Request, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> list[PendingApproval]:
    return await mark_passkey_cards(request, uid, await _pending_models(brain, uid))


@router.post(
    "/v1/approvals/{approval_id}/approve",
    response_model=ChatResponse,
    dependencies=[Depends(require_auth)],
)
async def approve(
    approval_id: str,
    d: Decision,
    request: Request,
    brain: Brain = Depends(_brain),
    uid: str = Depends(current_user),
) -> ChatResponse:
    # the passkey check is made by the gateway's approval guard, on the card as it is now
    with presenting_proof(d.passkey):
        return await brain.approve(approval_id, session_id=d.session_id, user_id=uid)


class ApproveAll(BaseModel):
    # a client-sent user_id or passkey is ignored (pydantic drops unknown fields)
    session_id: str = Field(min_length=1, max_length=64)
    ids: list[ApprovalId] = Field(min_length=1, max_length=MAX_IDS)


@router.post(
    "/v1/approvals/approve-all",
    response_model=ApproveAllResponse,
    dependencies=[Depends(require_auth)],
)
async def approve_all(
    d: ApproveAll, brain: Brain = Depends(_brain), uid: str = Depends(current_user)
) -> ApproveAllResponse:
    """Slice 11 D6: the listed cards of this conversation that can be undone, in order; cards
    that can't be undone stay waiting for their own approval. No passkey is ever presented here,
    so the approval guard refuses any card that would need one."""
    with presenting_proof(None):
        return await brain.approve_all(d.ids, session_id=d.session_id, user_id=uid)


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
