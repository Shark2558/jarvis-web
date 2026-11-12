# src/jarvis/api/fix_files.py
"""R11.1 Part B's routes, under `/v1/input` (docs/plans/r11-1-observations.md D8, D9, D12).
Owner-only (`require_auth`; cookie writes need `X-Requested-With: JARVIS`, enforced there),
`no-store`, and each reads the part's services from `app.state.r111_parts["files"].services` per
request. No route here acts on anything: none writes, sends or deletes, so none calls a tool.

GET  /v1/input              {part, ready, understand, limits {accept [".pdf", ...], max_files,
                            file_mb, total_mb, folder_max_files, zip_max_files, picture_max_kb,
                            picture_side, max_pictures}}: the part's status and what the console's
                            file picker may offer (its accept list comes from here, not the page).
POST /v1/input/understand   {heard (1-2,000), alternatives? (<= 3), files? (<= 20 names),
                            session_id?, confidence? (0-1)} -> {understood, changed, sure,
                            question, via: rules | ai | none | off}. The fixed rules first and
                            free; the fast tier only when unsure, admitted and metered, never in
                            No-AI mode; else one short question. <= 60 a minute per owner (429).
GET  /v1/input/hints        ?session_id= -> {hints [...]}: the per-turn recognition hints (file
                            names as said, the conversation's nouns) for the browser recogniser.
POST /v1/input/estimate     {attachments [ids], message?, brain?, tier?} -> {show, tier, inr,
                            stronger_tier, stronger_inr, suggest, line}: the rupee estimate
                            before a costly reply. `show` is false below ₹5, for a free brain,
                            in No-AI mode and for small files. It never calls a model.

Errors use the app's shape {"error": code, "detail": plain words}; a body that does not fit is
FastAPI's 422. Heard words, file names and questions are never logged.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.documents.limits import (
    ACCEPT,
    MAX_FILE_BYTES,
    PICTURE_SHRINK_SIDE,
)
from jarvis.documents.service import MB, policy_from
from jarvis.fixes.ports import NOT_BUILT, ROUTE_PREFIX, FixPart, PartName
from jarvis.understand.estimate import MAX_IDS, Estimator
from jarvis.understand.service import HEARD_LIMIT, MAX_ALTERNATIVES, MAX_FILES, UnderstandService

PART: PartName = "files"
PREFIX = ROUTE_PREFIX[PART]
NO_STORE = {"Cache-Control": "no-store"}
NAME_CHARS = 300
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])

Heard = Annotated[str, Field(max_length=HEARD_LIMIT)]
Name = Annotated[str, Field(max_length=NAME_CHARS)]


class UnderstandIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    heard: str = Field(min_length=1, max_length=HEARD_LIMIT)
    alternatives: list[Heard] = Field(default_factory=list, max_length=MAX_ALTERNATIVES)
    files: list[Name] = Field(default_factory=list, max_length=MAX_FILES)
    session_id: str | None = Field(default=None, max_length=64)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class EstimateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attachments: list[Annotated[str, Field(max_length=64)]] = Field(
        default_factory=list, max_length=MAX_IDS
    )
    message: str = Field(default="", max_length=100_000)
    brain: str | None = Field(default=None, max_length=64)
    tier: str | None = Field(default=None, max_length=16)


def part_of(request: Request) -> FixPart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r111_parts", None) or {}
    return parts.get(PART)


def _json(body: dict[str, Any], status: int = 200, **headers: str) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={**NO_STORE, **headers})


def _off() -> JSONResponse:
    return _json(
        {"error": "not_available", "detail": "This part of JARVIS is not set up on this server."},
        status=503,
    )


def _service(request: Request, name: str) -> Any:
    part = part_of(request)
    return part.services.get(name) if part is not None else None


def _limits(request: Request) -> dict[str, Any]:
    p = policy_from(request.app.state.settings)
    return {
        "accept": list(ACCEPT),
        "max_files": p.max_files,
        "file_mb": MAX_FILE_BYTES // MB,
        "total_mb": p.total_bytes // MB,
        "folder_max_files": p.folder_max_files,
        "zip_max_files": p.zip_max_files,
        "picture_max_kb": p.picture_max_bytes // 1024,
        "picture_side": PICTURE_SHRINK_SIDE,
        "max_pictures": p.max_pictures,
    }


@router.get("")
async def status(request: Request) -> JSONResponse:
    part = part_of(request)
    ready = part.ready if part is not None else NOT_BUILT
    svc: UnderstandService | None = _service(request, "understand")
    body = {
        "part": PART,
        "ready": ready,
        "understand": bool(svc is not None and svc.enabled),
        "limits": _limits(request),
    }
    return _json(body)


@router.post("/understand")
async def understand(
    body: UnderstandIn, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    svc: UnderstandService | None = _service(request, "understand")
    if svc is None:
        return _off()
    allowed, wait = svc.allow(uid)
    if not allowed:
        return _json(
            {"error": "rate_limited", "detail": "Too many requests; wait a moment."},
            status=429,
            **{"Retry-After": str(max(1, int(wait + 0.999)))},
        )
    out = await svc.understand(
        uid,
        body.heard,
        alternatives=body.alternatives,
        files=body.files,
        session_id=body.session_id,
        confidence=body.confidence,
    )
    return _json(asdict(out))


@router.get("/hints")
async def hints(
    request: Request, session_id: str | None = None, uid: str = Depends(current_user)
) -> JSONResponse:
    svc: UnderstandService | None = _service(request, "understand")
    if svc is None:
        return _off()
    sid = session_id if session_id and len(session_id) <= 64 else None
    return _json({"hints": list((await svc.hints(uid, session_id=sid)).turn)})


@router.post("/estimate")
async def estimate(
    body: EstimateIn, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    est: Estimator | None = _service(request, "estimate")
    if est is None:
        return _off()
    out = await est.estimate(
        uid, attachments=body.attachments, message=body.message, brain=body.brain, tier=body.tier
    )
    return _json(asdict(out))


__all__ = ["PREFIX", "part_of", "router"]
