# src/jarvis/api/seeme.py
"""R13.1 Part C's routes, under `/v1/seeme` (docs/plans/r13-1-try-on.md "The HTTP contract"):
exactly the "seeme" rows of `wardrobe.tryon.http.ROUTES`, owner-only (`require_auth`, CSRF),
no-store, limited per owner (30 changes, 60 reads, 6 presses a minute), every refusal a `Refusal`. Console
rows pass a signed-in browser only (`auth.session_email`, `book_gate.console_only`'s rule), checked
FIRST, before any body is read. The work is the part's `seeme` service; bodies, pictures and his
photo never reach a log; owner changes are audited by ids only (`settings_audit.record_change`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from jarvis.api.auth import require_auth, session_email
from jarvis.api.body import BodyTooLarge, read_capped
from jarvis.api.identity import current_user
from jarvis.api.r13_status import NO_STORE, limited, part_of
from jarvis.api.settings_audit import record_change
from jarvis.logging import get_logger
from jarvis.wardrobe.model import PIECE_ID
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.tryon import http
from jarvis.wardrobe.tryon.model import PRESSES_A_MINUTE

log = get_logger(__name__)
router = APIRouter(dependencies=[Depends(require_auth)])
JPEG = "image/jpeg"
AGENT = "seeme"
JSON_MAX = 16 * 1024  # a JSON body of these routes is a few hundred bytes


def _ok(model: Any) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers=NO_STORE)


def _no(status: int, code: str, words: str) -> JSONResponse:
    body = http.Refusal(error=code, detail=words[:300])
    return JSONResponse(body.model_dump(), status_code=status, headers=NO_STORE)


def _console(request: Request) -> JSONResponse | None:
    if session_email(request, request.app.state.settings) is not None:
        return None
    return _no(403, "console_only", texts.CONSOLE_ONLY)


def _svc(request: Request) -> Any:
    part = part_of(request, "seeme")
    return part.services.get("seeme") if part is not None else None


def _off(request: Request) -> JSONResponse:
    part = part_of(request, "seeme")
    words = part.ready if part is not None else texts.OFF_PICTURES
    return _no(503, "not_configured", words)


async def _jpeg(request: Request, max_kb: int) -> bytes | JSONResponse:
    if request.headers.get("content-type", "").split(";")[0].strip() != JPEG:
        return _no(422, "not_jpeg", texts.NOT_JPEG)
    cap = max_kb * 1024
    try:
        return await read_capped(request, cap, too_large=lambda: BodyTooLarge(cap))
    except BodyTooLarge:
        return _no(413, "too_large", texts.TOO_LARGE)


async def _json(request: Request, model: type[BaseModel]) -> Any:
    """The body as `model`, read AFTER the console check (so a script never learns the shape)."""
    try:
        raw = await read_capped(request, JSON_MAX, too_large=lambda: BodyTooLarge(JSON_MAX))
        return model.model_validate_json(raw or b"{}")
    except BodyTooLarge:
        return _no(413, "too_large", texts.INVALID)
    except ValidationError:
        return _no(422, "invalid", texts.INVALID)


async def _run(fn: Any, *args: Any, **kw: Any) -> Any:
    """The service's answer, or its refusal; anything else is "can't just now" (logged by name)."""
    try:
        return await fn(*args, **kw)
    except SeeMeRefused as exc:
        return _no(exc.status, exc.code, exc.words)
    except Exception as exc:  # noqa: BLE001 - never a 500 with a body or a trace in it
        log.error("see it on me: a route failed", extra={"error": type(exc).__name__})
        return _no(503, "unavailable", texts.UNAVAILABLE_NOW)


def _start(
    request: Request, uid: str, name: str, *, change: bool, console: bool, per: int | None = None
) -> tuple[Any, Response | None]:
    """(the service, None) or (None, the refusal): console first, then the limit, then on."""
    if console and (refused := _console(request)) is not None:
        return None, refused
    if (no := limited(request, f"seeme_{name}", uid, change=change, per=per)) is not None:
        return None, no
    svc = _svc(request)
    return (svc, None) if svc is not None else (None, _off(request))


def _answer(got: Any) -> Response:
    return got if isinstance(got, Response) else _ok(got)


def _image(data: bytes, mime: str) -> Response:
    return Response(data, media_type=mime, headers=http.PICTURE_HEADERS)


