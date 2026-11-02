# src/jarvis/contacts/client.py
"""Google Contacts over the owner's link (slice 12 D5; Layer 6): people.searchContacts.

Verified 2026-11-03 against developers.google.com/people/api/rest/v1/people/searchContacts and
developers.google.com/people/v1/contacts:
- `GET https://people.googleapis.com/v1/people:searchContacts`, `query` (prefix phrases over the
  contact's names, nicknames, email addresses, phone numbers and organisations), `readMask`
  (required), `pageSize` (default 10, at most 30). Scope: contacts or contacts.readonly.
- The answer is `{"results": [{"person": Person}]}`; `phoneNumbers[].canonicalForm` is Google's
  E.164 form of the number (output only, may be missing).
- Search uses a lazy cache "updated after a request": clients "should first send a warmup search
  request with an empty query", then search "after several seconds". JARVIS warms the cache once
  per owner every `WARM_TTL_S` (every search refreshes it too); when a search straight after a
  warm-up finds nothing, it waits `COLD_RETRY_S` and asks once more. Not verified: how long the
  cache really takes to catch up (Google gives no figure).

Every call goes through `GoogleConnector.request` (bearer, 15 s, one refresh, a retry only for
GETs, vendor text never leaves), under one overall deadline; every response is checked for shape
before it is used. Contacts are other people's words (a name is whatever the contact or a synced
profile says): `Contact.name` is one clean line, and the tools fence it before the model sees it.
Nothing is cached or stored here but the time of the last warm-up.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.contacts.phones import is_e164, to_e164
from jarvis.integrations.google import (
    NOT_CONNECTED_MSG,
    RECONNECT_MSG,
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
    GoogleServiceDisabled,
    can_use_contacts,
)
from jarvis.logging import get_logger
from jarvis.tools.addresses import loose_address
from jarvis.tools.card import one_line

log = get_logger(__name__)

SEARCH_URL = "https://people.googleapis.com/v1/people:searchContacts"
READ_MASK = "names,emailAddresses,phoneNumbers"
MAX_MATCHES = 5
NAME_LIMIT = 100
QUERY_LIMIT = 100
MAX_EMAILS = 3
MAX_PHONES = 3
WARM_TTL_S = 600.0
COLD_RETRY_S = 2.0
DEADLINE_S = 20.0

GRANT_MSG = (
    "JARVIS has no permission to look up your contacts yet. Open Integrations and press Grant "
    "next to 'Contacts', then ask again."
)
PEOPLE_OFF_MSG = (
    "The contacts service (People API) is not switched on for your JARVIS project yet: re-run "
    "deploy/cloudrun.sh, or switch on 'People API' in Google Cloud Console → APIs & Services → "
    "Library."
)
TOO_SLOW = "Google Contacts took too long to answer; try again shortly."


class ContactsNotGranted(RuntimeError):
    """The link exists but the owner has not granted the contacts scope."""


@dataclass(frozen=True)
class Contact:
    """One match. `name` is one clean line of someone else's words (fence it for the model);
    `phones` are E.164; `unreadable` counts numbers that are not phone numbers JARVIS can use."""

    name: str
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    unreadable: int = 0


@dataclass(frozen=True)
class Found:
    contacts: tuple[Contact, ...]
    more: bool


def query_arg(value: Any) -> str:
    """The name to look up: one clean line of 1..QUERY_LIMIT characters, or ValueError."""
    text = one_line(value, QUERY_LIMIT + 1) if isinstance(value, str) else ""
    if not text:
        raise ValueError("name is required (who to look up)")
    if len(text) > QUERY_LIMIT:
        raise ValueError(f"name is too long (at most {QUERY_LIMIT} characters)")
    return text


def _list(value: Any) -> list[dict[str, Any]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _name(p: dict[str, Any]) -> str:
    names = _list(p.get("names"))
    primary = next((n for n in names if (n.get("metadata") or {}).get("primary") is True), None)
    chosen = primary or (names[0] if names else {})
    raw = chosen.get("displayName") or chosen.get("unstructuredName") or ""
    return one_line(raw if isinstance(raw, str) else "", NAME_LIMIT)


def _emails(p: dict[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for e in _list(p.get("emailAddresses")):
        addr = loose_address(e.get("value"))
        if addr and addr not in out:
            out.append(addr)
    return tuple(out[:MAX_EMAILS])


def _phones(p: dict[str, Any]) -> tuple[tuple[str, ...], int]:
    out: list[str] = []
    bad = 0
    for n in _list(p.get("phoneNumbers")):
        canon = n.get("canonicalForm")
        number = canon if is_e164(canon) else None
        if number is None:
            try:
                number = to_e164(n.get("value"))
            except ValueError:
                bad += 1
                continue
        if number not in out:
            out.append(number)
    return tuple(out[:MAX_PHONES]), bad


def contact_of(p: dict[str, Any]) -> Contact:
    emails = _emails(p)
    phones, bad = _phones(p)
    name = _name(p) or (emails[0] if emails else "(no name)")
    return Contact(name=name, emails=emails, phones=phones, unreadable=bad)


@dataclass
class ContactsClient:
    conn: GoogleConnector
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    clock: Callable[[], float] = time.monotonic
    _warm: dict[str, float] = field(default_factory=dict)

    async def require(self, uid: str) -> None:
        """Linked, usable, and contacts granted — from the stored link, no Google call."""
        st = await self.conn.status(uid)
        if not st["connected"] or st["needs_reconnect"]:
            raise GoogleNotConnected(RECONNECT_MSG if st["needs_reconnect"] else NOT_CONNECTED_MSG)
        if not can_use_contacts(st["scopes"]):
            raise ContactsNotGranted(GRANT_MSG)

    async def search(self, uid: str, name: str) -> Found:
        """Up to MAX_MATCHES contacts matching `name` (call `require` first)."""
        query = query_arg(name)
        try:
            return await asyncio.wait_for(self._search(uid, query), DEADLINE_S)
        except TimeoutError:
            raise GoogleAPIError(TOO_SLOW) from None

    async def _search(self, uid: str, query: str) -> Found:
        fresh = await self._warm_up(uid)
        found = await self._query(uid, query)
        if fresh and not found.contacts:  # the cache may not have caught up yet
            await self.sleep(COLD_RETRY_S)
            found = await self._query(uid, query)
        return found

    async def _warm_up(self, uid: str) -> bool:
        """The empty-query request Google asks for, at most every WARM_TTL_S per owner."""
        last = self._warm.get(uid)
        if last is not None and self.clock() - last < WARM_TTL_S:
            return False
        await self._get(uid, "")
        self._warm[uid] = self.clock()
        return True

    async def _query(self, uid: str, query: str) -> Found:
        body = await self._get(uid, query)
        results = _list(body.get("results")) if isinstance(body, dict) else []
        people = [r["person"] for r in results if isinstance(r.get("person"), dict)]
        found = tuple(contact_of(p) for p in people)
        return Found(found[:MAX_MATCHES], len(found) > MAX_MATCHES)

    async def _get(self, uid: str, query: str) -> Any:
        params = {"query": query, "readMask": READ_MASK, "pageSize": MAX_MATCHES + 1}
        try:
            return await self.conn.request(uid, "GET", SEARCH_URL, params=params)
        except GoogleServiceDisabled:
            raise GoogleAPIError(PEOPLE_OFF_MSG) from None


__all__ = [
    "GRANT_MSG",
    "MAX_MATCHES",
    "PEOPLE_OFF_MSG",
    "READ_MASK",
    "SEARCH_URL",
    "Contact",
    "ContactsClient",
    "ContactsNotGranted",
    "Found",
    "contact_of",
    "query_arg",
]
