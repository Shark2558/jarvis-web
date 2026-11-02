# src/jarvis/drive/service.py
"""Google Drive, chosen folders only — end to end (slice 12 D1; Layer 6 → 5).

Integrations (the owner, on screen):
  view(uid, owner_email)   JARVIS's address to share with; the folders shared with it BY THE OWNER
                           (sharingUser.emailAddress == the owner's verified address), each with
                           its Use switch; a count of folders shared by anyone else ("not offered:
                           shared by another account" — their address is never shown).
  set_use(uid, email, id, on)  Use on: the folder must be shared directly with JARVIS by the
                           owner's own address, right now (asked of Drive, not taken from the
                           browser). Use off: always allowed.

The tools (the model, inside a turn; every call is checked against the confirmed folders):
  folders(uid)             the confirmed folders (from storage only)
  list_folder(uid, f, page) one confirmed folder's direct contents, ≤ 25 a page
  search(uid, query)       Drive fullText, then only hits inside confirmed folders (≤ 10)
  read(uid, file, part)    one ~4,000-character part, fenced: Google Docs / Slides → text/plain,
                           Sheets → text/csv (Google exports the first sheet), PDF / DOCX / TXT /
                           MD / CSV ≤ 10 MB → the slice 10 sandboxed extractor (a killable child
                           process; one at a time). A shortcut is followed to its target, which
                           is checked again. Extracted text is kept in memory for 10 minutes
                           (≤ 8 files, keyed by id + modifiedTime), so part 2 doesn't download
                           again; nothing from Drive is stored.

Everything Drive returns — names included — is other people's words: fenced with the per-call
nonce (`jarvis.tools.external`), and the tools are untrusted (`trusted_output` False) so the round
is tainted. Errors are plain English (`DriveError` family); Google's text never appears.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.config import Settings
from jarvis.documents.chunking import pages_label, split
from jarvis.documents.extract import Limits
from jarvis.documents.isolation import Sandbox, extract_isolated
from jarvis.documents.limits import DocumentRejected
from jarvis.drive.client import DriveClient, check_id
from jarvis.drive.guard import NOT_IN_ROOTS, ParentsGuard, WalkBudget
from jarvis.drive.ports import (
    DOC_MIME,
    DRIVE_ID,
    FOLDER_MIME,
    GOOGLE_PREFIX,
    MAX_FILE_BYTES,
    SHEET_MIME,
    SLIDES_MIME,
    DriveError,
    DriveFile,
    DriveNotFound,
    NotInRoots,
)
from jarvis.drive.roots import RootsStore
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs
from jarvis.tools.external import wrap_external

log = get_logger(__name__)

LIST_PAGE = 25
SEARCH_LIMIT = 10
SEARCH_SCAN = 50  # Drive hits looked at before filtering to the chosen folders
SEARCH_LOOKUPS = 60  # uncached folder look-ups one search may make (the rest: not shown)
PART_CHARS = 4_000  # chunk cost (JSON characters) of one drive_read part
PART_TEXT_LIMIT = 6_000  # the fenced text after fence-like text is replaced (fits the gateway)
NAME_SHOWN = 120
TEXT_CACHE_S = 600.0
TEXT_CACHE_FILES = 8
QUEUE_WAIT_S = 50.0

EXPORTS = {DOC_MIME: "text/plain", SLIDES_MIME: "text/plain", SHEET_MIME: "text/csv"}
BLOBS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
    "text/csv": "csv",
}
_EXT = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "md", ".csv": "csv"}
KINDS = {
    FOLDER_MIME: "folder",
    DOC_MIME: "Google Doc",
    SHEET_MIME: "Google Sheet",
    SLIDES_MIME: "Google Slides",
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "text/plain": "text",
    "text/markdown": "Markdown",
    "text/csv": "CSV",
    "application/vnd.google-apps.shortcut": "shortcut",
}
UNSUPPORTED = (
    "JARVIS can read Google Docs, Sheets and Slides, and PDF, Word (.docx), text, Markdown and "
    "CSV files from Drive — not this kind of file."
)
FOLDER_NOT_FILE = "That is a folder: use drive_list to see what is in it."
BROKEN_SHORTCUT = "That shortcut points to something JARVIS can't open."
NOT_SET_UP = (
    "No Drive folders are switched on yet. The owner shares a folder with JARVIS and switches "
    "on Use in Integrations → Google Drive."
)
BUSY = "JARVIS is still reading another file. Try again in a minute."


class DriveRejected(ValueError):
    """An Integrations change that is not allowed (plain words for the owner)."""

    def __init__(self, code: str, detail: str, *, status: int = 422) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status


def kind_word(mime: str) -> str:
    return KINDS.get(mime) or ("Google file" if mime.startswith(GOOGLE_PREFIX) else "file")


def _blob_kind(f: DriveFile) -> str | None:
    if f.mime in BLOBS:
        return BLOBS[f.mime]
    low = f.name.lower()
    if f.mime in ("application/octet-stream", "") or f.mime.startswith("text/"):
        return next((k for ext, k in _EXT.items() if low.endswith(ext)), None)
    return None


@dataclass(frozen=True)
class _Text:
    chunks: tuple[str, ...]
    pages: tuple[tuple[int | None, int | None], ...]
    truncated: bool


def _name(f: DriveFile) -> str:
    return wrap_external(f.name, source="Google Drive name", limit=NAME_SHOWN)


def _item(f: DriveFile) -> dict[str, Any]:
    out: dict[str, Any] = {"id": f.id, "name": _name(f), "kind": kind_word(f.mime)}
    if f.modified:
        out["modified"] = f.modified[:10]
    if f.size is not None:
        out["size_kb"] = max(1, f.size // 1024)
    if f.is_shortcut and f.target_mime:
        out["points_to"] = kind_word(f.target_mime)
    return out


class DriveService:
    def __init__(
        self,
        client: DriveClient,
        roots: RootsStore,
        *,
        guard: ParentsGuard | None = None,
        sandbox: Sandbox | None = None,
        limits: Limits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.roots = roots
        self.guard = guard or ParentsGuard(client, clock=clock)
        self.sandbox = sandbox or Sandbox()
        self.limits = limits or Limits()
        self._clock = clock
        self._slot = asyncio.Semaphore(1)
        self._texts: OrderedDict[tuple[str, str], tuple[float, _Text]] = OrderedDict()

    async def aclose(self) -> None:
        await self.client.aclose()
        await self.client.tokens.aclose()

    async def _root_ids(self, uid: str) -> set[str]:
        return {r.id for r in await self.roots.load(uid)}

    # ---- Integrations ------------------------------------------------------------------------

    async def view(self, uid: str, owner_email: str | None) -> dict[str, Any]:
        email = await self.client.tokens.email()
        shared = await self.client.shared_folders()
        chosen = await self.roots.load(uid)
        mine = owner_email.strip().lower() if owner_email else None
        confirmed = {r.id for r in chosen}
        folders: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        for f in shared:
            if mine is not None and f.sharer == mine:
                folders.append(
                    {"id": f.id, "name": f.name, "confirmed": f.id in confirmed, "shared": True}
                )
            else:
                others.append({"name": f.name})
        offered = {f["id"] for f in folders}
        for r in chosen:  # chosen earlier, no longer shared with JARVIS (or by someone else now)
            if r.id not in offered:
                folders.append({"id": r.id, "name": r.name, "confirmed": True, "shared": False})
        return {
            "service_email": email,
            "folders": folders,
            "others": others,
            "max_folders": 20,
        }

    async def set_use(self, uid: str, owner_email: str | None, folder_id: str, on: bool) -> None:
        if not isinstance(folder_id, str) or not DRIVE_ID.fullmatch(folder_id):
            raise DriveRejected("bad_id", "That isn't a Google Drive folder id.")
        if not on:
            await self.roots.remove(uid, folder_id)
            self.guard.forget()
            return
        if not owner_email:
            raise DriveRejected(
                "no_owner_email",
                "Sign in with Google in the browser to choose Drive folders.",
                status=403,
            )
        shared = {f.id: f for f in await self.client.shared_folders()}
        f = shared.get(folder_id)
        if f is None:
            raise DriveRejected(
                "not_offered",
                "That folder isn't shared with JARVIS. Share it with JARVIS's address first.",
                status=409,
            )
        if f.sharer != owner_email.strip().lower():
            raise DriveRejected(
                "not_offered",
                "Not offered: that folder was shared with JARVIS by another account, not yours.",
                status=403,
            )
        try:
            await self.roots.confirm(uid, folder_id, f.name)
        except ValueError as exc:
            raise DriveRejected("too_many", str(exc), status=409) from None
        self.guard.forget()

    # ---- the tools -----------------------------------------------------------------------------

    async def folders(self, uid: str) -> dict[str, Any]:
        chosen = await self.roots.load(uid)
        if not chosen:
            return {"folders": [], "note": NOT_SET_UP}
        return {
            "folders": [
                {
                    "id": r.id,
                    "name": wrap_external(r.name, source="Google Drive name", limit=NAME_SHOWN),
                }
                for r in chosen
            ],
            "note": "Use drive_list with a folder id to see inside, drive_search to find files.",
        }

    async def _resolve(self, uid: str, file_id: str) -> DriveFile:
        """The item, checked; a shortcut is followed to its target, which is checked again."""
        roots = await self._root_ids(uid)
        item = await self.guard.check(file_id, roots)
        if item.is_shortcut:
            if item.target_id is None:
                raise DriveError(BROKEN_SHORTCUT)
            item = await self.guard.check(item.target_id, roots)
            if item.is_shortcut:
                raise DriveError(BROKEN_SHORTCUT)
        return item

    async def list_folder(
        self, uid: str, folder_id: str, page: str | None = None
    ) -> dict[str, Any]:
        folder = await self._resolve(uid, folder_id)
        if not folder.is_folder:
            raise DriveError("That is a file, not a folder: use drive_read to read it.")
        got = await self.client.children(folder.id, page_token=page, page_size=LIST_PAGE)
        return {
            "folder": folder.id,
            "folder_name": _name(folder),
            "items": [_item(f) for f in got.files],
            "next_page": got.next_token,
        }

    async def search(self, uid: str, query: str) -> dict[str, Any]:
        roots = await self._root_ids(uid)
        if not roots:
            return {"query": query, "results": [], "note": NOT_SET_UP}
        got = await self.client.search(query, page_size=SEARCH_SCAN)
        hits: list[dict[str, Any]] = []
        budget = WalkBudget(SEARCH_LOOKUPS)  # one search costs a bounded number of Drive calls
        for f in got.files:
            if len(hits) >= SEARCH_LIMIT:
                break
            if f.trashed or not await self.guard.inside(f, roots, budget):
                continue  # outside the chosen folders: never shown, not even its name
            hits.append(_item(f))
        note = (
            "Read one with drive_read and its id."
            if hits
            else "Nothing in the chosen folders matched. Try other words, or drive_list a folder."
        )
        return {"query": query, "results": hits, "note": note}

    async def read(self, uid: str, file_id: str, part: int = 1) -> dict[str, Any]:
        f = await self._resolve(uid, file_id)
        if f.is_folder:
            raise DriveError(FOLDER_NOT_FILE)
        text = await self._text(f)
        parts = max(1, len(text.chunks))
        if not 1 <= part <= parts:
            raise ValueError(f"part must be 1-{parts} for this file")
        body = text.chunks[part - 1].strip() if text.chunks else ""
        first, last = text.pages[part - 1] if text.pages else (None, None)
        pages = pages_label(first, last)
        source = f"Google Drive file, part {part} of {parts}" + (f", {pages}" if pages else "")
        return {
            "file": f.id,
            "name": _name(f),
            "kind": kind_word(f.mime),
            "part": part,
            "parts": parts,
            "pages": pages,
            "more": part < parts,
            "truncated": text.truncated,
            "text": wrap_external(body or "(no text)", source=source, limit=PART_TEXT_LIMIT),
        }

    # ---- text --------------------------------------------------------------------------------

    async def _text(self, f: DriveFile) -> _Text:
        key = (f.id, f.modified or "")
        hit = self._texts.get(key)
        if hit is not None and hit[0] > self._clock():
            self._texts.move_to_end(key)
            return hit[1]
        text = await self._fetch_text(f)
        self._texts[key] = (self._clock() + TEXT_CACHE_S, text)
        while len(self._texts) > TEXT_CACHE_FILES:
            self._texts.popitem(last=False)
        return text

    async def _fetch_text(self, f: DriveFile) -> _Text:
        if f.mime in EXPORTS:
            data = await self.client.export(f.id, EXPORTS[f.mime])
            kind = "csv" if EXPORTS[f.mime] == "text/csv" else "txt"
        else:
            blob = _blob_kind(f)
            if blob is None:
                raise DriveError(UNSUPPORTED)
            kind = blob
            if f.size is not None and f.size > MAX_FILE_BYTES:
                raise DriveError("That file is over 10 MB, so JARVIS can't read it.")
            data = await self.client.download(f.id)
        out = await self._extract(data, kind)
        chunks, cut = split(out.text, out.page_starts, cost=PART_CHARS)
        return _Text(
            tuple(c.text for c in chunks),
            tuple((c.page, c.page_end) for c in chunks),
            out.truncated or cut,
        )

    async def _extract(self, data: bytes, kind: str) -> Any:
        if not data:
            raise DriveError("That file is empty.")
        try:
            await asyncio.wait_for(self._slot.acquire(), QUEUE_WAIT_S)
        except TimeoutError:
            raise DriveError(BUSY) from None
        try:
            return await extract_isolated(data, kind, self.limits, self.sandbox)
        except DocumentRejected as exc:
            raise DriveError(str(exc)) from None  # the extractor's words are our own
        finally:
            self._slot.release()


# ---- wiring (the app) --------------------------------------------------------------------------


def drive_configured(s: Settings) -> bool:
    return bool(s.drive)


def build_drive_service(s: Settings, docs: Docs) -> DriveService | None:
    """None unless `JARVIS_DRIVE=on`: then no tools, and /v1/drive says not configured. No
    network here: the token and address are fetched on first use."""
    if not drive_configured(s):
        return None
    from jarvis.drive.token import MetadataTokens

    return DriveService(DriveClient(MetadataTokens()), RootsStore(docs, prefix=s.firestore_prefix))


__all__ = [
    "NOT_IN_ROOTS",
    "NOT_SET_UP",
    "DriveNotFound",
    "DriveRejected",
    "DriveService",
    "NotInRoots",
    "build_drive_service",
    "check_id",
    "drive_configured",
    "kind_word",
]
