# src/jarvis/api/tryon.py
"""R13.1 Part A's routes, under `/v1/tryon` (docs/plans/r13-1-try-on.md "The HTTP contract").

Exactly the `jarvis.wardrobe.tryon.http.ROUTES` rows of part "tryon":

    GET    /v1/tryon                 the figure's release and files, his measurements (current,
                                     draft, earlier; typed or estimated), the ranges, his figure
                                     choices, saved comparisons (re-checked), the words
    PUT    /v1/tryon/body            a draft from what he typed (range words for a value outside)
    POST   /v1/tryon/body/use        "Use these measurements" (?at= the draft he saw: 409 if not)
    DELETE /v1/tryon/body/draft      "Keep the current"
    GET    /v1/tryon/look            ?plan= | ?day=today|tomorrow&alt=0|1|2 | ?pieces=slot:wi_...
                                     (row 388's card; &plan=, &day=, &code= may come with it),
                                     &private=1 for his own "Show private basics"
    PUT    /v1/tryon/assets/{piece}  his figure choice for a piece
    POST   /v1/tryon/confirm         the fresh check (409 in words), then ONE `outfit_plan` lock
                                     through `api.wardrobe.run_panel_tool` (at most one card)
    GET/POST /v1/tryon/saved, GET/DELETE /v1/tryon/saved/{id}   saved comparisons (<= 10)

Each is owner-only (`require_auth`; cookie writes need `X-Requested-With`), `no-store`, limited
per owner (`r13_status.limited`: 30 changes, 60 reads a minute), and answers every refusal as
`http.Refusal` {"error", "detail"} (the console branches on `err.code`); a request body is read
and checked here, so even a malformed one is a `Refusal`. The part's service is read per request
from `app.state.r13_parts["tryon"]`. A measurement change is recorded with `record_change`: the
action and the field names only, never a number. OPS-05 has no route: it is Privacy's delete.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from jarvis.api import tryon_assets
from jarvis.api.auth import require_auth
from jarvis.api.body import read_capped
from jarvis.api.identity import current_user
from jarvis.api.r13_status import NO_STORE, limited, part_of
from jarvis.api.settings_audit import record_change
from jarvis.api.wardrobe import PanelRun, panel_reply, run_panel_tool
from jarvis.logging import get_logger
from jarvis.tools.gateway import GatewayOutcome
from jarvis.wardrobe.model import PIECE_ID
from jarvis.wardrobe.tryon import assets, confirm, looks, saved, store, versions
from jarvis.wardrobe.tryon.http import AssetChoice, BodyIn, ConfirmIn, Refusal, SavedIn
from jarvis.wardrobe.tryon.model import SAVED_ID
from jarvis.wardrobe.tryon.part import TryonService

log = get_logger(__name__)
router = APIRouter(dependencies=[Depends(require_auth)])
M = TypeVar("M", bound=BaseModel)
Act = Callable[[TryonService], Awaitable[Any]]
NOT_SET_UP = "Try-on isn't available on this server."
BAD = "That request can't be read."
DOWN = "That couldn't be done just now. Try again in a minute."
DOWN_STATUS = 503  # Off, unreadable or storage trouble, on every route (the contract's rows)
INTERNAL = "Something went wrong inside JARVIS. Try again later."
UNREADABLE = (  # no cause named: a newer release's data reads the same (review A-1 F10)
    "Your try-on data can't be opened on this server. Nothing was changed; you can delete it in "
    "Privacy to start again."
)
ALTS = ("0", "1", "2")
QUERY_MAX = 1000  # a reply card's 12 slots of `slot:wi_...` fit with room to spare
BODY_MAX = 16_384  # A's largest body (two saved looks of 12 slots) is under 3 KB (review A-1 F8)
TOO_LARGE = "That request is too big."
_CODES: tuple[tuple[type[Exception], int, str], ...] = (
    (versions.OutOfRange, 422, "out_of_range"),
    (versions.NothingTyped, 422, "nothing_typed"),
    (versions.NotWhole, 422, "not_whole"),
    (versions.NoDraft, 404, "no_draft"),
    (versions.Changed, 409, "changed"),
    (assets.NotIn, 404, "not_in"),
    (assets.Refused, 422, "wrong_shape"),
    (looks.NoLook, 404, "gone"),
    (looks.BadDay, 422, "bad_day"),
    (looks.NotPieces, 422, "not_a_piece"),
    (confirm.Draft, 409, "draft"),
    (confirm.LeftOut, 409, "left_out"),
    (confirm.BadSlots, 422, "not_a_look"),
    (saved.SavedFull, 409, "too_many"),
    (saved.SavedGone, 404, "gone"),
    (store.TooBig, 422, "full"),
)


class _Bad(ValueError):
    """A request that can't be read: a 422 `bad_request`."""


class _TooLarge(ValueError):
    """A body past `BODY_MAX`: a 413 `too_large`, refused before it is read as JSON."""


