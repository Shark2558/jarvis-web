# src/jarvis/vault_inbox/service.py
"""The DigiLocker import folder (R2 D9; Layer 6 Drive -> Layer 7 vault).

DigiLocker's partner APIs are for registered organisations, so the owner downloads a document in
the DigiLocker app and shares it to a Drive folder he shares with JARVIS's address (Viewer). That
folder is the **vault inbox**, a role separate from Drive "Use":

    view(uid, email)   the folder (if any), the owner's folders offered for it, the last check,
                       totals and the reasons files were skipped. Plain words for every off state.
    pick(uid, email, id)  must be the owner's own folder (`jarvis.drive.live.problem`, the slice 12
                       ownership test), not ticked Use and not inside a Use folder (parents walked).
    clear(uid)         switch the import off (the seen list goes too; nothing in Drive changes).
    check(uid)         import now: the folder's direct children (<= 4 pages of 25); a new Drive id,
                       or one whose md5Checksum (else modified time and size) changed, that is a
                       PDF / JPEG / PNG <= 10 MB is downloaded and handed to `VaultIntake`
                       (<= 3 downloads and <= 60 s a run; the rest next time). Other files are
                       skipped with a reason and not looked at again until they change.

No Drive call is made while no folder is picked. The folder is re-checked at the start of every
run: no longer shared, no longer the owner's, in the trash or now inside a Use folder -> imports
stop, with words. Drive file names are never stored, logged or returned; the Drive tools can never
read the inbox (`DriveService(inbox=...)`, `ParentsGuard.check(deny=...)`). The copies stay in
Drive: JARVIS is read-only there.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jarvis.drive.client import check_id
from jarvis.drive.live import problem
from jarvis.drive.ports import (
    DRIVE_ID,
    DriveError,
    DriveFile,
    DriveNotFound,
    DriveUnavailable,
    RootsUnreadable,
)
from jarvis.drive.roots import owner_address
from jarvis.drive.service import DriveRejected, DriveService
from jarvis.logging import get_logger
from jarvis.vault.ports import MAX_FILE_BYTES, VAULT_MIMES, IntakeResult, VaultIntake
from jarvis.vault_inbox.store import Inbox, InboxStore, Seen

log = get_logger(__name__)

MAX_PER_RUN = 3
RUN_BUDGET_S = 55.0  # inside the tick's own 60 s cap
LIST_PAGES = 4
LIST_PAGE = 25
SKIPS_SHOWN = 5

NOT_SET_UP = "Drive isn't set up on this server."
PICK_STEPS = (
    "In Google Drive make a folder (for example 'JARVIS Vault inbox') and share it with JARVIS's "
    "address as Viewer. Then pick it here. In the DigiLocker app, share a document to that folder."
)
IMPORTED_NOTE = "Imported. You can delete the copy in Drive now; JARVIS keeps an encrypted one."
VAULT_OFF = "The vault isn't available on this server, so nothing is imported."
IN_USE = "Pick a folder outside the folders JARVIS reads for you."
WHY_UNSUPPORTED = "Only PDF, JPEG and PNG files are imported."
WHY_TOO_BIG = "Over 10 MB, so it wasn't imported."
WHY_DUPLICATE = "Already in your vault."
WHY_UNREADABLE = "JARVIS couldn't download it."
WHY_IMPORT_FAILED = "JARVIS couldn't import it."
WHY_NOT_YOURS = "Not yours: it isn't owned by your account."
LIST_ORDER = "createdTime desc"  # newest first, so a new file is never behind 100 old ones
ERRORS = {
    "gone": "JARVIS can no longer see the import folder (it was un-shared or deleted). "
    "Imports have stopped.",
    "trashed": "The import folder is in the Drive trash. Imports have stopped.",
    "not_folder": "The import folder is no longer a folder. Imports have stopped.",
    "not_owner": "The import folder is no longer shared from your account. Imports have stopped.",
    "in_use": (
        "The import folder is now inside a folder JARVIS reads for you. Imports have stopped."
    ),
    "drive": "Google Drive couldn't be reached. JARVIS will try again.",
    "failed": "The check didn't finish. JARVIS will try again.",
}
_REFUSED = {
    "gone": (
        "not_offered",
        "That folder isn't shared with JARVIS. Share it with JARVIS's address first.",
        409,
    ),
    "trashed": ("not_offered", "That folder is in the trash in Google Drive.", 409),
    "not_folder": ("not_a_folder", "That isn't a folder. Share a folder, then pick it.", 422),
    "not_owner": (
        "not_owner",
        "Not offered: that folder was shared with JARVIS by another account, not yours.",
        403,
    ),
}
# Intake answers that are about this moment, not about the file: try the file again next run.
RETRY_CODES = frozenset({"unavailable", "vault_full", "busy"})


@dataclass
class CheckResult:
    imported: int = 0
    skipped: int = 0
    more: bool = False
    note: str = ""
    stopped: str | None = None  # a plain-words reason imports stopped (the folder is gone, ...)

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "imported": self.imported,
            "skipped": self.skipped,
            "more": self.more,
        }
        if self.note:
            out["note"] = self.note
        if self.stopped:
            out["stopped"] = self.stopped
        return out


@dataclass
class _Run:
    box: Inbox
    result: CheckResult = field(default_factory=CheckResult)
    downloads: int = 0
    listing_cut: bool = False  # the folder has more files than one run lists


def _version(f: DriveFile) -> str:
    """What "changed" means for a file: its md5Checksum, else modified time and size."""
    return (
        f"md5:{f.md5.lower()}"
        if f.md5
        else f"mod:{f.modified or '-'}:{f.size if f.size is not None else '-'}"
    )


def _owned_by(f: DriveFile, email: str) -> bool:
    """Only files the owner's own account owns are imported: an editor of the folder can drop a
    file in, but cannot make the owner own it. Shared-drive files (no owners) need the sharer."""
    mine = email.strip().lower()
    return mine in f.owners if f.owners else f.sharer == mine


def _address(value: str | None) -> str | None:
    try:
        return owner_address(value)
    except ValueError:
        return None


class InboxService:
    def __init__(
        self,
        drive: DriveService,
        store: InboxStore,
        intake: VaultIntake,
        *,
        review_count: Callable[[str], Awaitable[int]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.drive = drive
        self.store = store
        self.intake = intake
        self._review = review_count
        self._clock = clock
        self._mono = monotonic
        self._locks: dict[str, asyncio.Lock] = {}

    async def folder_id(self, uid: str) -> str | None:
        """The `DriveService(inbox=...)` source: the inbox id Drive tools must never read."""
        return await self.store.folder_id(uid)

    # ---- the owner's panel ---------------------------------------------------------------------

    async def view(self, uid: str, owner_email: str | None) -> dict[str, Any]:
        box = await self.store.load(uid)
        out: dict[str, Any] = {
            "available": True,
            "configured": box is not None,
            "folder": None,
            "offered": [],
            "last_check_at": None,
            "imported_total": 0,
            "waiting_review": await self._waiting(uid) if box is not None else 0,
            "skipped": [],
            "note": PICK_STEPS,
        }
        if box is None:
            out["offered"] = await self._offered(uid, owner_email)
            return out
        stopped = await self._stopped(uid, box)
        skips = sorted(
            ((s.at, s.skip) for s in box.seen.values() if s.skip), key=lambda p: p[0], reverse=True
        )
        out.update(
            folder={"id": box.folder_id, "name": box.name},
            last_check_at=box.last_check_at.isoformat() if box.last_check_at else None,
            imported_total=box.imported_total,
            skipped=[{"why": why, "at": at} for at, why in skips[:SKIPS_SHOWN]],
            note=stopped or box.last_error or IMPORTED_NOTE,
        )
        return out

    async def _waiting(self, uid: str) -> int:
        if self._review is None:
            return 0
        try:
            return max(0, int(await self._review(uid)))
        except Exception as exc:  # noqa: BLE001 - a count only
            log.warning("inbox review count failed", extra={"reason": type(exc).__name__})
            return 0

    async def _offered(self, uid: str, owner_email: str | None) -> list[dict[str, str]]:
        """The owner's own shared folders that could be the inbox (not a Use folder)."""
        mine = _address(owner_email)
        if mine is None:
            return []
        roots = {r.id for r in await self.drive.roots.load(uid)}
        folders = await self.drive.offered_folders(owner_email)
        return [{"id": f.id, "name": f.name} for f in folders if f.id not in roots]

    async def _stopped(self, uid: str, box: Inbox) -> str | None:
        """Why imports can't run now (a fresh look at the folder), or None."""
        try:
            return await self._problem(uid, box)
        except DriveError:
            return ERRORS["drive"]

    async def pick(self, uid: str, owner_email: str | None, folder_id: str) -> None:
        if not isinstance(folder_id, str) or not DRIVE_ID.fullmatch(folder_id):
            raise DriveRejected("bad_id", "That isn't a Google Drive folder id.")
        mine = _address(owner_email)
        if mine is None:
            raise DriveRejected(
                "no_owner_email",
                "Sign in with Google in the browser to choose the import folder.",
                status=403,
            )
        try:
            f: DriveFile | None = await self.drive.client.get(check_id(folder_id))
        except DriveNotFound:
            f = None
        why = problem(f, folder_id, mine, self.drive.checks.owns)
        if why or f is None:
            code, detail, status = _REFUSED.get(why, _REFUSED["gone"])
            raise DriveRejected(code, detail, status=status)
        if await self._in_use(uid, f):
            raise DriveRejected("in_use_folder", IN_USE, status=409)
        now = self._clock()
        await self.store.change(uid, lambda _old: Inbox(f.id, f.name, mine, now))
        self.drive.guard.forget()

    async def clear(self, uid: str) -> None:
        await self.store.change(uid, lambda _old: None)
        self.drive.guard.forget()

    async def export(self, uid: str) -> dict[str, Any] | None:
        box = await self.store.load(uid)
        if box is None:
            return None
        return {
            "folder_id": box.folder_id,
            "name": box.name,
            "confirmed_at": box.confirmed_at.isoformat(),
            "last_check_at": box.last_check_at.isoformat() if box.last_check_at else None,
            "imported_total": box.imported_total,
            "seen": {
                did: {"item": s.item_id, "skip": s.skip, "at": s.at} for did, s in box.seen.items()
            },
        }

    async def _in_use(self, uid: str, folder: DriveFile) -> bool:
        roots = {r.id for r in await self.drive.roots.load(uid)}
        return bool(roots) and await self.drive.guard.inside(folder, roots)

    # ---- importing -----------------------------------------------------------------------------

    def _lock(self, uid: str) -> asyncio.Lock:
        return self._locks.setdefault(uid, asyncio.Lock())

    async def check(self, uid: str) -> CheckResult:
        """Import what is new, now. No folder picked: nothing happens (no Drive call)."""
        async with self._lock(uid):
            box = await self.store.load(uid)
            if box is None:
                return CheckResult()
            run = _Run(box)
            try:
                await self._run(uid, run)
            except DriveUnavailable:
                run.result.stopped = ERRORS["drive"]
            except (DriveError, RootsUnreadable) as exc:
                log.warning("inbox check failed", extra={"reason": type(exc).__name__})
                run.result.stopped = ERRORS["drive"]
            except Exception as exc:  # noqa: BLE001 - never lose the run's record
                log.error("inbox check broke", extra={"reason": type(exc).__name__})
                run.result.stopped = ERRORS["failed"]
            finally:
                await self._finish(uid, run)
            return run.result

    async def _run(self, uid: str, run: _Run) -> None:
        why = await self._problem(uid, run.box)
        if why:
            run.result.stopped = why
            return
        deadline = self._mono() + RUN_BUDGET_S
        files, run.listing_cut = await self._children(run.box.folder_id)
        run.result.more = run.listing_cut
        for f in files:
            seen = run.box.seen.get(f.id)
            if seen is not None and seen.version == _version(f):
                continue
            if run.downloads >= MAX_PER_RUN or self._mono() >= deadline:
                run.result.more = True
                return
            await self._one(uid, run, f)
            if run.result.stopped:
                return

    async def _problem(self, uid: str, box: Inbox) -> str | None:
        """Is the folder still the owner's, shared, a live folder and outside the Use folders?"""
        try:
            f: DriveFile | None = await self.drive.client.get(box.folder_id)
        except DriveNotFound:
            f = None
        code = problem(f, box.folder_id, box.email, self.drive.checks.owns)
        if code:
            return ERRORS[code]
        assert f is not None
        return ERRORS["in_use"] if await self._in_use(uid, f) else None

    async def _children(self, folder_id: str) -> tuple[list[DriveFile], bool]:
        """The folder's files, newest first, and whether more remain than were listed."""
        out: list[DriveFile] = []
        token: str | None = None
        for _ in range(LIST_PAGES):
            page = await self.drive.client.children(
                folder_id, page_token=token, page_size=LIST_PAGE, order_by=LIST_ORDER
            )
            out.extend(f for f in page.files if not f.is_folder and not f.is_shortcut)
            token = page.next_token
            if token is None:
                break
        return out, token is not None

    def _skip(self, run: _Run, f: DriveFile, why: str) -> None:
        run.box = run.box.with_seen(f.id, Seen(_version(f), None, why, self._clock().isoformat()))
        run.result.skipped += 1

    async def _one(self, uid: str, run: _Run, f: DriveFile) -> None:
        if f.mime not in VAULT_MIMES:
            return self._skip(run, f, WHY_UNSUPPORTED)
        if f.size is not None and f.size > MAX_FILE_BYTES:
            return self._skip(run, f, WHY_TOO_BIG)
        if not _owned_by(f, run.box.email):
            return self._skip(run, f, WHY_NOT_YOURS)
        run.downloads += 1
        try:
            data = await self.drive.client.download(f.id)
        except DriveUnavailable:
            raise
        except DriveError:  # this file only: not tried again until it changes
            return self._skip(run, f, WHY_UNREADABLE)
        try:
            got = await self.intake.intake(uid, data, source="digilocker", drive_id=f.id)
        except Exception as exc:  # noqa: BLE001 - this file only; the others still go in
            log.warning("inbox intake failed", extra={"reason": type(exc).__name__})
            return self._skip(run, f, WHY_IMPORT_FAILED)
        self._record(run, f, got)

    def _record(self, run: _Run, f: DriveFile, got: IntakeResult) -> None:
        at = self._clock().isoformat()
        if got.status == "added":
            run.box = run.box.with_seen(f.id, Seen(_version(f), got.item_id, None, at))
            run.box = _bump(run.box)
            run.result.imported += 1
        elif got.status == "duplicate":
            run.box = run.box.with_seen(f.id, Seen(_version(f), got.item_id, WHY_DUPLICATE, at))
            run.result.skipped += 1
        elif got.code in RETRY_CODES:  # not the file's fault: no record, try again next run
            run.result.stopped = got.message or VAULT_OFF
        else:
            self._skip(run, f, got.message or WHY_UNSUPPORTED)

    async def _finish(self, uid: str, run: _Run) -> None:
        """Save what the run learned (the checks already made are not repeated)."""
        box, result = run.box, run.result
        error = result.stopped
        now = self._clock()

        def save(cur: Inbox | None) -> Inbox | None:
            if cur is None or cur.folder_id != box.folder_id:
                return cur  # switched off or changed meanwhile: leave that as it is
            return Inbox(
                cur.folder_id,
                cur.name,
                cur.email,
                cur.confirmed_at,
                now,
                error,
                box.imported_total,
                box.seen,
            )

        await self.store.change(uid, save)


def _bump(box: Inbox) -> Inbox:
    return Inbox(
        box.folder_id,
        box.name,
        box.email,
        box.confirmed_at,
        box.last_check_at,
        box.last_error,
        box.imported_total + 1,
        box.seen,
    )


__all__ = [
    "ERRORS",
    "IMPORTED_NOTE",
    "MAX_PER_RUN",
    "NOT_SET_UP",
    "CheckResult",
    "InboxService",
]
