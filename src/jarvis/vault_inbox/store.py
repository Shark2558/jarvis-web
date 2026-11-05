# src/jarvis/vault_inbox/store.py
"""The DigiLocker import folder and what was already looked at (R2 D9; Layer 7) on the `Docs` port.

    {prefix}vault_inbox/{uid}   {folder_id, name, email, confirmed_at, last_check_at, last_error,
                                 imported_total, seen: {drive_id: {v, item, skip, at}}, updated_at}

Not encrypted: it holds a Drive folder id and its name (the owner's own label), the owner's
address (as the Drive roots do), Drive ids with a change key (`md5Checksum`, else modified time and
size) and an item id or a skip reason. A file's NAME is never stored; neither is anything from
inside a file. `seen` keeps the newest MAX_SEEN entries.

Reads fail closed: storage trouble or an odd document is `InboxUnreadable` (the Drive tools then
read nothing, because the inbox id cannot be told); a write is a transaction and never overwrites
a document it could not read.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from jarvis.drive.ports import DRIVE_ID
from jarvis.drive.roots import owner_address
from jarvis.logging import get_logger
from jarvis.storage.docs import Doc, Docs, DocTx
from jarvis.tools.card import one_line
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

MAX_SEEN = 500
NAME_LIMIT = 200
WHY_LIMIT = 160
VERSION_LIMIT = 120
UNREADABLE = "JARVIS couldn't read the DigiLocker import settings just now. Try again in a minute."
UNSAVED = "JARVIS couldn't save the DigiLocker import settings just now. Try again in a minute."
_ITEM = re.compile(r"v_[0-9a-f]{12}")


class InboxUnreadable(RuntimeError):
    """The import folder record can't be read or saved (plain words)."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Seen:
    """What was decided about one Drive file at one version of it."""

    version: str
    item_id: str | None = None
    skip: str | None = None  # plain words; never a file name
    at: str = ""


@dataclass(frozen=True)
class Inbox:
    folder_id: str
    name: str
    email: str
    confirmed_at: datetime
    last_check_at: datetime | None = None
    last_error: str | None = None
    imported_total: int = 0
    seen: dict[str, Seen] = field(default_factory=dict)

    def with_seen(self, drive_id: str, entry: Seen) -> Inbox:
        merged = {k: v for k, v in self.seen.items() if k != drive_id}
        merged[drive_id] = entry  # newest last
        while len(merged) > MAX_SEEN:
            del merged[next(iter(merged))]
        return replace(self, seen=merged)


def _when(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise ValueError("time")
    when = datetime.fromisoformat(raw)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _decode_seen(raw: object) -> dict[str, Seen]:
    if not isinstance(raw, dict) or len(raw) > MAX_SEEN:
        raise ValueError("seen")
    out: dict[str, Seen] = {}
    for did, e in raw.items():
        if not isinstance(did, str) or not DRIVE_ID.fullmatch(did) or not isinstance(e, dict):
            raise ValueError("seen entry")
        v, item, skip, at = e.get("v"), e.get("item"), e.get("skip"), e.get("at", "")
        if not isinstance(v, str) or len(v) > VERSION_LIMIT or not isinstance(at, str):
            raise ValueError("seen fields")
        if item is not None and not (isinstance(item, str) and _ITEM.fullmatch(item)):
            raise ValueError("seen item")
        if skip is not None and not (isinstance(skip, str) and len(skip) <= WHY_LIMIT):
            raise ValueError("seen skip")
        out[did] = Seen(v, item, skip, at)
    return out


def decode(doc: Doc | None) -> Inbox | None:
    if doc is None:
        return None
    fid, name = doc.get("folder_id"), doc.get("name")
    if not isinstance(fid, str) or not DRIVE_ID.fullmatch(fid):
        raise ValueError("folder")
    if not isinstance(name, str) or len(name) > NAME_LIMIT:
        raise ValueError("name")
    last = doc.get("last_check_at")
    error = doc.get("last_error")
    total = doc.get("imported_total", 0)
    if error is not None and not (isinstance(error, str) and len(error) <= 400):
        raise ValueError("error")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError("total")
    return Inbox(
        folder_id=fid,
        name=name,
        email=owner_address(doc.get("email")),
        confirmed_at=_when(doc.get("confirmed_at")),
        last_check_at=None if last is None else _when(last),
        last_error=error,
        imported_total=total,
        seen=_decode_seen(doc.get("seen", {})),
    )


def encode(box: Inbox, now: datetime) -> Doc:
    seen = {
        did: {"v": s.version, "item": s.item_id, "skip": s.skip, "at": s.at}
        for did, s in box.seen.items()
    }
    return {
        "folder_id": box.folder_id,
        "name": one_line(box.name, NAME_LIMIT) or "(no name)",
        "email": box.email,
        "confirmed_at": box.confirmed_at.isoformat(),
        "last_check_at": None if box.last_check_at is None else box.last_check_at.isoformat(),
        "last_error": box.last_error,
        "imported_total": box.imported_total,
        "seen": seen,
        "updated_at": now.isoformat(),
    }


class InboxStore:
    def __init__(
        self, docs: Docs, *, prefix: str = "jarvis_", now: Callable[[], datetime] = _utcnow
    ) -> None:
        self._d = docs
        self._col = f"{prefix}vault_inbox"
        self._now = now

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._col}/{uid}"

    async def load(self, uid: str) -> Inbox | None:
        path = self._path(uid)
        try:
            return decode(await self._d.get(path))
        except Exception as exc:  # noqa: BLE001 - storage or data trouble: read nothing
            log.warning("vault inbox unreadable", extra={"reason": type(exc).__name__})
            raise InboxUnreadable(UNREADABLE) from None

    async def change(self, uid: str, fn: Callable[[Inbox | None], Inbox | None]) -> Inbox | None:
        """Read, change, write in one transaction. `fn` returns the new record, or None to remove
        it. A document that can't be read is never overwritten."""
        path = self._path(uid)

        async def tx(t: DocTx) -> Inbox | None:
            try:
                current = decode(await t.get(path))
            except ValueError:
                log.warning("vault inbox corrupt; refusing to change it")
                raise InboxUnreadable(UNREADABLE) from None
            updated = fn(current)
            if updated is None:
                t.delete(path)
            else:
                t.set(path, encode(updated, self._now()))
            return updated

        try:
            return await self._d.transaction(tx)
        except InboxUnreadable:
            raise
        except Exception as exc:  # noqa: BLE001 - nothing changed; say so
            log.warning("vault inbox change failed", extra={"reason": type(exc).__name__})
            raise InboxUnreadable(UNSAVED) from None

    async def folder_id(self, uid: str) -> str | None:
        """The inbox folder's id (what the Drive guard refuses to read through), or None."""
        box = await self.load(uid)
        return None if box is None else box.folder_id


__all__ = [
    "MAX_SEEN",
    "Inbox",
    "InboxStore",
    "InboxUnreadable",
    "Seen",
    "decode",
    "encode",
]