def no(status: int, code: str, words: str) -> JSONResponse:
    body = Refusal(error=code, detail=words[:300])
    return JSONResponse(body.model_dump(), status_code=status, headers=NO_STORE)


def _ok(model: BaseModel) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers=NO_STORE)


def refused(exc: Exception, route: str = "") -> JSONResponse:
    """A refusal in its own words; Off and storage trouble are 503 on every route (review A-1
    F5); any other error is a bug: logged at ERROR with where it happened and answered 500
    `internal` (F3). Never the error's message or a trace: those can carry his numbers."""
    if isinstance(exc, _Bad):
        return no(422, "bad_request", BAD)
    if isinstance(exc, _TooLarge):
        return no(413, "too_large", TOO_LARGE)
    for kind, status, code in _CODES:
        if isinstance(exc, kind):
            return no(status, code, str(exc))
    if isinstance(exc, (looks.StylingOff, store.Off)):
        return no(DOWN_STATUS, "off", str(exc) or NOT_SET_UP)
    if isinstance(exc, store.Unreadable):
        return no(DOWN_STATUS, "unreadable", UNREADABLE)
    extra = {"route": route, "error": type(exc).__name__, "at": store.where(exc)}
    if store.storage_trouble(exc):
        log.warning("try-on route: storage trouble", extra=extra)
        return no(DOWN_STATUS, "unavailable", DOWN)
    log.error("try-on route failed", extra=extra)
    return no(500, "internal", INTERNAL)


def _service(request: Request) -> TryonService | str:
    """The part's service, or the words of why there is none (its own "Off: ..." first)."""
    part = part_of(request, "tryon")
    svc = part.services.get("tryon_looks") if part is not None else None
    if isinstance(svc, TryonService):
        return svc
    ready = part.ready if part is not None else ""
    return ready if ready.startswith("Off") else NOT_SET_UP


async def _run(request: Request, uid: str, route: str, act: Act, *, change: bool) -> JSONResponse:
    key = f"tryon_{route}_{'change' if change else 'read'}"  # each allowance its own bucket
    if (busy := limited(request, key, uid, change=change)) is not None:
        return busy
    svc = _service(request)
    if isinstance(svc, str):
        return no(DOWN_STATUS, "off", svc)
    try:
        got = await act(svc)
    except Exception as exc:  # noqa: BLE001 - every refusal in words, never a stack
        return refused(exc, route)
    return got if isinstance(got, JSONResponse) else _ok(got)


async def body_of(
    request: Request, model: type[M], check: Callable[[object], None] | None = None
) -> M:
    """The request's JSON (at most `BODY_MAX` bytes, else `_TooLarge` before it is parsed),
    `check`ed as sent, then against its contract model (else `_Bad`)."""
    raw = await read_capped(request, BODY_MAX, too_large=_TooLarge)
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):  # JSONDecodeError is a ValueError
        raise _Bad from None  # never chained: his values stay out of any trace
    if check is not None:
        check(data)  # its own refusal in words (a measurement that isn't whole centimetres)
    try:
        return model.model_validate(data)
    except (ValueError, ValidationError, RecursionError):
        raise _Bad from None


def _files() -> tuple[str, ...]:
    """The figure's files that pass the mannequin manifest's check (body first)."""
    try:  # on the loop, as the mannequin route reads it (one cache, never two threads)
        good = tryon_assets.mannequin_files(tryon_assets.RELEASE)
    except Exception as exc:  # noqa: BLE001 - no files: the engine falls back to the list
        log.warning("mannequin manifest unreadable", extra={"error": type(exc).__name__})
        return ()
    glb = sorted(n for n in good if n.endswith(".glb"))
    return tuple(sorted(glb, key=lambda n: n != "body.glb"))


