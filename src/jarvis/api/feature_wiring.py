# src/jarvis/api/feature_wiring.py
"""Slices 10-12 on the app (moved out of `api/app.py` at R6 I0, behaviour unchanged, so that file
stays a short list of named steps, as R2's `api/personal.py`, R3's `api/home_wiring.py` and R4's
`api/r4_wiring.py` do).

- `wire_features` (slices 10-11): web search, attached files, Recently deleted and the to-dos
  JARVIS wrote from outside content, on the same documents.
- `wire_slice12`: Maps + YouTube on JARVIS's own Google API key, and Drive (chosen folders only),
  sharing the documents' ONE extraction slot.
- `build_undo`: Recently deleted only on persistent storage.
"""

from __future__ import annotations

from fastapi import FastAPI

from jarvis.config import Settings
from jarvis.documents.service import DocumentService, policy_from
from jarvis.documents.store import AttachmentStore
from jarvis.drive.service import DriveService, build_drive_service
from jarvis.media.service import build_media
from jarvis.storage import Storage
from jarvis.storage.docs import Docs
from jarvis.tools.task_marks import OutsideTasks
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.web.service import build_web_service


def build_undo(s: Settings, built: Storage | None, docs: Docs) -> UndoBin | None:
    """Recently deleted (slice 11) only on persistent storage: a copy kept in process memory
    would vanish on a restart, so "Undo for 30 days" would not hold. Without it every delete
    stays R3 (card + passkey) and /v1/deleted says it isn't available."""
    if built is None or not built.persistent:
        return None
    return UndoBin(DeletedStore(docs, prefix=s.firestore_prefix))


def wire_features(
    app: FastAPI, s: Settings, undo: UndoBin | None, built: Storage | None, docs: Docs
) -> None:
    """Slices 10–11 on the same documents: web search, attached files, Recently deleted and the
    to-dos JARVIS wrote from outside content. `undo` is the one a test or host injected (None:
    built here)."""
    app.state.web = build_web_service(s, docs)  # slice 10 B: None without a Tavily key
    # Attached files (slice 10 E): text and chunks on the same documents, deleted with the
    # conversation; the doc tools join the gateway's registry.
    app.state.documents = DocumentService(
        AttachmentStore(docs, prefix=s.firestore_prefix),
        policy=policy_from(s),  # R11.1 D11: what one message may carry, his own settings
        sessions=app.state.store,  # R11.1 D10: a turn's pictures come from the stored turn
    )
    # Recently deleted (slice 11): the owner's deletes keep a copy here for 30 days (undo);
    # only on persistent storage, else None and deletes stay R3
    app.state.undo = undo or build_undo(s, built, docs)
    app.state.outside_tasks = OutsideTasks(docs, prefix=s.firestore_prefix)  # D8 (swept)


def wire_slice12(app: FastAPI, s: Settings, docs: Docs, drive: DriveService | None) -> None:
    """Maps + YouTube (D2–D4) on JARVIS's own Google API key (None without one), and Drive,
    chosen folders only (D1): None unless JARVIS_DRIVE=on. Drive files go through the documents'
    ONE extraction slot (never two children at once)."""
    app.state.media = build_media(s, docs, google=app.state.google)
    one_slot = app.state.documents.extract
    app.state.drive = drive or build_drive_service(s, docs, extract=one_slot)
    if app.state.drive is not None and app.state.drive.extract is None:
        app.state.drive.extract = one_slot


__all__ = ["build_undo", "wire_features", "wire_slice12"]