# ---- the overview, his settings ------------------------------------------------------------------
@router.get("/v1/seeme", include_in_schema=False)
async def seeme(request: Request, uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "read", change=False, console=False)
    if no is not None:
        return no
    return _answer(await _run(svc.overview, uid))


@router.put("/v1/seeme/settings", include_in_schema=False)
async def settings(request: Request, uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "change", change=True, console=True)
    if no is not None:
        return no
    body = await _json(request, http.SeeMeSettingsIn)
    if isinstance(body, Response):
        return body
    got = await _run(
        svc.settings,
        uid,
        on=body.on,
        cap_inr=body.cap_inr,
        keep_days=body.keep_days,
        confirm_cost=body.confirm_cost,
    )
    if isinstance(got, Response):
        return got
    shown = body.model_dump(exclude_none=True)
    await record_change(
        request,
        agent=AGENT,
        tool="seeme_settings",
        args=shown,
        detail="See it on me settings changed",
    )
    return _ok(got)


# ---- his photo, his YES --------------------------------------------------------------------------
@router.post("/v1/seeme/photo", include_in_schema=False)
async def photo_in(request: Request, uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "change", change=True, console=True)
    if no is not None:
        return no
    body = await _jpeg(request, request.app.state.settings.tryon_photo_max_kb)
    if isinstance(body, Response):
        return body
    got = await _run(svc.save_photo, uid, body)
    if isinstance(got, Response):
        return got
    await record_change(
        request,
        agent=AGENT,
        tool="seeme_photo",
        args={"bytes": got.bytes},
        detail="his photo for See it on me kept",
    )
    return _ok(got)


@router.get("/v1/seeme/photo", include_in_schema=False)
async def photo_out(request: Request, uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "image", change=False, console=True)
    if no is not None:
        return no
    got = await _run(svc.photo, uid)
    if isinstance(got, Response):
        return got
    return _image(got, JPEG) if got is not None else _no(404, "no_photo", texts.NO_PHOTO)


@router.delete("/v1/seeme/photo", include_in_schema=False)
async def photo_drop(request: Request, uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "change", change=True, console=True)
    if no is not None:
        return no
    got = await _run(svc.delete_photo, uid)
    if isinstance(got, Response):
        return got
    await record_change(
        request,
        agent=AGENT,
        tool="seeme_photo_delete",
        args={"deleted": got},
        detail="his photo and his YES deleted",
    )
    return _ok(http.Deleted(deleted=bool(got), message=texts.PHOTO_GONE))


@router.post("/v1/seeme/consent", include_in_schema=False)
async def consent(request: Request, uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "change", change=True, console=True)
    if no is not None:
        return no
    body = await _json(request, http.ConsentIn)
    if isinstance(body, Response):
        return body
    got = await _run(svc.give_consent, uid, body.typed, body.template_version)
    if isinstance(got, Response):
        return got
    await record_change(
        request,
        agent=AGENT,
        tool="seeme_consent",
        args={"version": got.version},
        detail="his YES for See it on me",
    )
    return _ok(got)


# ---- a garment he is thinking of buying (D22) ----------------------------------------------------
@router.post("/v1/seeme/garments", include_in_schema=False)
async def garment_in(
    request: Request,
    type: str = "",
    colour: str = "",
    uid: str = Depends(current_user),  # noqa: A002
) -> Response:
    svc, no = _start(request, uid, "change", change=True, console=True)
    if no is not None:
        return no
    body = await _jpeg(request, request.app.state.settings.tryon_photo_max_kb)
    if isinstance(body, Response):
        return body
    got = await _run(svc.add_garment, uid, type, colour, body)
    if isinstance(got, Response):
        return got
    await record_change(
        request,
        agent=AGENT,
        tool="seeme_garment",
        args={"garment": got.id},
        detail="a garment's photo kept (not in his wardrobe)",
    )
    return _ok(got)


@router.get("/v1/seeme/garments", include_in_schema=False)
async def garments(request: Request, uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "read", change=False, console=False)
    if no is not None:
        return no
    return _answer(await _run(svc.garments, uid))


@router.get("/v1/seeme/garments/{id}", include_in_schema=False)
async def garment_out(
    request: Request,
    id: str,
    uid: str = Depends(current_user),  # noqa: A002 - the contract's
) -> Response:
    svc, no = _start(request, uid, "image", change=False, console=True)
    if no is not None:
        return no
    got = await _run(svc.garment_photo, uid, id)
    if isinstance(got, Response):
        return got
    return _image(got, JPEG) if got is not None else _no(404, "no_garment", texts.GARMENT_GONE)


