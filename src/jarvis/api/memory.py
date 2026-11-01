# src/jarvis/api/memory.py
"""Long-term memory HTTP surface (slice 8 §5; Layer 1 → 3). Owner-only: `require_auth` +
`current_user` (a client `user_id` is ignored); cookie writes need `X-Requested-With: JARVIS`
(enforced by `require_auth`); rate-limited with the rest of /v1.

GET    /v1/memory                  MemoryView {settings, profile, facts, counts,
                                   learn_cost_note_inr, runs_today}
PUT    /v1/memory/settings         {use?, learn?, confirm_spend?} → settings; learn:true without
                                   confirm_spend → 409 consent_required
PUT    /v1/memory/profile/{label}  {text} (≤ 1,000, filtered) → profile; 404 unknown label,
                                   422 sensitive
POST   /v1/memory/facts            {text, category} → fact (origin "added"); 422 sensitive,
                                   409 memory_full
PATCH  /v1/memory/facts/{id}       {text?, category?, pinned?} → fact; 404, 422 sensitive
DELETE /v1/memory/facts/{id}       204; 404
GET    /v1/memory/export           JSON attachment jarvis-memory-YYYY-MM-DD.json (with history)
POST   /v1/memory/import           {data} → {added, skipped}; 413 too_large over 512 KB
DELETE /v1/memory                  {confirm: "FORGET"} → 204: facts + profile wiped, settings kept
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import ValidationError

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.core.guardrails import InputRejected
from jarvis.recall.errors import ImportTooLarge
from jarvis.recall.models import (
    IMPORT_MAX_BYTES,
    Fact,
    FactPatch,
    ForgetAll,
    ImportRequest,
    ImportResult,
    MemorySettings,
    MemoryView,
    NewFact,
    Profile,
    ProfileText,
    SettingsPatch,
)
from jarvis.recall.service import MemoryService

router = APIRouter(prefix="/v1/memory", dependencies=[Depends(require_auth)])
CONFIRM_WORD = "FORGET"


def _svc(request: Request) -> MemoryService:
    svc: MemoryService | None = getattr(request.app.state, "memory", None)
    if svc is None:
        raise LookupError("Long-term memory is switched off on this server.")
    return svc


@router.get("", response_model=MemoryView)
async def get_memory(
    svc: MemoryService = Depends(_svc), uid: str = Depends(current_user)
) -> MemoryView:
    return await svc.view(uid)


@router.put("/settings", response_model=MemorySettings)
async def put_settings(
    patch: SettingsPatch, svc: MemoryService = Depends(_svc), uid: str = Depends(current_user)
) -> MemorySettings:
    return await svc.update_settings(uid, patch)


@router.put("/profile/{label}", response_model=Profile)
async def put_profile(
    label: str,
    body: ProfileText,
    svc: MemoryService = Depends(_svc),
    uid: str = Depends(current_user),
) -> Profile:
    return await svc.put_profile(uid, label, body.text)


@router.post("/facts", response_model=Fact)
async def add_fact(
    body: NewFact, svc: MemoryService = Depends(_svc), uid: str = Depends(current_user)
) -> Fact:
    return await svc.add_fact(uid, body.text, body.category)


@router.patch("/facts/{fact_id}", response_model=Fact)
async def patch_fact(
    fact_id: str,
    body: FactPatch,
    svc: MemoryService = Depends(_svc),
    uid: str = Depends(current_user),
) -> Fact:
    return await svc.patch_fact(uid, fact_id, body)


@router.delete("/facts/{fact_id}", status_code=204)
async def delete_fact(
    fact_id: str, svc: MemoryService = Depends(_svc), uid: str = Depends(current_user)
) -> Response:
    await svc.delete_fact(uid, fact_id)
    return Response(status_code=204)


@router.get("/export")
async def export(svc: MemoryService = Depends(_svc), uid: str = Depends(current_user)) -> Response:
    body = json.dumps(await svc.export(uid), ensure_ascii=False, indent=2)
    name = f"jarvis-memory-{svc.today()}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/import", response_model=ImportResult)
async def import_memory(
    request: Request, svc: MemoryService = Depends(_svc), uid: str = Depends(current_user)
) -> ImportResult:
    """The body is size-checked before it is parsed."""
    raw = await request.body()
    if len(raw) > IMPORT_MAX_BYTES:
        raise ImportTooLarge()
    try:
        req = ImportRequest.model_validate_json(raw)
    except ValidationError:
        raise InputRejected("The file is not a JARVIS memory export.") from None
    try:
        return await svc.import_(uid, req.data)
    except ValueError:
        raise InputRejected("The file is not a JARVIS memory export.") from None


@router.delete("", status_code=204)
async def forget_everything(
    body: ForgetAll = Body(...),
    svc: MemoryService = Depends(_svc),
    uid: str = Depends(current_user),
) -> Response:
    if body.confirm != CONFIRM_WORD:
        raise InputRejected(f"Type {CONFIRM_WORD} to confirm.")
    await svc.forget_all(uid)
    return Response(status_code=204)


__all__ = ["router"]
