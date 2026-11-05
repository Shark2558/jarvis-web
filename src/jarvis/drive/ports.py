# src/jarvis/drive/ports.py
"""Google Drive, chosen folders only (slice 12 D1; Layer 6): the data and the errors.

JARVIS reads Drive as its own Google identity (the Cloud Run service account `jarvis-run`), never
as the owner: the owner shares a folder with JARVIS's address (Viewer) and then ticks "Use" for it
in Integrations. Google enforces what the account can see at all; JARVIS additionally reads only
inside the folders the owner confirmed (`jarvis.drive.guard`).

Everything here is plain data, type-checked when it is made (`jarvis.drive.client`). File names
and contents are other people's words: the tools fence them. Every error carries plain English of
our own; Google's text never reaches the model or the owner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
SLIDES_MIME = "application/vnd.google-apps.presentation"
GOOGLE_PREFIX = "application/vnd.google-apps."
# Drive ids are URL-safe base64-ish; anything else is never sent to Drive or stored.
DRIVE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
MAX_ROOTS = 20
MAX_FILE_BYTES = 10 * 1024 * 1024  # PDF / DOCX / text downloads, and Google's own export cap


class DriveError(RuntimeError):
    """A Drive step failed; the message is plain English, free of Google's text."""


class DriveUnavailable(DriveError):
    """JARVIS can't get its Drive token or reach Drive (off Cloud Run, timeout, refused)."""


class DriveNotFound(DriveError):
    """Drive says it isn't there for JARVIS: never shared with it, un-shared, or deleted."""


class NotInRoots(DriveError):
    """The item is not inside a folder the owner chose (or can't be shown to be)."""


class RootsUnreadable(DriveError):
    """The owner's chosen-folder list can't be read (storage down, or corrupt): fail closed."""


@dataclass(frozen=True)
class DriveFile:
    """One Drive item as JARVIS's account sees it."""

    id: str
    name: str
    mime: str
    parents: tuple[str, ...] = ()
    trashed: bool = False
    size: int | None = None  # bytes; Google Docs/Sheets/Slides have none
    modified: str | None = None
    sharer: str | None = None  # sharingUser.emailAddress, lower-cased
    owners: tuple[str, ...] = ()  # owners[].emailAddress, lower-cased (none in shared drives)
    target_id: str | None = None  # a shortcut's target
    target_mime: str | None = None
    md5: str | None = None  # md5Checksum of a binary file (the DigiLocker import's change test)

    @property
    def is_folder(self) -> bool:
        return self.mime == FOLDER_MIME

    @property
    def is_shortcut(self) -> bool:
        return self.mime == SHORTCUT_MIME


@dataclass(frozen=True)
class Page:
    files: tuple[DriveFile, ...]
    next_token: str | None = None
    incomplete: bool = False


@runtime_checkable
class TokenSource(Protocol):
    """JARVIS's own access token for Drive (read-only scope) and its address."""

    async def token(self) -> str: ...

    def invalidate(self) -> None: ...

    async def email(self) -> str: ...

    async def aclose(self) -> None: ...


__all__ = [
    "DOC_MIME",
    "DRIVE_ID",
    "DRIVE_SCOPE",
    "FOLDER_MIME",
    "GOOGLE_PREFIX",
    "MAX_FILE_BYTES",
    "MAX_ROOTS",
    "SHEET_MIME",
    "SHORTCUT_MIME",
    "SLIDES_MIME",
    "DriveError",
    "DriveFile",
    "DriveNotFound",
    "DriveUnavailable",
    "NotInRoots",
    "Page",
    "RootsUnreadable",
    "TokenSource",
]
