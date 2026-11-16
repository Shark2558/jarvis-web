# src/jarvis/api/wardrobe.py
"""R13 Part A's routes, under `/v1/wardrobe` (docs/plans/r13-wardrobe.md "The HTTP contract", D1,
D4, D7). Exactly the `jarvis.wardrobe.http` `ROUTES` rows of "catalog" and "any": each owner-only
(`require_auth`), `no-store`, limited per owner (30 changes and 60 reads a minute), answering
plain words. The picture and file routes live in `wardrobe/catalog/routes_files.py` (included
here: the wiring installs this one router).

    GET  /v1/wardrobe?private=1&after=   the view (pieces a page, counts, pairs, sets, places,
                                         labels, settings, rev); a private piece only on a tap
    GET  /v1/wardrobe/pieces/{id}        one piece and its history summary (LND-15)
    POST /v1/wardrobe/scan               events from the phone or a tap, one commit (D4: the
                                         device's clock corrected by `sent`, a stated day 12:00
                                         HIS time, a retry by its client id is applied once)
    GET  /v1/wardrobe/labels.svg?sheet=  24 QR labels, numbers and codes only; writes nothing
    POST /v1/wardrobe/labels             stick one of his labels on a piece (or free it)
    GET  /v1/wardrobe/pilot              e2e 8's counts, counts only
    POST /v1/wardrobe/tools/{tool}       the panel's changes through `gateway.execute` (D1): the
                                         same rows, cards and audit as the AI's call; a card
                                         waits in a conversation of his own
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.r13_status import ready_of
from jarvis.core.models import Session
from jarvis.core.prompts import PERSONA_VERSION
from jarvis.llm.base import ToolCall
from jarvis.tools.budget import turn_budget
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.taint import context_trust
from jarvis.wardrobe import http
from jarvis.wardrobe.catalog import labels as label_sheet
from jarvis.wardrobe.catalog.events import event
from jarvis.wardrobe.catalog.routes_common import (
    NO_STORE_HEADERS,
    desk_of,
    err,
    off,
    ok,
    refused,
    too_many,
)
from jarvis.wardrobe.catalog.routes_files import router as files_router
from jarvis.wardrobe.model import PIECE_ID, Event, WardrobeView
from jarvis.wardrobe.ports import TOOL_OWNER, Commit, Committed, Refused
from jarvis.wardrobe.states import EVENT_KINDS

router = APIRouter(dependencies=[Depends(require_auth)])
router.routes.extend(files_router.routes)  # one router (an included one is lazy here)
NOT_IN = "That piece isn't in your wardrobe."
MERGED = "That piece was merged into another: refresh the list and scan again."
# what a scan may record; registering, merging, archiving and corrections go through the tools
SCAN_KINDS = frozenset(EVENT_KINDS) - {"registered", "merged", "corrected", "archived", "restored"}
PLAIN_SCOPE = "wardrobe"


# ---- reads ---------------------------------------------------------------------------------------
@router.get("/v1/wardrobe", include_in_schema=False)
async def wardrobe(
    request: Request, private: int = 0, after: str = "", uid: str = Depends(current_user)
) -> JSONResponse:
    if (busy := too_many(request, "wardrobe", uid, change=False)) is not None:
        return busy
    if (desk := desk_of(request)) is None:
        return off(request)
    try:
        view = await desk.store.view(uid)
    except Exception as exc:  # noqa: BLE001
        return refused(exc, status=503)
    shown = desk.views.wardrobe_view(
        view, ready=_ready(request), show_private=bool(private), after=after or None
    )
    return ok(shown)


def _ready(request: Request) -> str:
    return ready_of(request, "catalog")


@router.get("/v1/wardrobe/pieces/{id}", include_in_schema=False)
async def piece(
    request: Request,
    id: str,
    uid: str = Depends(current_user),  # noqa: A002 - the contract's name
) -> JSONResponse:
    pid = id
    if (busy := too_many(request, "piece", uid, change=False)) is not None:
        return busy
    desk = desk_of(request)
    if desk is None or not PIECE_ID.match(pid):
        return err(404, NOT_IN)
    try:
        view = await desk.store.view(uid)
        p = view.piece(pid)
        if p is None:
            return err(404, NOT_IN)
        history = await desk.merge.history(uid, pid)
        return ok(desk.views.detail(view, p, history, await desk.ctx.zone(uid)))
    except Exception as exc:  # noqa: BLE001
        return refused(exc, status=404, down=404)


# ---- the scan (D4) -------------------------------------------------------------------------------
async def _at(desk: Any, uid: str, e: http.EventIn, now: datetime) -> tuple[datetime, Any]:
    """(its time, the device's send clock): a device's capture with `sent`; a time he states;
    a stated day at 12:00 HIS local time, or now while that noon is still ahead (a "today" in
    the morning is never refused as a time ahead, M5); else now."""
    if e.at is not None:
        return e.at, e.sent
    if e.stated_at is not None:
        return e.stated_at, None
    if e.day is not None:
        noon = datetime.combine(e.day, time(12, 0), tzinfo=await desk.ctx.zone(uid))
        return min(noon, now), None
    return now, None


async def _events(desk: Any, uid: str, body: http.ScanRequest, view: WardrobeView) -> list[Event]:
    now, out = desk.store.now(), []
    for e in body.events:
        if e.kind not in SCAN_KINDS:
            raise Refused("That change is made with its own button: archive, restore or merge.")
        p = view.piece(e.piece)
        if p is None:
            raise Refused(NOT_IN)
        if p.merged_into is not None:
            raise Refused(MERGED)
        at, sent = await _at(desk, uid, e, now)
        # a QR read counts only for a piece wearing one of his labels (D7)
        verified = e.verified and (e.how != "qr" or p.label_code is not None)
        fields = {"client_id": e.client_id, "sent": sent, "source": e.source, "via": e.via,
                  "verified": verified, "evidence": {"how": e.how, "score": e.score}, "to": e.to,
                  "place": e.place, "load": e.load, "batch": e.batch, "due": e.due,
                  "plan": e.plan, "rev_seen": body.rev_seen, "note": e.note}  # fmt: skip
        out.append(event(e.piece, e.kind, at, **fields))
    return out


def _scan_reply(desk: Any, got: Committed, events: list[Event], ready: str) -> http.ScanReply:
    by_client = {e.id: e.client_id or e.id for e in events}
    marks = {by_client.get(k, k): m for k, m in got.marks.items()}
    dup = sum(m in ("duplicate", "known") for m in got.marks.values())
    review = len(got.needed)
    words = "Already done." if got.already else "Saved."
    if review:
        words = f"Saved; {review} to check in Helpers, Wardrobe."
    view = (
        desk.views.wardrobe_view(got.view, ready=ready, show_private=False) if got.already else None
    )
    return http.ScanReply(applied=sum(m == "applied" for m in got.marks.values()), duplicates=dup,
                          review=review, already_done=got.already, marks=marks, message=words,
                          view=view)  # fmt: skip


@router.post("/v1/wardrobe/scan", include_in_schema=False)
async def scan(
    request: Request, body: http.ScanRequest, uid: str = Depends(current_user)
) -> JSONResponse:
    if (busy := too_many(request, "scan", uid, change=True)) is not None:
        return busy
    if (desk := desk_of(request)) is None:
        return off(request)
    made: list[Event] = []

    async def fn(view: WardrobeView, tx: Any) -> Commit:
        made[:] = await _events(desk, uid, body, view)
        return Commit(events=tuple(made))

    try:
        got = await desk.store.transact(uid, fn)
    except Refused as exc:
        return err(409 if str(exc) == MERGED else 422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return refused(exc)
    return ok(_scan_reply(desk, got, made, _ready(request)))


# ---- labels and the pilot ------------------------------------------------------------------------
@router.get("/v1/wardrobe/labels.svg", include_in_schema=False)
async def labels_svg(
    request: Request, sheet: int = 1, uid: str = Depends(current_user)
) -> Response:
    if (busy := too_many(request, "labels", uid, change=False)) is not None:
        return busy
    desk = desk_of(request)
    found: tuple[Any, ...] = ()
    if desk is not None:
        try:
            found = await desk.labels.sheet(uid, max(1, sheet))
        except Exception:  # noqa: BLE001 - an empty page, never an error page
            found = ()
    heads = NO_STORE_HEADERS | {"Content-Security-Policy": "default-src 'none'",
                                "X-Content-Type-Options": "nosniff"}  # fmt: skip
    heads["Content-Disposition"] = f'attachment; filename="jarvis-labels-{max(1, sheet)}.svg"'
    return Response(label_sheet.svg(found), media_type="image/svg+xml", headers=heads)


@router.post("/v1/wardrobe/labels", include_in_schema=False)
async def assign_label(
    request: Request, body: http.LabelAssign, uid: str = Depends(current_user)
) -> JSONResponse:
    if (busy := too_many(request, "labels", uid, change=True)) is not None:
        return busy
    if (desk := desk_of(request)) is None:
        return off(request, 422)
    try:
        lb = await desk.labels.assign(uid, body.code, body.piece)
    except Refused as exc:
        return err(404 if str(exc) == NOT_IN else 422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return refused(exc, down=422)
    return ok(http.LabelView(code=lb.code, number=lb.number, piece=lb.piece))


@router.get("/v1/wardrobe/pilot", include_in_schema=False)
async def pilot(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    if (busy := too_many(request, "pilot", uid, change=False)) is not None:
        return busy
    desk, zero = desk_of(request), dict.fromkeys(http.Pilot.model_fields, 0)
    if desk is None:
        return ok(http.Pilot(**zero))
    try:
        return ok(await desk.pilot.counts(uid))
    except Exception:  # noqa: BLE001 - counts only; none readable: zeros
        return ok(http.Pilot(**zero))


# ---- the panel's changes through the gateway (D1) ------------------------------------------------
async def _conversation(request: Request, uid: str) -> str | None:
    store = getattr(request.app.state, "store", None)
    if store is None:
        return None
    made = Session(user_id=uid, metadata={"persona": PERSONA_VERSION})
    await store.save(made)
    return str(made.id)


def _tool_reply(res: GatewayResult) -> JSONResponse:
    if res.outcome is GatewayOutcome.EXECUTED:
        result = res.result if isinstance(res.result, dict) else {"value": res.result}
        words = str(result.get("message") or result.get("status") or "Done.")
        return ok(http.ToolReply(status="executed", message=words, result=result))
    if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and res.pending is not None:
        return ok(http.ToolReply(status="needs_approval", message=res.pending.summary,
                                 approval_id=res.pending.id))  # fmt: skip
    if res.outcome is GatewayOutcome.DENIED:
        return ok(http.ToolReply(status="denied", message="Switched off in your Permissions."))
    words = (res.error or "That couldn't be done.").split(" (")[0][:200]
    return JSONResponse(http.ToolReply(status="error", message=words).model_dump(mode="json"),
                        status_code=422, headers=NO_STORE_HEADERS)  # fmt: skip


@router.post("/v1/wardrobe/tools/{tool}", include_in_schema=False)
async def tools(
    request: Request, tool: str, body: http.ToolCall, uid: str = Depends(current_user)
) -> JSONResponse:
    if (busy := too_many(request, "tools", uid, change=True)) is not None:
        return busy
    gateway: Gateway | None = getattr(request.app.state, "gateway", None)
    if tool not in TOOL_OWNER or gateway is None or gateway.registry.get(tool) is None:
        return err(404, "That wardrobe action isn't available on this server.")
    call = ToolCall(
        id=f"wardrobe-{uuid.uuid4().hex[:8]}", name=tool, arguments=dict(body.arguments)
    )

    async def run(scope: str) -> GatewayResult:
        assert gateway is not None
        with turn_budget(), context_trust(untrusted=False, spoken=False, owner_text=None):
            return await gateway.execute(call, scope=f"{uid}:{scope}")

    res = await run(PLAIN_SCOPE)
    if res.pending is not None:  # a card waits in a real conversation of his
        await gateway.gate.cancel(res.pending.id)
        sid = await _conversation(request, uid)
        if sid is None:
            return err(422, "That needs your OK, and there is no conversation to ask it in.")
        res = await run(sid)
    return _tool_reply(res)


__all__ = ["SCAN_KINDS", "router"]
