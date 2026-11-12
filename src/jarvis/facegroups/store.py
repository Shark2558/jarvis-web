# src/jarvis/facegroups/store.py
"""What the cloud remembers about the laptop's face groups (R11.1 O7; plan D15, D21-C).

    {prefix}face_groups/{uid}   {groups: [{id, n, photos, first, last}], strays, named, engine,
                                 store, folder, read, skipped, keep_days, heard_at, told: [ids
                                 already announced], forget: [ids to forget when the laptop is
                                 back], forget_all, lost: [names the laptop could not take]}

Ids and counts only, in plain fields: never a face, a crop, an embedding or a name. It is a copy
of the laptop's last answer (so the panel has something to show while the laptop sleeps) plus the
owner's own pending asks. The laptop stays the source of truth.

Every change is `update(uid, change)`: the document is read and written in ONE transaction and
`change` is applied to what is there at that moment (review C-code M3), so a "forget" asked while
the laptop was being called is never overwritten by a copy read before it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from jarvis.photos.models import CLUSTER_ID, GroupAtHome, GroupsAtHome
from jarvis.storage.docs import Delete, Docs, DocTx
from jarvis.undo.store import owner_ok

MAX_GROUPS = 100
MAX_IDS = 200
FOLDERS = ("off", "on", "unreadable")


@dataclass(frozen=True)
class GroupsDoc:
    home: GroupsAtHome = GroupsAtHome()
    heard_at: str = ""  # when the laptop last answered ("" = never)
    told: tuple[str, ...] = ()
    forget: tuple[str, ...] = ()
    forget_all: bool = False
    lost: int = 0  # names given while the laptop slept whose group had gone (told to the owner)

    @property
    def shown(self) -> tuple[GroupAtHome, ...]:
        """The groups the owner still sees: not the ones he asked to forget."""
        if self.forget_all:
            return ()
        waiting = set(self.forget)
        return tuple(g for g in self.home.groups if g.id not in waiting)

    @property
    def kept(self) -> int:
        """Unnamed groups and stray faces the laptop holds, as last heard (pending or not)."""
        return len(self.home.groups) + self.home.more + self.home.strays


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _ids(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(i for i in raw if isinstance(i, str) and CLUSTER_ID.fullmatch(i))[:MAX_IDS]


def _group(raw: object) -> GroupAtHome | None:
    if not isinstance(raw, dict):
        return None
    gid = raw.get("id")
    if not isinstance(gid, str) or not CLUSTER_ID.fullmatch(gid):
        return None
    return GroupAtHome(
        gid,
        _count(raw.get("n")),
        _count(raw.get("photos")),
        _count(raw.get("first")),
        _count(raw.get("last")),
    )


class GroupsStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}face_groups"

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> GroupsDoc:
        return _parse(await self._d.get(self._path(uid)))

    async def update(self, uid: str, change: Callable[[GroupsDoc], GroupsDoc]) -> GroupsDoc:
        """Read, change and write the document in one transaction. Returns what was written."""
        path = self._path(uid)

        async def tx(t: DocTx) -> GroupsDoc:
            raw = await t.get(path)
            new = change(_parse(raw))
            body = dict(raw) if isinstance(raw, dict) else {}
            body.update(_body(new))  # fields this module does not know are kept
            t.set(path, body)
            return new

        return await self._d.transaction(tx)

    async def claim_told(self, uid: str, ids: Sequence[str]) -> tuple[str, ...]:
        """Mark these groups as announced, in one transaction, and return the ones that were
        not announced before: a group is told once, however many clocks tick at once."""
        path = self._path(uid)

        async def tx(t: DocTx) -> tuple[str, ...]:
            raw = await t.get(path)
            body = dict(raw) if isinstance(raw, dict) else {}
            told = list(_ids(body.get("told")))
            fresh = tuple(i for i in dict.fromkeys(ids) if i not in told)
            if fresh:
                body["told"] = [*told, *fresh][-MAX_IDS:]
                t.set(path, body)
            return fresh

        return await self._d.transaction(tx)

    async def delete(self, uid: str) -> None:
        await self._d.write([Delete(self._path(uid))])


def _parse(raw: object) -> GroupsDoc:
    if not isinstance(raw, dict):
        return GroupsDoc()
    rows = raw.get("groups")
    groups = tuple(g for g in (_group(r) for r in (rows if isinstance(rows, list) else [])) if g)
    folder = raw.get("folder")
    days = _count(raw.get("keep_days"))
    home = GroupsAtHome(
        groups[:MAX_GROUPS],
        _count(raw.get("more")),
        _count(raw.get("strays")),
        _count(raw.get("named")),
        raw.get("engine") is True,
        folder if folder in FOLDERS else "off",
        _count(raw.get("read")),
        days if 1 <= days <= 3650 else 90,
        skipped=_count(raw.get("skipped")),
        store_ok=raw.get("store") is not False,
    )
    heard = raw.get("heard_at")
    return GroupsDoc(
        home,
        heard if isinstance(heard, str) and len(heard) <= 40 else "",
        _ids(raw.get("told")),
        _ids(raw.get("forget")),
        raw.get("forget_all") is True,
        _count(raw.get("lost")),
    )


def _body(doc: GroupsDoc) -> dict[str, Any]:
    h = doc.home
    return {
        "groups": [
            {"id": g.id, "n": g.n, "photos": g.photos, "first": g.first, "last": g.last}
            for g in h.groups[:MAX_GROUPS]
        ],
        "more": h.more,
        "strays": h.strays,
        "named": h.named,
        "engine": h.engine_ready,
        "store": h.store_ok,
        "folder": h.folder,
        "read": h.read,
        "skipped": h.skipped,
        "keep_days": h.keep_days,
        "heard_at": doc.heard_at,
        "told": list(doc.told[-MAX_IDS:]),
        "forget": list(doc.forget[-MAX_IDS:]),
        "forget_all": doc.forget_all,
        "lost": doc.lost,
    }


__all__ = ["GroupsDoc", "GroupsStore"]
