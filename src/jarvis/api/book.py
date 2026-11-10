# src/jarvis/api/book.py
"""The build book's owner routes (R6 D6-D9, D16; "Contract"; builder B). Owner-only
(`require_auth` + `current_user`), every answer `no-store` + `nosniff`, every failure
`{error, detail}` in plain words.

GET  /v1/book                          status; for the PRIMARY owner it first seals the current
                                       release (D7: one shared run, waited on at most 20 s; past
                                       that `sealing: true`, the panel asks again)
GET  /v1/book/sections                 ● the current book's eight sections
GET  /v1/book/releases/{rid}/sections  ● an older sealed release's sections
POST /v1/book/releases/{rid}/ticket    ● {ticket, expires_in_s: 60}
GET  /v1/book/download/{ticket}        the sealed source zip (attachment), audited first
GET  /v1/book/settings | PUT           D16 Book settings

● = header X-Jarvis-Book: a live OWNER book session, checked through `app.state.book_sessions`
(ports.BookSessions). ● routes and the download are the console's (a bearer script: 403
console_only). Everything is read from `app.state` per request; a missing required part answers
503 book_off, an optional one (lock, talk, service, sealer) has a safe default.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from jarvis.api.auth import require_auth, session_email
from jarvis.api.book_http import BOOK_OFF, NO_STORE, TOKEN_HEADER, book_err, book_json
from jarvis.api.book_status import NO_BOOK, status_body
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.buildbook.lines import CREATOR_MAX
from jarvis.buildbook.model import Book, SealedRelease, SessionView, load_book
from jarvis.buildbook.owner import BookSettingsPatch, SettingsRejected
from jarvis.buildbook.ports import BookError, BookUnavailable, SessionGone, VaultTampered
from jarvis.config import AuthMode, Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.vault.unlock import TicketGone

log = get_logger(__name__)

router = APIRouter(prefix="/v1/book", dependencies=[Depends(require_auth)])

TICKETS_PER_MINUTE = 10
DOWNLOADS_PER_MINUTE = 10
SETTINGS_PER_MINUTE = 30
TOKEN_MAX = 128
GONE = "Open the build book again."
NOT_SEALED = "That release isn't sealed in your vault."
TAMPERED = "That sealed build book failed its integrity check, so it stays closed."
DOWN = "The vault can't be reached right now."
_RID = re.compile(r"[0-9a-f]{7}")
_TICKET = re.compile(r"[A-Za-z0-9_\-]{20,100}")


class BookRefused(Exception):
    """A route's refusal: answered as {error, detail} with no-store by `install_book`."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _need(request: Request, name: str) -> Any:
    part = getattr(request.app.state, name, None)
    if part is None:
        raise BookRefused(503, "book_off", BOOK_OFF)
    return part


def _console_only(request: Request) -> None:
    """The book opens in the console only: a signed-in browser (or token-mode dev)."""
    s: Settings = request.app.state.settings
    if session_email(request, s) is not None or (s.auth_mode is AuthMode.TOKEN and s.env == "dev"):
        return
    raise BookRefused(
        403, "console_only", "The build book opens only in the JARVIS console, not from a script."
    )


def _limit(request: Request, name: str, uid: str) -> None:
    allowed, _ = request.app.state.book_limits[name].allow(uid)
    if not allowed:
        raise BookRefused(429, "rate_limited", "Too many requests; wait a moment.")


async def _owner_session(request: Request, uid: str, token: str | None) -> SessionView:
    """The live OWNER book session this token opens (D9: sections, older books, the code)."""
    sessions = _need(request, "book_sessions")
    if not token or len(token) > TOKEN_MAX:
        raise BookRefused(401, "session_gone", GONE)
    try:
        session: SessionView = await sessions.resolve(uid, token, now=_now())
    except SessionGone:
        raise BookRefused(401, "session_gone", GONE) from None
    if session.audience != "owner":
        raise BookRefused(403, "owner_only", "Only your own book session opens this.")
    return session


async def _audit(request: Request, tool: str, args: dict[str, Any]) -> bool:
    """Audit first; False means the entry could not be written (nothing is sent)."""
    gw = getattr(request.app.state, "gateway", None)
    if gw is None:
        log.error("no audit chain: a book event is refused", extra={"tool": tool})
        return False
    try:
        await gw.audit.append(
            agent="owner", tool=tool, risk=ActionRisk.READ_ONLY, outcome="executed", args=args
        )
    except Exception as exc:  # noqa: BLE001
        log.error("AUDIT WRITE FAILED for a book event", extra={"error": type(exc).__name__})
        return False
    return True


# ---- reading the sealed vault ------------------------------------------------------------------


async def _sealed(request: Request, uid: str) -> tuple[SealedRelease, ...]:
    try:
        rows: tuple[SealedRelease, ...] = await _need(request, "book_vault").releases(uid)
    except VaultTampered:
        raise BookRefused(503, "tampered", TAMPERED) from None
    except BookError:
        raise BookRefused(503, "unavailable", DOWN) from None
    return rows


async def _find(request: Request, uid: str, rid: str) -> SealedRelease:
    if not _RID.fullmatch(rid):
        raise BookRefused(404, "not_found", NOT_SEALED)
    found = next((r for r in await _sealed(request, uid) if r.id == rid), None)
    if found is None:
        raise BookRefused(404, "not_found", NOT_SEALED)
    return found


