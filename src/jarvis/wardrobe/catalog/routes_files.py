# src/jarvis/wardrobe/catalog/routes_files.py
"""Part A's picture and file routes (docs/plans/r13-wardrobe.md "The HTTP contract", D7, D9,
D17), included by `api/wardrobe.py`'s router (the one router the wiring installs).

    POST   /v1/wardrobe/photos?piece=&view=   the door's crop (image/jpeg) -> PhotoSaved
    DELETE /v1/wardrobe/photos/{id}           -> Deleted
    GET    /v1/wardrobe/photos/{id}           the sealed thumbnail for his console (image/jpeg)
    GET    /v1/wardrobe/fingerprints?model=   his saved fingerprints of one model
    POST   /v1/wardrobe/fingerprints          "Remember how it looks" (FingerprintIn)
    POST   /v1/wardrobe/tag?piece=            the door's crop for AI tagging -> TagReply
    GET    /v1/wardrobe/tag/estimate?piece=   its rupees first -> TagEstimate
    GET    /v1/wardrobe/backup?photos=1       the sealed file, streamed
    POST   /v1/wardrobe/restore/check         the file -> RestoreCheck (writes nothing)
    POST   /v1/wardrobe/restore?token=&include=   the same file -> RestoreDone

A picture body is read with `read_capped` at the photo cap and must be `image/jpeg`; the restore
body at `wardrobe_backup_max_mb` (the middleware lets 30 MB + 64 KB through on these two paths,
I0's `BODY_CAPS`), answered in plain words between the two. Picture bytes never reach a log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from jarvis.api.auth import require_auth
from jarvis.api.body import BodyTooLarge, read_capped
from jarvis.api.identity import current_user
from jarvis.wardrobe import http
from jarvis.wardrobe.catalog.routes_common import (
    NO_STORE_HEADERS,
    desk_of,
    err,
    off,
    off_words,
    ok,
    refused,
)
from jarvis.wardrobe.catalog.routes_common import too_many as limited
from jarvis.wardrobe.model import PHOTO_ID, PIECE_ID

router = APIRouter(dependencies=[Depends(require_auth)])
JPEG = "image/jpeg"
NOT_FOUND = "That photo isn't in your wardrobe."
NOT_JPEG = "Only a JPEG photo of a saved piece can be kept."


async def _jpeg(request: Request, desk: Any) -> bytes | JSONResponse:
    if request.headers.get("content-type", "").split(";")[0].strip() != JPEG:
        return err(422, NOT_JPEG)
    cap = desk.vault.max_bytes
    try:
        return await read_capped(request, cap, too_large=lambda: BodyTooLarge(cap))
    except BodyTooLarge:
        return err(413, f"A photo is at most {cap // 1024} KB.")


@router.post("/v1/wardrobe/photos", include_in_schema=False)
async def save_photo(
    request: Request, piece: str, view: str, uid: str = Depends(current_user)
) -> JSONResponse:
    if (desk := desk_of(request)) is None:
        return off(request, 422)
    if (busy := limited(request, "photos", uid, change=True)) is not None:
        return busy
    body = await _jpeg(request, desk)
    if isinstance(body, JSONResponse):
        return body
    try:
        photo, size = await desk.vault.save(uid, piece, view, body)
    except Exception as exc:  # noqa: BLE001 - a refusal in words
        return refused(exc, down=422)
    return ok(http.PhotoSaved(photo=photo, piece=piece, view=view, bytes=size))  # type: ignore[arg-type]


@router.delete("/v1/wardrobe/photos/{id}", include_in_schema=False)
async def delete_photo(
    request: Request,
    id: str,
    uid: str = Depends(current_user),  # noqa: A002 - the contract's name
) -> JSONResponse:
    photo = id
    desk = desk_of(request)
    if desk is None or not PHOTO_ID.match(photo):
        return err(404, NOT_FOUND)
    if (busy := limited(request, "photos", uid, change=True)) is not None:
        return busy
    try:
        gone = await desk.vault.delete(uid, photo)
    except Exception as exc:  # noqa: BLE001
        return refused(exc, status=404, down=404)
    if not gone:
        return err(404, NOT_FOUND)
    return ok(http.Deleted(deleted=True, message="The photo is deleted."))


@router.get("/v1/wardrobe/photos/{id}", include_in_schema=False)
async def get_photo(
    request: Request,
    id: str,
    uid: str = Depends(current_user),  # noqa: A002 - the contract's name
) -> Response:
    photo = id
    desk = desk_of(request)
    if desk is None or not PHOTO_ID.match(photo):
        return err(404, NOT_FOUND)
    if (busy := limited(request, "photo", uid, change=False)) is not None:
        return busy
    try:
        found = await desk.vault.get(uid, photo)
    except Exception:  # noqa: BLE001 - one that can't be opened is not his to see
        found = None
    if found is None:
        return err(404, NOT_FOUND)
    heads = NO_STORE_HEADERS | {"X-Content-Type-Options": "nosniff"}
    return Response(found, media_type=JPEG, headers=heads)


@router.get("/v1/wardrobe/fingerprints", include_in_schema=False)
async def fingerprints(
    request: Request, model: str = "mnv2-int8-1", uid: str = Depends(current_user)
) -> JSONResponse:
    if (busy := limited(request, "fingerprints", uid, change=False)) is not None:
        return busy
    chosen = model if model in ("mnv2-int8-1", "mnv2-fp32-1") else "mnv2-int8-1"
    desk = desk_of(request)
    items: tuple[Any, ...] = ()
    if desk is not None:
        try:
            found = await desk.vault.prints.items(uid, chosen)
        except Exception:  # noqa: BLE001 - none to compare with: every scan is "new?"
            found = ()
        items = tuple(http.FingerprintView(piece=e["p"], view=e["w"], v=e["v"]) for e in found)
    return ok(http.Fingerprints(model=chosen, items=items))  # type: ignore[arg-type]


@router.post("/v1/wardrobe/fingerprints", include_in_schema=False)
async def keep_fingerprint(
    request: Request, body: http.FingerprintIn, uid: str = Depends(current_user)
) -> JSONResponse:
    if (desk := desk_of(request)) is None:
        return off(request, 422)
    if (busy := limited(request, "fingerprints", uid, change=True)) is not None:
        return busy
    try:
        await desk.vault.prints.save(uid, body.piece, body.view, body.model, body.v)
    except Exception as exc:  # noqa: BLE001
        return refused(exc, down=422)
    return ok(http.FingerprintSaved(piece=body.piece, view=body.view, model=body.model))


@router.post("/v1/wardrobe/tag", include_in_schema=False)
async def tag(request: Request, piece: str, uid: str = Depends(current_user)) -> JSONResponse:
    if (desk := desk_of(request)) is None:
        return off(request)
    if (busy := limited(request, "tag", uid, change=True)) is not None:
        return busy
    if not PIECE_ID.match(piece):
        return err(422, "AI tagging is only for a saved piece that isn't private.")
    body = await _jpeg(request, desk)
    if isinstance(body, JSONResponse):
        return body if body.status_code != 413 else err(422, "That photo is too large.")
    try:
        return ok(await desk.tagging.tag(uid, piece, body))
    except Exception as exc:  # noqa: BLE001 - TagRefused carries its 402 / 422 / 503
        return refused(exc)


@router.get("/v1/wardrobe/tag/estimate", include_in_schema=False)
async def tag_estimate(
    request: Request, piece: str, uid: str = Depends(current_user)
) -> JSONResponse:
    if (busy := limited(request, "tag", uid, change=False)) is not None:
        return busy
    desk = desk_of(request)
    if desk is None:
        why = off_words(request)
        return ok(http.TagEstimate(inr=0.0, month_inr=0.0, cap_inr=0, allowed=False, why=why))
    try:
        return ok(await desk.tagging.estimate(uid, piece))
    except Exception:  # noqa: BLE001 - can't tell: not allowed, in words
        why = "AI tagging can't be checked just now."
        return ok(http.TagEstimate(inr=0.0, month_inr=0.0, cap_inr=0, allowed=False, why=why))


@router.get("/v1/wardrobe/backup", include_in_schema=False)
async def backup(request: Request, photos: int = 0, uid: str = Depends(current_user)) -> Response:
    if (desk := desk_of(request)) is None:
        return off(request)
    if (busy := limited(request, "backup", uid, change=False)) is not None:
        return busy
    try:
        await desk.backup.check_size(uid, bool(photos))
        await desk.store.view(uid)  # fails here, in words, before a byte is sent
    except Exception as exc:  # noqa: BLE001
        return refused(exc, status=503)
    name = "jarvis-wardrobe-photos.jwb" if photos else "jarvis-wardrobe.jwb"
    heads = NO_STORE_HEADERS | {"X-Content-Type-Options": "nosniff"}
    heads["Content-Disposition"] = f'attachment; filename="{name}"'
    stream = desk.backup.lines(uid, photos=bool(photos))
    return StreamingResponse(stream, media_type="application/octet-stream", headers=heads)


async def _file(request: Request, desk: Any) -> bytes | JSONResponse:
    cap = desk.backup.max_bytes
    try:
        return await read_capped(request, cap, too_large=lambda: BodyTooLarge(cap))
    except BodyTooLarge:
        return err(413, f"A wardrobe backup is at most {desk.backup.max_mb} MB.")


@router.post("/v1/wardrobe/restore/check", include_in_schema=False)
async def restore_check(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    if (desk := desk_of(request)) is None:
        return off(request, 422)
    if (busy := limited(request, "restore", uid, change=True)) is not None:
        return busy
    body = await _file(request, desk)
    if isinstance(body, JSONResponse):
        return body
    try:
        return ok(await desk.restore.check(uid, body))
    except Exception as exc:  # noqa: BLE001
        return refused(exc, down=422)


@router.post("/v1/wardrobe/restore", include_in_schema=False)
async def restore(
    request: Request, token: str = "", include: str = "", uid: str = Depends(current_user)
) -> JSONResponse:
    if (desk := desk_of(request)) is None:
        return off(request, 422)
    if (busy := limited(request, "restore", uid, change=True)) is not None:
        return busy
    body = await _file(request, desk)
    if isinstance(body, JSONResponse):
        return body
    ticked = tuple(x for x in include.split(",") if PIECE_ID.match(x))
    try:
        return ok(await desk.restore.apply(uid, body, token, ticked))
    except Exception as exc:  # noqa: BLE001 - an expired token is a 409
        from jarvis.wardrobe.catalog.restore import EXPIRED  # noqa: PLC0415

        return refused(exc, status=409 if str(exc) == EXPIRED else 422, down=422)


__all__ = ["router"]
