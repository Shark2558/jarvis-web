# src/jarvis/api/helpers_today.py
"""R11 Part A's routes, under `/v1/helpers/today` (docs/plans/r11-free-helpers.md D2, D7-D9, D19).
Owner-only (`require_auth` + `current_user`; cookie writes need `X-Requested-With: JARVIS`),
`no-store`, changes rate-limited per owner by I0's limiter. They read Part A's services from
`app.state.r11_parts["today"].services` per request; 404 {error: "helpers_off"} when it is off.

GET    /v1/helpers/today                   the Today tab: {bills: {available, note, items, prefs},
                                           birthdays: {on, at, state, note, today, soon},
                                           top, pending: [{source, items}], not_checked}
POST   /v1/helpers/today/bills             his own entry {label, payee?, amount?, day? | on?,
                                           every_months?, leads?, last4?} -> 201 {bill}
POST   /v1/helpers/today/bills/{id}/paid   "I paid" (its current due date)
DELETE /v1/helpers/today/bills/{id}        remove one bill (the console confirms first)
PUT    /v1/helpers/today/prefs             {bills_at?, birthdays_on?, birthday_at?}
POST   /v1/helpers/today/bills/{id}/payee  {upi, payee?, session_id} -> the R3 `bill_payee_set`
                                           card through the gateway (202 awaiting)
POST   /v1/helpers/today/bills/{id}/pay    {amount?, session_id} -> the R3 `bill_pay_prepare`
                                           card through the gateway (202 awaiting)
POST   /v1/helpers/today/bills/{id}/payment  the approved payment, ONCE, within 10 minutes:
                                           {link, qr, upi, payee, amount, note}; 404 not_ready

A UPI ID is never written by a route: setting one and preparing a payment are R3 tool calls
through the gateway (policy, the passkey rule, the audit), proposed in his open conversation
(`session_id`, checked to be his) so he approves them in Approvals; with no conversation:
409 no_conversation. The payment's link and QR are made for this one answer and never stored.
Errors: 422 {error: "invalid", detail} in plain words; 503 {error: "unavailable"}.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.helpers.ports import HelperPart
from jarvis.helpers.today.bills import BillsService
from jarvis.helpers.today.models import BillRefused
from jarvis.helpers.today.store import BillsOff
from jarvis.helpers.today.tools import UNUSABLE
from jarvis.helpers.today.views import today_view
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.tools.budget import turn_budget
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import context_trust

log = get_logger(__name__)

PREFIX = "/v1/helpers/today"
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])
NO_STORE = {"Cache-Control": "no-store"}
SESSION = r"^[A-Za-z0-9_-]{1,64}$"
NO_CONVERSATION = (
    "Open a conversation in Chat first, Sir: the approval waits there. Or say “pay the {label} "
    "bill” in the chat."
)
AWAITING = "Approve it in Approvals, Sir. JARVIS never pays: you finish it in your UPI app."


class BillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=200)
    payee: str = Field(default="", max_length=200)
    amount: str | None = Field(default=None, max_length=30)
    day: StrictInt | None = None
    on: str | None = Field(default=None, max_length=10)
    every_months: StrictInt = 1
    leads: list[StrictInt] | None = Field(default=None, max_length=4)
    last4: str = Field(default="", max_length=10)


class PrefsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bills_at: str | None = Field(default=None, max_length=5)
    birthdays_on: StrictBool | None = None
    birthday_at: str | None = Field(default=None, max_length=5)


class PayeeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upi: str = Field(max_length=330)
    payee: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, pattern=SESSION)


class PayBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: str | None = Field(default=None, max_length=30)
    session_id: str | None = Field(default=None, pattern=SESSION)


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _part(request: Request) -> HelperPart | None:
    parts: dict[str, HelperPart] = getattr(request.app.state, "r11_parts", None) or {}
    part = parts.get("today")
    return part if part is not None and "bills" in part.services else None


def _off(request: Request) -> JSONResponse:
    why = getattr(request.app.state, "helpers_off", None) or "off"
    return _answer(404, {"error": "helpers_off", "detail": f"The helpers are off ({why})."})


def _now(request: Request) -> datetime:
    return request.app.state.helpers_now()  # type: ignore[no-any-return]


def _limited(request: Request, uid: str) -> JSONResponse | None:
    limiter = getattr(request.app.state, "helpers_limit", None)
    if limiter is not None and not limiter.allow(uid)[0]:
        return _answer(429, {"error": "rate_limited", "detail": "Too many changes; wait a moment."})
    return None


async def _change(request: Request, uid: str, work: Any, status: int = 200) -> JSONResponse:
    """Run one change; then the whole view (or the change's own answer)."""
    part = _part(request)
    if part is None:
        return _off(request)
    if (refused := _limited(request, uid)) is not None:
        return refused
    try:
        got = await work(part.services["bills"])
    except BillsOff as exc:
        return _answer(409, {"error": "bills_off", "detail": str(exc)})
    except BillRefused as exc:
        return _answer(422, {"error": "invalid", "detail": str(exc)})
    except ValueError:  # a model's own check: never echo what was sent
        return _answer(422, {"error": "invalid", "detail": UNUSABLE})
    except Exception as exc:  # noqa: BLE001 - the store; plain words, the class in the log
        log.warning("today change failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't save that just now."})
    return _answer(status, got if isinstance(got, dict) else await _view_body(request, part, uid))


async def _view_body(request: Request, part: HelperPart, uid: str) -> dict[str, Any]:
    return await today_view(part.services, uid, _now(request))


