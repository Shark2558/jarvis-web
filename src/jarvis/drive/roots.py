# src/jarvis/drive/roots.py
"""The owner's chosen Drive folders (slice 12 D1; Layer 7) on the `Docs` port.

    {prefix}drive_roots/{uid}   {roots: [{id, name, confirmed_at}], updated_at}   (≤ 20 roots)

A folder gets here only through the owner's own "Use" switch in Integrations, and only when the
account that shared it with JARVIS is the owner's verified address (`DriveService.set_use`).
Reads fail closed: storage trouble, a missing field, a wrong type, an odd id or more than 20
entries is `RootsUnreadable` — JARVIS then reads nothing from Drive until it can tell again.
Writes are transactions (read, change, write), so two windows can't lose each other's change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jarvis.drive.ports import DRIVE_ID, MAX_ROOTS, RootsUnreadable
from jarvis.logging import get_logger
from jarvis.storage.docs import Doc, Docs, DocTx
from jarvis.tools.card import one_line
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

NAME_LIMIT = 200
UNREADABLE = (
    "JARVIS couldn't read your chosen Drive folders just now, so nothing was read from Drive. "
    "Try again in a minute."
)
FULL = f"At most {MAX_ROOTS} Drive folders can be in use. Switch one off first."


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Root:
    id: str
    name: str
    confirmed_at: datetime


def _decode(doc: Doc | None) -> list[Root]:
    """The stored list, every entry re-checked (raises ValueError on anything odd)."""
    if doc is None:
        return []
    raw = doc.get("roots")
    if not isinstance(raw, list) or len(raw) > MAX_ROOTS:
        raise ValueError("roots")
    out: list[Root] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("entry")
        rid, name, at = item.get("id"), item.get("name"), item.get("confirmed_at")
        if not isinstance(rid, str) or not DRIVE_ID.fullmatch(rid):
            raise ValueError("id")
        if not isinstance(name, str) or len(name) > NAME_LIMIT:
            raise ValueError("name")
        if not isinstance(at, str):
            raise ValueError("confirmed_at")
        when = datetime.fromisoformat(at)
        out.append(Root(rid, name, when if when.tzinfo else when.replace(tzinfo=UTC)))
    if len({r.id for r in out}) != len(out):
        raise ValueError("duplicate")
    return out


def _encode(roots: list[Root], now: datetime) -> Doc:
    return {
        "roots": [
            {"id": r.id, "name": r.name, "confirmed_at": r.confirmed_at.isoformat()} for r in roots
        ],
        "updated_at": now.isoformat(),
    }


class RootsStore:
    def __init__(
        self, docs: Docs, *, prefix: str = "jarvis_", now: Callable[[], datetime] = _utcnow
    ) -> None:
        self._d = docs
        self._col = f"{prefix}drive_roots"
        self._now = now

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._col}/{uid}"

    async def load(self, uid: str) -> list[Root]:
        path = self._path(uid)
        try:
            return _decode(await self._d.get(path))
        except Exception as exc:  # noqa: BLE001 — storage or data trouble: read nothing
            log.warning("drive roots unreadable", extra={"reason": type(exc).__name__})
            raise RootsUnreadable(UNREADABLE) from None

    async def _change(self, uid: str, fn: Callable[[list[Root]], list[Root]]) -> list[Root]:
        path = self._path(uid)

        async def tx(t: DocTx) -> list[Root]:
            try:
                current = _decode(await t.get(path))
            except ValueError:
                log.warning("drive roots corrupt; refusing to change them")
                raise RootsUnreadable(UNREADABLE) from None
            updated = fn(current)
            t.set(path, _encode(updated, self._now()))
            return updated

        return await self._d.transaction(tx)

    async def confirm(self, uid: str, folder_id: str, name: str) -> list[Root]:
        """Add (or rename) a chosen folder. Raises ValueError past 20."""
        if not DRIVE_ID.fullmatch(folder_id):
            raise ValueError("not a Drive id")
        label = one_line(name, NAME_LIMIT) or "(no name)"

        def add(current: list[Root]) -> list[Root]:
            kept = [r for r in current if r.id != folder_id]
            if len(kept) >= MAX_ROOTS:
                raise ValueError(FULL)
            old = next((r for r in current if r.id == folder_id), None)
            at = old.confirmed_at if old is not None else self._now()
            return (
                [*kept, Root(folder_id, label, at)]
                if old is None
                else [
                    Root(r.id, label, r.confirmed_at) if r.id == folder_id else r for r in current
                ]
            )

        return await self._change(uid, add)

    async def remove(self, uid: str, folder_id: str) -> list[Root]:
        return await self._change(uid, lambda cur: [r for r in cur if r.id != folder_id])


def describe(roots: list[Root]) -> list[dict[str, Any]]:
    return [{"id": r.id, "name": r.name, "confirmed_at": r.confirmed_at.isoformat()} for r in roots]


__all__ = ["FULL", "UNREADABLE", "Root", "RootsStore", "describe"]
