# src/jarvis/api/notes.py
"""Notes, memos and links: the HTTP surface (R2 D10; Layer 1 -> 3). Owner-only: `require_auth` +
`current_user` (a client user id is never read); cookie writes need `X-Requested-With: JARVIS`
(enforced by `require_auth`); rate-limited with the rest of /v1. Errors: {error, detail, reason?}.

GET    /v1/notes?q=&kind=&page=   NotesPage {items: [NoteView], total, page, pages, counts,
                                  available}. With q: the best 8 matches with snippets. Without a
                                  token key: 200 {available: false, reason, items: []}.
POST   /v1/notes                  {kind: note|memo|link, text, title?, tags?, url?, owner_note?}
                                  -> 201 NoteView. A memo is a transcript the owner reviewed. 422
                                  sensitive / bad_url / input_rejected, 409 notes_full.
PATCH  /v1/notes/{id}             {text?, title?, tags?, owner_note?, adopt?} -> NoteView.
                                  An outside or voice note stays so unless adopt: true. 404.
DELETE /v1/notes/{id}             -> {undo_id, kind: "note"}: Recently deleted for 30 days.
POST   /v1/notes/{id}/fetch       {confirm_credit: true} -> NoteView with the page excerpt; uses 1
                                  of the month's web credits. 409 web_off / allowance, 422 bad_url.
GET    /v1/notes/export           JSON attachment jarvis-notes-YYYY-MM-DD.json. Audited FIRST (R14
                                  D13 (4): agent `privacy`, the count only); 503 export_unaudited
                                  when the audit chain can't be written (nothing is sent).
POST   /v1/notes/import           {data} (<= 2 MB, filter applied) -> {added, skipped}
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.api.auth import require_auth
from jarvis.api.body import read_capped
from jarvis.api.identity import current_user
from jarvis.core.guardrails import ActionRisk
from jarvis.kb.models import (
    IMPORT_MAX_BYTES,
    MAX_OWNER_NOTE,
    MAX_TAGS,
    MAX_TEXT,
    ImportResult,
    Kind,
    NotesError,
    NotesPage,
    NoteView,
    invalid,
)
from jarvis.kb.service import NOT_CONFIGURED, NotesService
from jarvis.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/v1/notes", dependencies=[Depends(require_auth)])
EXPORT_AUDIT_AGENT, EXPORT_AUDIT_TOOL = "privacy", "notes_export"
UNAUDITED = (
    "The export couldn't be recorded in the audit log just now, so nothing was sent. Try again."
)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewNote(_Body):
    kind: Kind
    text: str = Field(default="", max_length=MAX_TEXT + 1)
    title: str | None = Field(default=None, max_length=400)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS * 4)
    url: str | None = Field(default=None, max_length=4096)
    owner_note: str = Field(default="", max_length=MAX_OWNER_NOTE + 1)


class NotePatch(_Body):
    text: str | None = Field(default=None, max_length=MAX_TEXT + 1)
    title: str | None = Field(default=None, max_length=400)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS * 4)
    owner_note: str | None = Field(default=None, max_length=MAX_OWNER_NOTE + 1)
    adopt: bool = False  # "mark as mine": the owner read the whole note and takes it as his own


class FetchRequest(_Body):
    confirm_credit: bool = False


class DeleteResult(BaseModel):
    undo_id: str
    kind: str = "note"


class ImportBody(_Body):
    data: dict[str, object]


def _svc(request: Request) -> NotesService:
    svc: NotesService | None = getattr(request.app.state, "notes", None)
    if svc is None:
        reason = getattr(request.app.state, "notes_reason", None) or NOT_CONFIGURED
        raise NotesError(503, "notes_off", reason)
    return svc


@router.get("", response_model=NotesPage)
async def list_notes(
    request: Request,
    q: str = Query(default="", max_length=200),
    kind: Kind | None = None,
    page: int = Query(default=1, ge=1, le=1000),
    uid: str = Depends(current_user),
) -> NotesPage | JSONResponse:
    svc: NotesService | None = getattr(request.app.state, "notes", None)
    if svc is None:
        reason = getattr(request.app.state, "notes_reason", None) or NOT_CONFIGURED
        off: dict[str, object] = {
            "available": False,
            "reason": reason,
            "items": [],
            "total": 0,
            "page": 1,
        }
        return JSONResponse({**off, "pages": 1, "counts": {"note": 0, "memo": 0, "link": 0}})
    return await svc.browse(uid, q=q, kind=kind, page=page)


@router.post("", status_code=201, response_model=NoteView)
async def add_note(
    body: NewNote, svc: NotesService = Depends(_svc), uid: str = Depends(current_user)
) -> NoteView:
    note = await svc.add(
        uid,
        kind=body.kind,
        text=body.text,
        title=body.title,
        tags=body.tags,
        url=body.url,
        owner_note=body.owner_note,
        origin="memo" if body.kind == "memo" else "typed",
    )
    return NoteView.of(note)


@router.patch("/{note_id}", response_model=NoteView)
async def patch_note(
    note_id: str,
    body: NotePatch,
    svc: NotesService = Depends(_svc),
    uid: str = Depends(current_user),
) -> NoteView:
    note = await svc.update(
        uid,
        note_id,
        text=body.text,
        title=body.title,
        tags=body.tags,
        owner_note=body.owner_note,
        adopt=body.adopt,
    )
    return NoteView.of(note)


@router.delete("/{note_id}", response_model=DeleteResult)
async def delete_note(
    note_id: str, svc: NotesService = Depends(_svc), uid: str = Depends(current_user)
) -> DeleteResult:
    item = await svc.remove(uid, note_id)
    return DeleteResult(undo_id=item.id)


@router.post("/{note_id}/fetch", response_model=NoteView)
async def fetch_note(
    note_id: str,
    body: FetchRequest,
    svc: NotesService = Depends(_svc),
    uid: str = Depends(current_user),
) -> NoteView:
    if not body.confirm_credit:
        raise invalid("Confirm that fetching uses 1 of your monthly web credits.")
    return NoteView.of(await svc.fetch(uid, note_id))


async def _audit_export(request: Request, count: int) -> bool:
    """R14 D13 (4): one line on the app's audit chain (the gateway's), the count only, before the
    file goes out. False when the chain is there but the line could not be written. With no chain
    (tools switched off) there is nothing to write to: logged, and the export answers."""
    gw = getattr(request.app.state, "gateway", None)
    if gw is None:
        log.warning("no audit chain for a notes export", extra={"count": count})
        return True
    try:
        await gw.audit.append(
            agent=EXPORT_AUDIT_AGENT,
            tool=EXPORT_AUDIT_TOOL,
            risk=ActionRisk.READ_ONLY,
            outcome="executed",
            args={"count": count},
            detail=f"notes: {count}",
        )
    except Exception as exc:  # noqa: BLE001 - an export nobody can see later is not sent
        log.error("AUDIT WRITE FAILED for a notes export", extra={"error": type(exc).__name__})
        return False
    return True


@router.get("/export")
async def export_notes(
    request: Request, svc: NotesService = Depends(_svc), uid: str = Depends(current_user)
) -> Response:
    data = await svc.export(uid)
    notes = data.get("notes")
    if not await _audit_export(request, len(notes) if isinstance(notes, list) else 0):
        raise NotesError(503, "export_unaudited", UNAUDITED)
    name = f"jarvis-notes-{datetime.now(UTC):%Y-%m-%d}.json"
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


def _too_large() -> NotesError:
    return NotesError(413, "too_large", "That file is larger than 2 MB, so it was not imported.")


@router.post("/import", response_model=ImportResult)
async def import_notes(
    request: Request, svc: NotesService = Depends(_svc), uid: str = Depends(current_user)
) -> ImportResult:
    raw = await read_capped(request, IMPORT_MAX_BYTES, too_large=_too_large)
    try:
        body = ImportBody.model_validate_json(raw)
    except ValidationError:
        raise invalid("The file is not a JARVIS notes export.") from None
    return await svc.import_(uid, body.data)


def install_notes(app: FastAPI) -> None:
    """Mount /v1/notes and its error mapping on `app`. The service is `app.state.notes` (None:
    notes are off, with `app.state.notes_reason` in plain words)."""

    @app.exception_handler(NotesError)
    async def _notes_error(_: Request, exc: NotesError) -> JSONResponse:
        body = {"error": exc.code, "detail": exc.detail}
        if exc.reason:
            body["reason"] = exc.reason
        return JSONResponse(status_code=exc.status, content=body)

    app.include_router(router)


__all__ = ["install_notes", "router"]
