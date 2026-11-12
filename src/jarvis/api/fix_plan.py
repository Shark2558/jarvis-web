# src/jarvis/api/fix_plan.py
"""R11.1 Part A's routes, under `/v1/series` (docs/plans/r11-1-observations.md D5, D6, D21-A).
Owner-only (`require_auth` + `current_user`; a cookie write needs `X-Requested-With: JARVIS`),
`no-store`, changes rate-limited per owner. They read the part's services from
`app.state.r111_parts["plan"].services` per request, and every action is a tool call through
`app.state.gateway` (its policy, the owner's rows, the audit): nothing here writes to Google.

GET  /v1/series                     {part, ready, plans: [{id, name, sessions, done, skipped,
                                    replan}], waiting: [{plan, session, of, start, text}]}: the
                                    part's status, his plans (numbers and times only; `replan`:
                                    the sentence for skipped sessions that have no new date) and
                                    the check-ins that wait for an answer.
POST /v1/series/answer              {answer: done | skipped, series?, session?, session_id?}:
                                    `series_checkin`. "skipped" leaves the re-plan card in
                                    Approvals (in that conversation; a new one when none is open).
POST /v1/series/replan              {series?, session?, session_id?}: propose the re-plan card
                                    again (`series_reschedule`; nothing moves until he approves).
POST /v1/series/batches/retry       {batch, events: [...], name?, session_id?}: the events of a
                                    batch that failed, on a card through the same path
                                    (`calendar_create_events`). They are marked as outside
                                    words: this route can't know where they came from.
POST /v1/series/batches/{id}/undo   The owner's own "Undo all" press (D21-A).
                                    `calendar_undo_events` is ALWAYS a card for the model; here
                                    the gateway proposes that card (in this route's own scope,
                                    never a conversation's) and this request approves it at
                                    once, so the press needs no second tap and takes no path
                                    round the gateway (policy, approval guard, audit
                                    "confirmed; owner: Undo all" all apply). A card that still
                                    asked to remove the same batch is then withdrawn.

404 {error: "plans_off"} when the part, the gateway or the plans are off; 403 not_allowed (his
permission row); 409 not_done / not_linked (Google is not linked); 422 invalid; 429 rate_limited.
Words in `detail` are JARVIS's own.
`session_id` names the open conversation; one that is gone or not his is never used (a new one
of his own is made when a card needs it).
"""

from __future__ import annotations

import uuid
from datetime import tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.core.models import Session
from jarvis.core.prompts import PERSONA_VERSION
from jarvis.fixes.ports import NOT_BUILT, ROUTE_PREFIX, FixPart, PartName
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.series import cards
from jarvis.series.batch import NOT_LINKED
from jarvis.series.part import ENSURE, SERVICE
from jarvis.series.service import SeriesService
from jarvis.series.store import PlansUnreadable
from jarvis.series.tools import CHECKIN, RESCHEDULE
from jarvis.tools.calendar_batch import BATCH_ID, CREATE, UNDO
from jarvis.tools.context import presenting_proof
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult, approved_via
from jarvis.tools.reply_cards import BatchItem
from jarvis.tools.taint import context_trust

log = get_logger(__name__)

PART: PartName = "plan"
PREFIX = ROUTE_PREFIX[PART]
NO_STORE = {"Cache-Control": "no-store"}
CHANGES_PER_MINUTE = 30
PLAIN_SCOPE = "plan"  # a press that leaves no card needs no conversation
UNDO_VIA = "owner: Undo all"
OFF = "Calendar plans are off on this server."
NOT_ALLOWED = "Your Permissions switch this off, Sir."
NOT_DONE = "That couldn't be done just now, Sir."
GONE = "Those events are no longer in your calendar, Sir."
WAITING = "That needs your OK, Sir: the approval is waiting."
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = Field(default=None, max_length=64)


class AnswerBody(_Body):
    answer: Literal["done", "skipped"]
    series: str | None = Field(default=None, max_length=80)
    session: int | None = Field(default=None, ge=1, le=999)


class ReplanBody(_Body):
    series: str | None = Field(default=None, max_length=80)
    session: int | None = Field(default=None, ge=1, le=999)


class RetryBody(_Body):
    batch: str = Field(pattern=BATCH_ID.pattern)
    name: str = Field(default="", max_length=60)
    events: list[BatchItem] = Field(min_length=1, max_length=100)


def part_of(request: Request) -> FixPart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r111_parts", None) or {}
    return parts.get(PART)


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return _answer(status, {"error": code, "detail": detail})


def _service(request: Request) -> SeriesService | None:
    part = part_of(request)
    if part is None:
        return None
    ensure = part.services.get(ENSURE)
    if callable(ensure):
        ensure()  # the No-AI phrases, once (the wiring has no slot for them yet)
    found = part.services.get(SERVICE)
    return found if isinstance(found, SeriesService) else None


