# src/jarvis/api/documents.py
"""Attached-file HTTP surface (slice 10 E; Layer 1 → 2). Owner-only: `require_auth` +
`current_user` (no client user id is read); cookie writes need `X-Requested-With: JARVIS`
(enforced by `require_auth`); ≤ 6 uploads a minute per owner on top of the /v1 per-client limit.

POST   /v1/attachments       body: the file's raw bytes (Content-Type is ignored: the type comes
                             from the name AND the bytes); header X-Jarvis-Filename: the name,
                             percent-encoded UTF-8. ≤ 10 MB: this route's own cap (Content-Length
                             checked before reading, a chunked body cut off as it passes); the
                             app-wide 2.1 MB cap stays on every other route → 201 AttachmentRef
                             {id, name, kind, size, pages, words, chars, truncated}. The file is
                             not kept: its text is. Errors {error, detail}: 413 too_large, 415
                             unsupported, 422 no_name / empty / encrypted / no_text / unreadable /
                             too_complex / too_slow, 408 upload_timeout (the body took > 60 s),
                             403 documents_off (Documents is "Never" in Permissions; also
                             refused on send), 409 too_many, 429 rate_limited, 503 busy /
                             permissions_unavailable (Retry-After on 429 / 503).
                             The file's text is read by a limited child process
                             (`jarvis.documents.isolation`), one at a time.
                             R11.1 (D10-D11): also Excel (.xlsx, .xlsm, .xls), PowerPoint
                             (.pptx), pictures (.png, .jpg, .jpeg: 413 too_large over the pixel
                             or byte cap, 422 bad_picture), .zip (422 unsafe_archive: an archive
                             inside it, a path outside it) and, with header X-Jarvis-Folder: 1,
                             a folder the console packed into one bundle (its name is the
                             folder's). The ref adds sheets, rows, slides, files, skipped and
                             pictures.
DELETE /v1/attachments/{id}  a file not sent yet (the owner removed its chip) → 204; 404
                             not_found. A sent file goes with its conversation.

Then POST /v1/chat {message, attachments: [id, …]} sends them with a message: at most
`attach_max_files` (10), `attach_total_mb` (40) together and 4 pictures (422 input_rejected).
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.body import read_capped
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.documents.extract import kind_for
from jarvis.documents.models import MAX_FILE_BYTES, AttachmentRef, DocumentRejected
from jarvis.documents.note import clean_name
from jarvis.documents.service import DocumentService, too_large

ATTACH_PATH = "/v1/attachments"
ATTACH_BODY_BYTES = MAX_FILE_BYTES + 64 * 1024  # the app-wide middleware's cap for this path
UPLOADS_PER_MINUTE = 6
READ_TIMEOUT_S = 60.0  # the whole body, however it arrives
NAME_HEADER = "x-jarvis-filename"
FOLDER_HEADER = "x-jarvis-folder"  # "1": the body is a folder the console packed (R11.1 D11)
NAME_HEADER_LIMIT = 1_000
BUSY_RETRY_S = 30

router = APIRouter(prefix=ATTACH_PATH, dependencies=[Depends(require_auth)])


class UploadRateLimited(Exception):
    def __init__(self, wait_s: float) -> None:
        self.retry_after = max(1, int(wait_s + 0.999))
        super().__init__("too many uploads")


def _svc(request: Request) -> DocumentService:
    svc: DocumentService | None = getattr(request.app.state, "documents", None)
    if svc is None:
        raise LookupError("Attached files are not available on this server.")
    return svc  # R11.1 I1: the app builds it with his limits (feature_wiring.wire_features)


def _limit(request: Request, uid: str) -> None:
    limiter: RateLimiter = request.app.state.attach_limit
    allowed, wait = limiter.allow(uid)
    if not allowed:
        raise UploadRateLimited(wait)


def _name(request: Request) -> str:
    raw = request.headers.get(NAME_HEADER, "")
    missing = DocumentRejected("no_name", "The file's name didn't arrive. Attach it again.")
    if not raw or len(raw) > NAME_HEADER_LIMIT:
        raise missing
    try:
        name = unquote(raw, errors="strict")
    except UnicodeDecodeError:
        raise missing from None
    if not clean_name(name):
        raise missing
    return name


@router.post("", status_code=201, response_model=AttachmentRef)
async def upload(
    request: Request, svc: DocumentService = Depends(_svc), uid: str = Depends(current_user)
) -> AttachmentRef:
    _limit(request, uid)
    name = _name(request)
    folder = request.headers.get(FOLDER_HEADER, "") == "1"
    if not folder:
        kind_for(clean_name(name))  # an unsupported type is refused before the body is read
    await svc.ensure_on(uid)  # Documents on "Never" in Permissions: refused before reading too
    try:  # an overall deadline: a sender that trickles bytes can't hold the route open
        data = await asyncio.wait_for(
            read_capped(request, MAX_FILE_BYTES, too_large=too_large), READ_TIMEOUT_S
        )
    except TimeoutError:
        raise DocumentRejected(
            "upload_timeout",
            "The upload took too long. Check the connection and try again.",
            status=408,
        ) from None
    return await svc.upload(uid, name, data, folder=folder)


@router.delete("/{attachment_id}", status_code=204)
async def discard(
    attachment_id: str, svc: DocumentService = Depends(_svc), uid: str = Depends(current_user)
) -> Response:
    await svc.discard(uid, attachment_id)
    return Response(status_code=204)


def _err(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=headers)


def install_documents(app: FastAPI) -> None:
    """Mount /v1/attachments, its per-owner limit and its error mapping on `app`."""
    app.state.attach_limit = RateLimiter(UPLOADS_PER_MINUTE)

    @app.exception_handler(DocumentRejected)
    async def _rejected(_: Request, exc: DocumentRejected) -> JSONResponse:
        retry = {"Retry-After": str(BUSY_RETRY_S)} if exc.status == 503 else None
        return _err(exc.status, {"error": exc.code, "detail": str(exc)}, retry)

    @app.exception_handler(UploadRateLimited)
    async def _limited(_: Request, exc: UploadRateLimited) -> JSONResponse:
        retry = {"Retry-After": str(exc.retry_after)}
        return _err(
            429, {"error": "rate_limited", "detail": "Too many uploads; wait a moment."}, retry
        )

    app.include_router(router)


__all__ = ["ATTACH_BODY_BYTES", "ATTACH_PATH", "UPLOADS_PER_MINUTE", "install_documents", "router"]