@router.delete("/v1/seeme/garments/{id}", include_in_schema=False)
async def garment_drop(
    request: Request,
    id: str,
    uid: str = Depends(current_user),  # noqa: A002 - the contract's
) -> Response:
    svc, no = _start(request, uid, "change", change=True, console=True)
    if no is not None:
        return no
    got = await _run(svc.delete_garment, uid, id)
    if isinstance(got, Response):
        return got
    if not got:
        return _no(404, "no_garment", texts.GARMENT_GONE)
    await record_change(
        request,
        agent=AGENT,
        tool="seeme_garment_delete",
        args={"garment": id},
        detail="a garment's photo deleted",
    )
    return _ok(http.Deleted(deleted=True, message=texts.GARMENT_DELETED))


@router.get("/v1/seeme/pair", include_in_schema=False)
async def pair(request: Request, garment: str = "", uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "read", change=False, console=False)
    if no is not None:
        return no
    return _answer(await _run(svc.pair, uid, garment))


# ---- the estimate, the press, the pictures -------------------------------------------------------
def _pieces(raw: str) -> list[str] | None:
    found = [x.strip() for x in raw.split(",") if x.strip()]
    return found if all(PIECE_ID.match(x) for x in found) and len(found) <= 12 else None


@router.get("/v1/seeme/estimate", include_in_schema=False)
async def estimate(
    request: Request, garment: str = "", pieces: str = "", uid: str = Depends(current_user)
) -> Response:
    svc, no = _start(request, uid, "read", change=False, console=False)
    if no is not None:
        return no
    asked = _pieces(pieces)
    if asked is None:
        return _no(422, "not_a_garment", texts.NOT_HIS)
    return _answer(await _run(svc.estimate, uid, garment, asked))


@router.post("/v1/seeme/pictures", include_in_schema=False)
async def pictures(request: Request, uid: str = Depends(current_user)) -> Response:
    svc, no = _start(request, uid, "press", change=True, console=True, per=PRESSES_A_MINUTE)
    if no is not None:
        return no
    body = await _json(request, http.PictureIn)
    if isinstance(body, Response):
        return body
    got = await _run(svc.press, uid, body)
    made = not isinstance(got, Response)
    args = {"request_id": body.request_id, "garment": body.garment, "pieces": list(body.pieces)}
    await record_change(
        request,
        agent=AGENT,
        tool="seeme_picture",
        args=args,
        detail="a picture made" if made else "no picture",
    )
    return _ok(got) if made else got  # type: ignore[no-any-return]


@router.get("/v1/seeme/pictures/{id}", include_in_schema=False)
async def picture(
    request: Request,
    id: str,
    uid: str = Depends(current_user),  # noqa: A002 - the contract's
) -> Response:
    svc, no = _start(request, uid, "image", change=False, console=True)
    if no is not None:
        return no
    got = await _run(svc.picture, uid, id)
    if isinstance(got, Response):
        return got
    return _image(*got) if got is not None else _no(404, "gone", texts.PICTURE_GONE)


@router.post("/v1/seeme/pictures/{id}/keep", include_in_schema=False)
async def keep(
    request: Request,
    id: str,  # noqa: A002 - the contract's name
    uid: str = Depends(current_user),
) -> Response:
    svc, no = _start(request, uid, "change", change=True, console=True)
    if no is not None:
        return no
    body = await _json(request, http.KeepIn)
    if isinstance(body, Response):
        return body
    return _answer(await _run(svc.keep, uid, id, body.keep))


@router.delete("/v1/seeme/pictures/{id}", include_in_schema=False)
async def picture_drop(
    request: Request,
    id: str,
    uid: str = Depends(current_user),  # noqa: A002 - the contract's
) -> Response:
    svc, no = _start(request, uid, "change", change=True, console=True)
    if no is not None:
        return no
    got = await _run(svc.delete_picture, uid, id)
    if isinstance(got, Response):
        return got
    if not got:
        return _no(404, "gone", texts.PICTURE_GONE)
    return _ok(http.Deleted(deleted=True, message=texts.PICTURE_DELETED))


__all__ = ["router"]