def _limited(request: Request, uid: str) -> bool:
    st = request.app.state
    limiter: RateLimiter | None = getattr(st, "plan_limit", None)
    if limiter is None:
        limiter = st.plan_limit = RateLimiter(CHANGES_PER_MINUTE)
    return not limiter.allow(uid)[0]


def _gate(request: Request, uid: str) -> Gateway | JSONResponse:
    """The gateway for a change, or the refusal (part off, or too many changes)."""
    gateway: Gateway | None = getattr(request.app.state, "gateway", None)
    if part_of(request) is None or gateway is None:
        return _error(404, "plans_off", OFF)
    if _limited(request, uid):
        return _error(429, "rate_limited", "Too many changes; wait a moment.")
    return gateway


async def _conversation(request: Request, uid: str, session_id: str | None) -> str | JSONResponse:
    """The conversation a card will wait in (an approval is decided inside one, so it must
    exist): the open one when it is his, else a new one of his own. One that is gone, or not
    his, is never used and never loses the press."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        return _error(503, "unavailable", NOT_DONE)
    if session_id:
        found = await store.get(session_id)
        if found is not None and found.user_id == uid:
            return session_id
    made = Session(user_id=uid, metadata={"persona": PERSONA_VERSION})
    await store.save(made)
    return made.id


def _no(message: str) -> dict[str, Any]:
    return {"message": message, "refused": True}


def _refusal(res: GatewayResult) -> JSONResponse:
    """A call that did not run, in JARVIS's own words (the gateway's error text is never sent:
    it may carry a connector's message)."""
    if res.outcome is GatewayOutcome.DENIED:
        return _error(403, "not_allowed", NOT_ALLOWED)
    why = res.error or ""
    if "no events of that batch" in why:
        return _error(409, "not_done", GONE)
    if "Google is not linked" in why or "GoogleNotConnected" in why:
        return _error(409, "not_linked", NOT_LINKED)
    log.warning("a plan action was not done", extra={"outcome": res.outcome.value})
    return _error(409, "not_done", NOT_DONE)


async def _run(
    request: Request,
    uid: str,
    name: str,
    args: dict[str, Any],
    session_id: str | None,
    *,
    card: bool,
    untrusted: bool = False,
) -> JSONResponse:
    """One tool call through the gateway. `card`: it will leave an approval card, which waits in
    a real conversation (the open one, else a new one). A call that needs no card runs without
    one; if his row turns it into a card after all, it is proposed again in a conversation."""
    gateway = _gate(request, uid)
    if isinstance(gateway, JSONResponse):
        return gateway
    sid: str | None = None
    if card:
        found = await _conversation(request, uid, session_id)
        if isinstance(found, JSONResponse):
            return found
        sid = found
    call = ToolCall(id=f"plan-{uuid.uuid4().hex[:8]}", name=name, arguments=args)

    async def execute(scope: str) -> GatewayResult:
        with context_trust(untrusted=untrusted):
            return await gateway.execute(call, scope=f"{uid}:{scope}")

    res = await execute(sid or PLAIN_SCOPE)
    if res.pending is not None and sid is None:
        await gateway.gate.cancel(res.pending.id)
        made = await _conversation(request, uid, session_id)
        if isinstance(made, JSONResponse):
            return made
        sid = made
        res = await execute(sid)
    return _said(res, sid)


def _said(res: GatewayResult, sid: str | None) -> JSONResponse:
    if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and res.pending is not None:
        head = res.pending.summary.splitlines()[0]
        return _answer(200, {"pending": True, "session_id": sid, "message": head})
    if res.outcome is not GatewayOutcome.EXECUTED:
        return _refusal(res)
    result = res.result if isinstance(res.result, dict) else {}
    return _answer(
        200,
        {
            "pending": "approval" in result,
            "session_id": sid,
            "message": str(result.get("message") or "Done, Sir."),
            "refused": bool(result.get("refused")),
        },
    )