# ---- the figure and his measurements (D4) ------------------------------------------------------
@router.get("/v1/tryon", include_in_schema=False)
async def tryon(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        return await svc.tryon_view(uid, release=tryon_assets.RELEASE, files=_files())

    return await _run(request, uid, "view", act, change=False)


async def _audit(request: Request, action: str, fields: list[str]) -> None:
    detail = "Try-on measurements changed"
    args = {"action": action, "fields": fields}  # names only: the chain keeps their hash
    await record_change(request, agent="tryon", tool="tryon_body", args=args, detail=detail)


@router.put("/v1/tryon/body", include_in_schema=False)
async def put_body(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        typed = (await body_of(request, BodyIn, versions.whole_cm)).model_dump()
        got = await svc.put_body(uid, typed)
        await _audit(request, "draft", sorted(k for k, v in typed.items() if v is not None))
        return got

    return await _run(request, uid, "body", act, change=True)


def _seen(raw: str | None) -> datetime | None:
    """`?at=`: the draft's `at` as he was shown it (D's console sends it back), else None."""
    if raw is None:
        return None
    try:
        at = datetime.fromisoformat(raw) if len(raw) <= 40 else None
    except ValueError:
        at = None
    if at is None or at.tzinfo is None:
        raise _Bad
    return at


@router.post("/v1/tryon/body/use", include_in_schema=False)
async def use_body(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        got = await svc.use_body(uid, _seen(request.query_params.get("at")))
        await _audit(request, "use", [])
        return got

    return await _run(request, uid, "body", act, change=True)


@router.delete("/v1/tryon/body/draft", include_in_schema=False)
async def drop_draft(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        got = await svc.drop_draft(uid)
        await _audit(request, "keep_current", [])
        return got

    return await _run(request, uid, "body", act, change=True)


# ---- the look (D5-D7, D21) ---------------------------------------------------------------------
def _look_args(q: dict[str, str]) -> tuple[int, bool]:
    if any(len(v) > QUERY_MAX for v in q.values()) or q.get("alt", "0") not in ALTS:
        raise _Bad
    return int(q.get("alt", "0")), q.get("private", "0") == "1"


@router.get("/v1/tryon/look", include_in_schema=False)
async def look(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    q = dict(request.query_params)

    async def act(svc: TryonService) -> Any:
        alt, private = _look_args(q)
        if "pieces" in q:
            return await svc.looks.for_pieces(
                uid, q["pieces"], plan=q.get("plan") or None, day=q.get("day") or None,
                code=q.get("code") or None, private=private,
            )  # fmt: skip
        if q.get("plan"):
            return await svc.looks.for_plan(uid, q["plan"], alt, private)
        return await svc.looks.for_day(uid, q.get("day") or "today", alt, private)

    return await _run(request, uid, "look", act, change=False)


# ---- figure choices (AVT-05) -------------------------------------------------------------------
@router.put("/v1/tryon/assets/{piece}", include_in_schema=False)
async def put_asset(request: Request, piece: str, uid: str = Depends(current_user)) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        if not PIECE_ID.match(piece):
            raise assets.NotIn(assets.NOT_IN)
        return await svc.choose(uid, piece, await body_of(request, AssetChoice))

    return await _run(request, uid, "assets", act, change=True)


# ---- "Use this look" (AVT-09, D7, D20) ---------------------------------------------------------
PANEL_CODES = {404: "unavailable", 422: "no_conversation"}


def _panel(run: PanelRun) -> JSONResponse:
    """R13's `ToolReply` for the one call (executed, a card, or denied); every refusal in the
    contract's shape, in R13's own words: the gateway's error, and `outfit_plan`'s own refusal
    (D20's race, "That plan changed meanwhile", ...), which R13 returns as an EXECUTED result
    and which must never read as done (review A-1 F1)."""
    if run.result is None:  # refused before any call
        status, words = run.refusal or (422, DOWN)
        return no(status, PANEL_CODES.get(status, "unavailable"), words)
    res = run.result
    if res.outcome is GatewayOutcome.EXECUTED and isinstance(res.result, dict):
        if res.result.get("refused"):
            return no(409, "refused", str(res.result.get("message") or DOWN))
    reply = panel_reply(run)
    if reply.status_code < 400:
        return reply
    words = str(json.loads(bytes(reply.body)).get("message") or DOWN)
    return no(reply.status_code, "tool_error", words)


@router.post("/v1/tryon/confirm", include_in_schema=False)
async def confirm_look(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        body = await body_of(request, ConfirmIn)

        async def call(args: dict[str, Any]) -> PanelRun:
            return await run_panel_tool(request, uid, "outfit_plan", args, body.session_id)

        return _panel(await svc.confirm(uid, body, call))

    return await _run(request, uid, "confirm", act, change=True)


# ---- saved comparisons (AVT-11) ----------------------------------------------------------------
_SAVED = re.compile(SAVED_ID)


def _saved_id(sid: str) -> str:
    if len(sid) > 16 or not _SAVED.fullmatch(sid):
        raise saved.SavedGone(saved.GONE)
    return sid


@router.get("/v1/tryon/saved", include_in_schema=False)
async def saved_list(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        return await svc.saved_list(uid)

    return await _run(request, uid, "saved", act, change=False)


@router.post("/v1/tryon/saved", include_in_schema=False)
async def save(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        return await svc.save(uid, await body_of(request, SavedIn))

    return await _run(request, uid, "saved", act, change=True)


@router.get("/v1/tryon/saved/{id}", include_in_schema=False)
async def saved_one(
    request: Request,
    id: str,  # noqa: A002 - the contract's name
    uid: str = Depends(current_user),
) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        return await svc.saved_one(uid, _saved_id(id))

    return await _run(request, uid, "saved", act, change=False)


@router.delete("/v1/tryon/saved/{id}", include_in_schema=False)
async def saved_drop(
    request: Request,
    id: str,  # noqa: A002 - the contract's name
    uid: str = Depends(current_user),
) -> JSONResponse:
    async def act(svc: TryonService) -> Any:
        return await svc.saved_drop(uid, _saved_id(id))

    return await _run(request, uid, "saved", act, change=True)


__all__ = ["body_of", "no", "refused", "router"]
