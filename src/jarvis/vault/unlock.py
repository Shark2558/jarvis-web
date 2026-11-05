# src/jarvis/vault/unlock.py
"""The vault unlock window and single-use download tickets (R2 D6).

`vault_unlocks/{uid}` = {grants: [{mac, until}], tickets: [{mac, item, fid, until}]}. A token or
ticket is 32 random bytes shown once; only an HMAC (keyring purpose `tickets`) is stored, so a
Firestore read reveals nothing usable. At most 3 live grants and 5 live tickets (the oldest go). A
ticket lives 60 seconds, is bound to the owner (by its document), one item and one file (or
"export"), and is removed the moment it is taken: a used ticket in a request log is worthless.
"""

from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.keyring import Keyring
from jarvis.storage.docs import Docs, DocTx

MAX_GRANTS = 3
MAX_TICKETS = 5
TICKET_S = 60
EXPORT = "export"


class TicketGone(Exception):
    """The ticket was used, expired or never existed (410). One answer for all three."""


@dataclass(frozen=True)
class Grant:
    token: str
    until: dt.datetime


@dataclass(frozen=True)
class Ticket:
    ticket: str
    expires_in_s: int


@dataclass(frozen=True)
class Taken:
    item: str | None
    fid: str


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class UnlockStore:
    def __init__(
        self,
        docs: Docs,
        ring: Keyring,
        *,
        minutes: int = 10,
        prefix: str = "jarvis_",
        clock: Callable[[], dt.datetime] = _utcnow,
    ) -> None:
        self._d = docs
        self._ring = ring
        self._minutes = minutes
        self._col = f"{prefix}vault_unlocks"
        self._clock = clock

    @property
    def minutes(self) -> int:
        return self._minutes

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    def _mac(self, secret: str) -> str:
        return self._ring.mac("tickets", secret)

    def _live(self, rows: Any, now: dt.datetime) -> list[dict[str, Any]]:
        out = []
        for r in rows if isinstance(rows, list) else []:
            try:
                if isinstance(r, dict) and dt.datetime.fromisoformat(r["until"]) > now:
                    out.append(r)
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def _read(
        self, doc: dict[str, Any] | None, now: dt.datetime
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        doc = doc or {}
        return self._live(doc.get("grants"), now), self._live(doc.get("tickets"), now)

    async def grant(self, uid: str) -> Grant:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        until = now + dt.timedelta(minutes=self._minutes)
        row = {"mac": self._mac(token), "until": until.isoformat()}

        async def fn(tx: DocTx) -> None:
            grants, tickets = self._read(await tx.get(self._path(uid)), now)
            grants = [*grants, row][-MAX_GRANTS:]
            tx.set(self._path(uid), {"grants": grants, "tickets": tickets})

        await self._d.transaction(fn)
        return Grant(token, until)

    async def valid(self, uid: str, token: str) -> bool:
        if not token or len(token) > 128:
            return False
        grants, _ = self._read(await self._d.get(self._path(uid)), self._clock())
        return any(self._ring.mac_matches("tickets", token, g["mac"]) for g in grants)

    async def ticket(self, uid: str, token: str, item: str | None, fid: str) -> Ticket:
        """A single-use ticket for one file or the export; PermissionError without a live token."""
        if not token or len(token) > 128:
            raise PermissionError("locked")
        now = self._clock()
        secret = secrets.token_urlsafe(32)
        row = {
            "mac": self._mac(secret),
            "item": item,
            "fid": fid,
            "until": (now + dt.timedelta(seconds=TICKET_S)).isoformat(),
        }
        mac = self._mac(token)

        async def fn(tx: DocTx) -> None:
            grants, tickets = self._read(await tx.get(self._path(uid)), now)
            if not any(g["mac"] == mac for g in grants):
                raise PermissionError("locked")
            tx.set(self._path(uid), {"grants": grants, "tickets": [*tickets, row][-MAX_TICKETS:]})

        await self._d.transaction(fn)
        return Ticket(secret, TICKET_S)

    async def take(self, uid: str, ticket: str) -> Taken:
        """Use a ticket: it is removed in the same transaction, so a second use finds nothing."""
        if not ticket or len(ticket) > 128:
            raise TicketGone
        now = self._clock()
        mac = self._mac(ticket)

        async def fn(tx: DocTx) -> Taken:
            grants, tickets = self._read(await tx.get(self._path(uid)), now)
            hit = next((t for t in tickets if t["mac"] == mac), None)
            if hit is None:
                raise TicketGone
            rest = [t for t in tickets if t is not hit]
            tx.set(self._path(uid), {"grants": grants, "tickets": rest})
            return Taken(hit.get("item"), str(hit["fid"]))

        return await self._d.transaction(fn)

    async def lock(self, uid: str) -> None:
        async def fn(tx: DocTx) -> None:
            await tx.get(self._path(uid))
            tx.set(self._path(uid), {"grants": [], "tickets": []})

        await self._d.transaction(fn)

    async def sweep(self, uid: str) -> int:
        """Drop expired entries; returns how many went."""
        now = self._clock()

        async def fn(tx: DocTx) -> int:
            doc = await tx.get(self._path(uid))
            if doc is None:
                return 0
            grants, tickets = self._read(doc, now)
            before = len(doc.get("grants") or []) + len(doc.get("tickets") or [])
            tx.set(self._path(uid), {"grants": grants, "tickets": tickets})
            return before - len(grants) - len(tickets)

        return await self._d.transaction(fn)


__all__ = [
    "EXPORT",
    "MAX_GRANTS",
    "MAX_TICKETS",
    "TICKET_S",
    "Grant",
    "Taken",
    "Ticket",
    "TicketGone",
    "UnlockStore",
]