@router.get("")
async def status(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    part = part_of(request)
    body: dict[str, Any] = {
        "part": PART,
        "ready": part.ready if part is not None else NOT_BUILT,
        "plans": [],
        "waiting": [],
    }
    svc = _service(request)
    if svc is None:
        return _answer(200, body)
    tz = _zone(request.app.state.settings.user_timezone)
    try:
        book, waiting = await svc.book(uid), await svc.waiting(uid)
    except PlansUnreadable as exc:
        return _answer(200, {**body, "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - the panel says so; never a 500
        log.warning("plans view failed", extra={"error": type(exc).__name__})
        return _answer(200, {**body, "detail": NOT_DONE})
    body["plans"] = [
        {
            "id": p.id,
            "name": "" if p.outside else p.name,  # a name a file gave is not repeated
            "sessions": p.total,
            "done": sum(s.state == "done" for s in p.sessions),
            "skipped": sum(s.state == "skipped" for s in p.sessions),
            "replan": cards.skipped_words(p),
        }
        for p in book.plans
    ]
    body["waiting"] = [
        {
            "plan": w.plan.id,
            "session": w.session.n,
            "of": w.plan.total,
            "start": w.session.start.isoformat(),
            "text": cards.waiting_words(w.plan, w.session, tz),
        }
        for w in waiting[:10]
    ]
    return _answer(200, body)


@router.post("/answer", response_model=None)
async def answer(
    request: Request, body: AnswerBody, uid: str = Depends(current_user)
) -> JSONResponse:
    if _service(request) is None:
        return _error(404, "plans_off", OFF)
    args: dict[str, Any] = {"answer": body.answer}
    if body.series:
        args["series"] = body.series
    if body.session is not None:
        args["session"] = body.session
    skipped = body.answer == "skipped"  # a skip leaves the re-plan card
    return await _run(request, uid, CHECKIN, args, body.session_id, card=skipped)


@router.post("/replan", response_model=None)
async def replan(
    request: Request, body: ReplanBody, uid: str = Depends(current_user)
) -> JSONResponse:
    svc = _service(request)
    if svc is None:
        return _error(404, "plans_off", OFF)
    try:  # named the way the "skipped" answer names it, so a second press finds the same card
        found = await svc.skipped(uid, body.series, body.session)
    except (LookupError, PlansUnreadable) as exc:
        return _answer(200, {"pending": False, "session_id": None, **_no(str(exc))})
    args = {"series": found.plan.id, "session": found.session.n}
    return await _run(request, uid, RESCHEDULE, args, body.session_id, card=True)


@router.post("/batches/retry", response_model=None)
async def retry(
    request: Request, body: RetryBody, uid: str = Depends(current_user)
) -> JSONResponse:
    events = [
        {
            k: v
            for k, v in e.model_dump(exclude={"why"}).items()
            if v not in ("", None)  # the tool takes only what an event has
        }
        for e in body.events
    ]
    args: dict[str, Any] = {"events": events, "batch": body.batch}
    if body.name:
        args["series"] = {"name": body.name}
    # the list comes back from the browser: JARVIS can't know whose words it holds, so the card
    # is made as in a round that read other people's text (the events carry the outside mark)
    return await _run(request, uid, CREATE, args, body.session_id, card=True, untrusted=True)


async def _tidy(gateway: Gateway, uid: str, batch: str, keep: str = "") -> None:
    """After his own press removed a batch, a card that still asks to remove it is pointless:
    withdrawn (his cards only). Never raises."""
    try:
        for card in await gateway.pending():
            mine = (card.scope or "").partition(":")[0] == uid
            if mine and card.tool == UNDO and card.arguments.get("batch") == batch:
                if card.id != keep:
                    await gateway.gate.cancel(card.id)
    except Exception as exc:  # noqa: BLE001 - tidying only
        log.warning("old undo cards not withdrawn", extra={"error": type(exc).__name__})


@router.post("/batches/{batch}/undo", response_model=None)
async def undo(request: Request, batch: str, uid: str = Depends(current_user)) -> JSONResponse:
    if not BATCH_ID.fullmatch(batch):
        return _error(422, "invalid", "That is not a batch id.")
    gateway = _gate(request, uid)
    if isinstance(gateway, JSONResponse):
        return gateway
    call = ToolCall(id=f"undo-{uuid.uuid4().hex[:8]}", name=UNDO, arguments={"batch": batch})
    scope = f"{uid}:{PLAIN_SCOPE}"  # the press's own card: never one a conversation is showing
    with context_trust(untrusted=False):  # his own press on his own reply card
        asked = await gateway.execute(call, scope=scope)
    if asked.outcome is not GatewayOutcome.AWAITING_CONFIRMATION or asked.pending is None:
        return _refusal(asked)
    card = asked.pending.id
    try:
        with approved_via(UNDO_VIA), presenting_proof(None):
            done = await gateway.execute(call, confirmation_id=card, scope=scope)
    except Exception as exc:  # noqa: BLE001 - the approval guard refused, or the store is down
        log.warning("Undo all was not run", extra={"error": type(exc).__name__})
        await gateway.gate.cancel(card)  # never leave the press's own card behind
        return _error(409, "not_done", NOT_DONE)
    if done.outcome is not GatewayOutcome.EXECUTED:
        if done.pending is not None:  # it changed while it was looked at: nothing ran
            await gateway.gate.cancel(done.pending.id)
        return _refusal(done)
    result = done.result if isinstance(done.result, dict) else {}
    if not result.get("unavailable"):
        await _tidy(gateway, uid, batch)
    return _answer(
        200,
        {
            "message": str(result.get("message") or "Done, Sir."),
            "removed": int(result.get("removed") or 0),
            "kept": int(result.get("kept") or 0),
            "failed": int(result.get("failed") or 0),
            "unavailable": bool(result.get("unavailable")),
        },
    )


__all__ = ["PREFIX", "part_of", "router"]