async def _read(request: Request, uid: str, found: SealedRelease, kind: str) -> bytes:
    try:
        data: bytes = await _need(request, "book_vault").read(uid, found.id, kind)
    except LookupError:
        raise BookRefused(404, "not_found", NOT_SEALED) from None
    except VaultTampered:
        sealer = getattr(request.app.state, "book_sealer", None)
        if sealer is not None and hasattr(sealer, "report_tampered"):
            await sealer.report_tampered(uid, found.id, found.label)
        raise BookRefused(503, "tampered", TAMPERED) from None
    except BookError:
        raise BookRefused(503, "unavailable", DOWN) from None
    return data


def _sections(book: Book) -> dict[str, Any]:
    return {"release": book.release.model_dump(), "sections": book.sections()}


# ---- GET /v1/book ------------------------------------------------------------------------------


@router.get("", response_model=None)
async def status(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    source, vault = _need(request, "book_source"), _need(request, "book_vault")
    return book_json(await status_body(request, uid, source, vault))


# ---- sections ------------------------------------------------------------------------------


@router.get("/sections", response_model=None)
async def sections(
    request: Request,
    uid: str = Depends(current_user),
    token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> JSONResponse:
    source = _need(request, "book_source")
    _console_only(request)
    await _owner_session(request, uid, token)
    try:
        book: Book = source.book()
    except (BookUnavailable, ValueError):
        raise BookRefused(404, "no_book", NO_BOOK) from None
    return book_json(_sections(book))


@router.get("/releases/{rid}/sections", response_model=None)
async def release_sections(
    rid: str,
    request: Request,
    uid: str = Depends(current_user),
    token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> JSONResponse:
    _need(request, "book_vault")
    _console_only(request)
    await _owner_session(request, uid, token)
    found = await _find(request, uid, rid)
    try:
        book = load_book(await _read(request, uid, found, "book"))
    except ValueError:  # sealed by a release whose book this version can't read
        raise BookRefused(
            409, "unreadable", "This version can't read that release's book."
        ) from None
    return book_json(_sections(book))


# ---- the code: ticket, then download ---------------------------------------------------------


@router.post("/releases/{rid}/ticket", response_model=None)
async def ticket(
    rid: str,
    request: Request,
    uid: str = Depends(current_user),
    token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> JSONResponse:
    tickets = _need(request, "book_tickets")
    _need(request, "book_vault")
    _console_only(request)
    await _owner_session(request, uid, token)
    _limit(request, "ticket", uid)
    found = await _find(request, uid, rid)
    try:
        t = await tickets.issue(uid, found.id)
    except Exception as exc:  # noqa: BLE001 - storage: no ticket, plain words
        log.error("book ticket not issued", extra={"error": type(exc).__name__})
        raise BookRefused(503, "unavailable", DOWN) from None
    return book_json({"ticket": t.ticket, "expires_in_s": t.expires_in_s})


@router.get("/download/{ticket}", response_model=None)
async def download(
    ticket: str, request: Request, uid: str = Depends(current_user)
) -> JSONResponse | Response:
    tickets = _need(request, "book_tickets")
    _need(request, "book_vault")
    _console_only(request)
    _limit(request, "download", uid)
    gone = book_err(410, "gone", "That download link was already used or has expired.")
    if not _TICKET.fullmatch(ticket):
        return gone
    try:
        taken = await tickets.take(uid, ticket)
    except TicketGone:
        return gone
    except Exception as exc:  # noqa: BLE001 - storage: nothing is sent
        log.error("book ticket unreadable", extra={"error": type(exc).__name__})
        raise BookRefused(503, "unavailable", DOWN) from None
    found = await _find(request, uid, str(taken.item or ""))
    data = await _read(request, uid, found, "source")
    if not await _audit(request, "book_download", {"release": found.id}):
        raise BookRefused(503, "unavailable", "The download could not be recorded.")
    headers = {
        **NO_STORE,
        "Content-Disposition": f'attachment; filename="JARVIS-source-{found.id}.zip"',
    }
    return Response(content=data, media_type="application/zip", headers=headers)


# ---- Book settings (D16) ---------------------------------------------------------------------


@router.get("/settings", response_model=None)
async def get_settings(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    store = _need(request, "book_settings")
    try:
        current = await store.get(uid)
    except BookError as exc:
        raise BookRefused(503, "unavailable", str(exc)) from None
    return book_json({**current.model_dump(), "creator_max": CREATOR_MAX})


@router.put("/settings", response_model=None)
async def put_settings(
    request: Request, uid: str = Depends(current_user), payload: Any = Body(default=None)
) -> JSONResponse:
    store = _need(request, "book_settings")
    _limit(request, "settings", uid)
    try:
        patch = BookSettingsPatch.model_validate(payload)
    except ValidationError:
        raise BookRefused(
            422, "input_rejected", "Those Book settings aren't valid; nothing was changed."
        ) from None
    try:
        saved = await store.update(uid, patch)
    except SettingsRejected as exc:
        raise BookRefused(422, "input_rejected", str(exc)) from None
    except BookError as exc:
        raise BookRefused(503, "unavailable", str(exc)) from None
    fields = sorted(patch.model_dump(exclude_none=True))
    await record_change(request, agent="book", tool="book_settings", args={"fields": fields})
    return book_json(saved.model_dump())


def install_book(app: FastAPI) -> None:
    """Mount /v1/book, its per-owner limits and its refusal answer on `app`."""
    app.state.book_limits = {
        "ticket": RateLimiter(TICKETS_PER_MINUTE),
        "download": RateLimiter(DOWNLOADS_PER_MINUTE),
        "settings": RateLimiter(SETTINGS_PER_MINUTE),
    }

    async def _refused(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, BookRefused)
        return book_err(exc.status, exc.code, exc.detail)

    app.add_exception_handler(BookRefused, _refused)
    app.include_router(router)


__all__ = ["BookRefused", "install_book", "router"]
