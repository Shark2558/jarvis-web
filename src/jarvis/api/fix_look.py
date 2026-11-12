# src/jarvis/api/fix_look.py
"""R11.1 Part D's routes, under `/v1/picture` (docs/plans/r11-1-observations.md D17). Owner-only
(`require_auth`; cookie writes need `X-Requested-With: JARVIS`), `no-store`. They read the part's
service from `app.state.r111_parts["look"].services` per request, and the owner's id only from
the sign-in (`current_user`), never from the body.

GET  /v1/picture            {part, ready, can, why}: the part's status, and whether a picture can
                            be looked at right now ("" or the reason in plain words: the AI is
                            off, no brain here may see a picture). No model call, nothing spent.
POST /v1/picture/research   {session_id, picture?} -> what the console shows for the picture
                            attached to the owner's LAST message of that conversation:
                            {status: "done", message, person, scene, text[], subjects[{kind,
                            name}], sources[{about, n, title, domain, url, snippet}], notes[],
                            offer: {name} | null, pictures}; or {status, message} in plain words
                            when it did not run (no picture, the AI off, the limit, "waiting"
                            for his approval, "denied" by his Permissions row). 422 for a
                            malformed body; 429 past the limit; 503 when the tools are off.

The research is the `picture_research` tool, called THROUGH THE GATEWAY like any tool call (his
"Pictures" row decides; the audit chain records it). The links come from the service's last
report for that conversation: a model is never shown a link, the owner's console is. Everything
the picture says reaches the page as JSON text and is set with `textContent` there.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.documents.pictures import MAX_PICTURES_PER_TURN
from jarvis.fixes.ports import NOT_BUILT, ROUTE_PREFIX, FixPart, PartName
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.picture.part import SERVICE
from jarvis.picture.research import OFF, PictureResearch, Report
from jarvis.picture.tools import PICTURE_RESEARCH
from jarvis.tools.gateway import Gateway, GatewayOutcome

log = get_logger(__name__)

PART: PartName = "look"
PREFIX = ROUTE_PREFIX[PART]
NO_STORE = {"Cache-Control": "no-store"}
RESEARCH_PER_MINUTE = 6
SESSION_ID = r"^[A-Za-z0-9_-]{1,64}$"
TOO_MANY = "Too many pictures; wait a moment."
TOOLS_OFF = "Tools are switched off on this server."
WAITING = "That needs your OK, Sir: the approval is waiting in Approvals."
DENIED = "Picture research is set to 'Never' in Permissions, Sir."
FAILED = "The picture could not be researched just now, Sir. Please try again."
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])


class ResearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(pattern=SESSION_ID)
    picture: StrictInt = Field(default=1, ge=1, le=MAX_PICTURES_PER_TURN)


def part_of(request: Request) -> FixPart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r111_parts", None) or {}
    return parts.get(PART)


def _service(request: Request) -> PictureResearch | None:
    part = part_of(request)
    found = part.services.get(SERVICE) if part is not None else None
    return found if isinstance(found, PictureResearch) else None


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _limited(request: Request, uid: str) -> bool:
    state = request.app.state
    limiter: RateLimiter | None = getattr(state, "picture_limiter", None)
    if limiter is None:
        limiter = state.picture_limiter = RateLimiter(RESEARCH_PER_MINUTE)
    return not limiter.allow(uid)[0]


def _shown(report: Report) -> dict[str, Any]:
    """What the console shows of a finished research: words, and the sources with their links."""
    return {
        "status": "done",
        "message": report.message,
        "person": report.person,
        "scene": report.scene,
        "text": list(report.text),
        "subjects": [{"kind": s.kind, "name": s.name} for s in report.subjects],
        "sources": [
            {
                "about": f.subject.name,
                "n": s.n,
                "title": s.title,
                "domain": s.domain,
                "url": s.url,
                "snippet": s.snippet,
            }
            for f in report.findings
            for s in f.sources
        ],
        "notes": [f.found.note for f in report.findings if f.found.note],
        "offer": {"name": report.named} if report.named else None,
        "pictures": report.pictures,
    }


@router.get("")
async def status(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    part = part_of(request)
    ready = part.ready if part is not None else NOT_BUILT
    service = _service(request)
    if service is None:
        return _answer(200, {"part": PART, "ready": ready, "can": False, "why": OFF})
    cant = await service.eyes.state(uid)
    why = str(cant) if cant is not None else ""
    return _answer(200, {"part": PART, "ready": ready, "can": cant is None, "why": why})


@router.post("/research", response_model=None)
async def research(
    body: ResearchBody, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    if _limited(request, uid):
        return _answer(429, {"error": "rate_limited", "detail": TOO_MANY})
    service = _service(request)
    if service is None:
        return _answer(200, {"status": "off", "message": OFF})
    gateway: Gateway | None = getattr(request.app.state, "gateway", None)
    if gateway is None:
        return _answer(503, {"error": "unavailable", "detail": TOOLS_OFF})
    call = ToolCall(
        id=f"look-{uuid.uuid4().hex[:8]}",
        name=PICTURE_RESEARCH,
        arguments={"picture": body.picture},
    )
    res = await gateway.execute(call, scope=f"{uid}:{body.session_id}")
    if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION:
        return _answer(200, {"status": "waiting", "message": WAITING})
    if res.outcome is GatewayOutcome.DENIED:
        return _answer(200, {"status": "denied", "message": DENIED})
    said = res.result if isinstance(res.result, dict) else {}
    if res.outcome is not GatewayOutcome.EXECUTED or not isinstance(said.get("status"), str):
        log.warning("picture research failed", extra={"outcome": res.outcome.value})
        return _answer(503, {"error": "unavailable", "detail": FAILED})
    if said["status"] != "done":  # it did not run: the tool's own fixed words
        return _answer(200, {"status": said["status"], "message": str(said.get("message", ""))})
    report = service.last(uid, body.session_id)
    if report is None or report.status != "done":
        return _answer(503, {"error": "unavailable", "detail": FAILED})
    return _answer(200, _shown(report))


__all__ = ["PREFIX", "RESEARCH_PER_MINUTE", "part_of", "router"]