@router.get("", response_model=None)
async def today_get(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    part = _part(request)
    if part is None:
        return _off(request)
    try:
        return _answer(200, await _view_body(request, part, uid))
    except Exception as exc:  # noqa: BLE001 - plain words, the class in the log
        log.warning("today view failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't read Today just now."})


@router.post("/bills", response_model=None)
async def bill_add(
    request: Request, body: BillBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: BillsService) -> Any:
        await svc.add(uid, **body.model_dump())

    return await _change(request, uid, work, status=201)


@router.post("/bills/{bill_id}/paid", response_model=None)
async def bill_paid(
    request: Request, bill_id: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: BillsService) -> Any:
        await svc.mark_paid(uid, bill_id)

    return await _change(request, uid, work)


@router.delete("/bills/{bill_id}", response_model=None)
async def bill_remove(
    request: Request, bill_id: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: BillsService) -> Any:
        if not await svc.remove(uid, bill_id):
            raise BillRefused("No bill by that name, Sir.")

    return await _change(request, uid, work)


@router.put("/prefs", response_model=None)
async def prefs_put(
    request: Request, body: PrefsBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: BillsService) -> Any:
        await svc.set_prefs(uid, **body.model_dump(exclude_none=True))

    return await _change(request, uid, work)


async def _own_session(request: Request, uid: str, session_id: str | None) -> bool:
    store = getattr(request.app.state, "store", None)
    if session_id is None or store is None:
        return False
    try:
        found = await store.get(session_id)
    except Exception as exc:  # noqa: BLE001 - unreadable: treat as no conversation
        log.warning("today: conversation unreadable", extra={"error": type(exc).__name__})
        return False
    return found is not None and getattr(found, "user_id", None) == uid


async def _card(request: Request, uid: str, session_id: str | None, call: ToolCall) -> JSONResponse:
    """Propose an R3 call through the gateway in his conversation; it waits in Approvals."""
    gateway = getattr(request.app.state, "gateway", None)
    if gateway is None:
        return _answer(503, {"error": "unavailable", "detail": "Tools are off on this server."})
    if not await _own_session(request, uid, session_id):
        label = str(call.arguments.get("bill", "")) or "this"
        return _answer(
            409, {"error": "no_conversation", "detail": NO_CONVERSATION.format(label=label)}
        )
    with turn_budget(), context_trust(untrusted=False, spoken=False, owner_text=None):
        res = await gateway.execute(call, scope=f"{uid}:{session_id}")
    if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and res.pending is not None:
        return _answer(
            202, {"status": "awaiting", "approval_id": res.pending.id, "detail": AWAITING}
        )
    if res.outcome is GatewayOutcome.DENIED:
        return _answer(403, {"error": "denied", "detail": "Switched off in your Permissions, Sir."})
    detail = (res.error or "That couldn't be done.").split(" (")[0][:200]
    return _answer(422, {"error": "invalid", "detail": detail})


async def _bill_ref(request: Request, uid: str, bill_id: str) -> str | None:
    part = _part(request)
    if part is None:
        return None
    try:
        return part.services["bills"].find(await part.services["bills"].book(uid), bill_id).id  # type: ignore[no-any-return]
    except (BillRefused, BillsOff):
        return None


@router.post("/bills/{bill_id}/payee", response_model=None)
async def bill_payee(
    request: Request, bill_id: str, body: PayeeBody, uid: str = Depends(current_user)
) -> JSONResponse:
    if _part(request) is None:
        return _off(request)
    if (refused := _limited(request, uid)) is not None:
        return refused
    if await _bill_ref(request, uid, bill_id) is None:
        return _answer(404, {"error": "not_found", "detail": "No bill by that name, Sir."})
    args: dict[str, Any] = {"bill": bill_id, "upi": body.upi}
    if body.payee is not None:
        args["payee"] = body.payee
    call = ToolCall(id=f"today-{uuid.uuid4().hex[:8]}", name="bill_payee_set", arguments=args)
    return await _card(request, uid, body.session_id, call)


@router.post("/bills/{bill_id}/pay", response_model=None)
async def bill_pay(
    request: Request, bill_id: str, body: PayBody, uid: str = Depends(current_user)
) -> JSONResponse:
    if _part(request) is None:
        return _off(request)
    if (refused := _limited(request, uid)) is not None:
        return refused
    if await _bill_ref(request, uid, bill_id) is None:
        return _answer(404, {"error": "not_found", "detail": "No bill by that name, Sir."})
    args: dict[str, Any] = {"bill": bill_id}
    if body.amount:
        args["amount"] = body.amount
    call = ToolCall(id=f"today-{uuid.uuid4().hex[:8]}", name="bill_pay_prepare", arguments=args)
    return await _card(request, uid, body.session_id, call)


@router.post("/bills/{bill_id}/payment", response_model=None)
async def bill_payment(
    request: Request, bill_id: str, uid: str = Depends(current_user)
) -> JSONResponse:
    part = _part(request)
    if part is None:
        return _off(request)
    if (refused := _limited(request, uid)) is not None:
        return refused
    try:
        shown = await part.services["bills"].payment(uid, bill_id)
    except (BillRefused, BillsOff):
        shown = None
    except Exception as exc:  # noqa: BLE001 - the store; plain words
        log.warning("today payment not shown", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't open it just now."})
    if shown is None:
        detail = "Nothing approved to show, Sir (or its 10 minutes are up). Tap Pay again."
        return _answer(404, {"error": "not_ready", "detail": detail})
    return _answer(
        200,
        {
            "link": shown.link,
            "qr": shown.qr,
            "upi": shown.upi,
            "payee": shown.payee,
            "amount": shown.amount,
            "note": shown.note,
        },
    )


__all__ = ["PREFIX", "router"]
