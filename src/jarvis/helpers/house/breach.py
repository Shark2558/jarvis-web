# src/jarvis/helpers/house/breach.py
"""Item 6, breach-notice watching (docs/plans/r11-free-helpers.md D14). Not a paid HIBP key.

He signs up his own address at Have I Been Pwned's free "Notify me" (and Mozilla Monitor if he
likes); JARVIS sends his address nowhere. `BreachJob` (`breach_watch`, the morning tick), for
each configured owner who switched it on ("I've subscribed") and whose Email row ("Search and
read email", `gmail_*`) and "Weather and alerts" row (`breach_*`) aren't Never (rules that can't
be read: no read):
- one Gmail search restricted to the fixed senders' domains (`SENDERS`, newer than 2 days) and
  each hit's headers only (`format=metadata`: From, Subject, Authentication-Results);
- a mail counts only when its From address is a fixed sender's (that exact host, no subdomain;
  security review L2) AND the first Authentication-Results header is Gmail's own (authserv-id
  `mx.google.com`, security review L1) and says dkim=pass or dmarc=pass aligned with that domain
  (the parcels reader's `authenticated`); anyone can write a From line or a header below Gmail's.
  The subject is used only to tell a notice from a sign-up mail ("verify your address") and is
  never stored, logged or sent;
- one `breach_notice` per service with new notices: "A breach notice from Have I Been Pwned
  arrived. Open it in Gmail and change that password, Sir." Each message is claimed (a hash of
  its id) before the send and released when no channel took it;
- a kind-only audit line (agent `helpers`, `breach_watch`, `breach_notice`) for every Gmail read.
It also sweeps Part B's claims older than 30 days (every owner, every day).
The sender addresses are UNVERIFIED until a real notice is seen in his mail (an owner check):
HIBP's support pages name noreply@haveibeenpwned.com (DKIM-signed); Mozilla Monitor's is a guess
limited to the exact host monitor.mozilla.org, so a wrong guess means "no alert", never a false
one.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any

from jarvis.helpers.house import words
from jarvis.helpers.house.guard import Counts, allowed, audit, tally
from jarvis.helpers.house.models import Outside
from jarvis.helpers.house.store import HouseStore, OutsideOff, OutsideStore
from jarvis.helpers.ports import HelperContext
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.packages.carriers import authenticated
from jarvis.tools.addresses import loose_address
from jarvis.tools.card import one_line
from jarvis.tools.gmail import MESSAGES_URL
from jarvis.tools.gmail_mime import headers_of

log = get_logger(__name__)

JOB = "breach_watch"
DAYS = 2  # the daily job overlaps a day, so a late tick misses nothing
MAX_SCAN = 20
READ_PARALLEL = 5
_ID_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
SKIP_WORDS = ("verify", "confirm your", "welcome", "unsubscribe")
GMAIL_AUTHSERV = "mx.google.com"  # the authserv-id Gmail stamps on mail it received
_AUTHSERV = re.compile(r"^\s*([^\s;]+)(?:\s+\d+)?\s*;")


@dataclass(frozen=True)
class Sender:
    key: str
    service: str  # JARVIS's own name for it (the alert says this, never the mail's words)
    domain: str
    locals: tuple[str, ...]  # the From local parts that count (empty: any)
    words: tuple[str, ...]  # a notice's subject has one of these (a filter only)


SENDERS: tuple[Sender, ...] = (
    Sender("hibp", "Have I Been Pwned", "haveibeenpwned.com", ("noreply",), ("pwned", "breach")),
    Sender("monitor", "Mozilla Monitor", "monitor.mozilla.org", (), ("breach", "exposed")),
)


def gmail_query(days: int) -> str:
    return f"from:({' OR '.join(s.domain for s in SENDERS)}) newer_than:{days}d"


def _sender_of(address: str) -> Sender | None:
    local_part, _, host = address.rpartition("@")
    for s in SENDERS:
        if host == s.domain and (not s.locals or local_part in s.locals):
            return s
    return None


def _gmails(results: str | None) -> bool:
    """The first Authentication-Results is Gmail's own (its authserv-id leads the header)."""
    m = _AUTHSERV.match(results or "")
    return m is not None and m.group(1).lower() == GMAIL_AUTHSERV


def notice_from(message: dict[str, Any]) -> Sender | None:
    """The fixed sender of a real notice in this Gmail message (headers only), else None."""
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return None
    h = headers_of(payload)
    address = loose_address(parseaddr(one_line(h.get("from", ""), 600))[1])
    s = _sender_of(address) if address else None
    results = h.get("authentication-results")  # the first one: Gmail prepends its own
    if s is None or not _gmails(results):
        return None
    if not authenticated(results, address.rpartition("@")[2]):
        return None
    subject = one_line(h.get("subject", ""), 300).lower()
    if any(w in subject for w in SKIP_WORDS) or not any(w in subject for w in s.words):
        return None
    return s


class BreachJob:
    name = JOB
    budget_s = 15.0

    def __init__(self, ctx: HelperContext, outside: OutsideStore, store: HouseStore) -> None:
        self._ctx = ctx
        self._outside = outside
        self._store = store

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` is ignored: the helpers serve the configured owners (`ctx.owners`)."""
        n = Counts()
        for uid in self._ctx.owners:
            try:
                n.add("swept", await self._store.sweep(uid, self._ctx.now()))
                await self._owner(uid, n)
            except OutsideOff:
                n.add("off")
            except GoogleNotConnected:
                n.add("not_linked")
            except GoogleAPIError as exc:
                log.warning("breach watch: Gmail unreachable", extra={"error": type(exc).__name__})
                n.add("unreachable")
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("breach watch failed for an owner", extra={"error": type(exc).__name__})
                n.add("failed")
        return n.done("sent", "retry", "swept", "failed")

    async def _owner(self, uid: str, n: Counts) -> None:
        o = await self._outside.read(uid)
        if not o.breach_on:
            n.add("not_on")
            return
        if self._ctx.google is None:
            n.add("not_linked")
            return
        if not await allowed(self._ctx, uid, "gmail_search", "breach_status"):
            n.add("skipped")
            return
        found = await self._scan(uid)
        await audit(self._ctx, JOB, "breach_notice")
        sent = 0
        for s in SENDERS:
            ids = [mid for who, mid in found if who == s]
            sent += await self._tell(uid, s, ids, n)
        await self._outside.change(uid, lambda cur: _checked(cur, self._ctx, sent))

    async def _scan(self, uid: str) -> list[tuple[Sender, str]]:
        google = self._ctx.google
        assert google is not None
        listing = await google.request(
            uid, "GET", MESSAGES_URL, params={"q": gmail_query(DAYS), "maxResults": MAX_SCAN}
        )
        rows = listing.get("messages") if isinstance(listing, dict) else None
        ids = [
            str(x["id"])
            for x in rows or []
            if isinstance(x, dict) and x.get("id") and set(str(x["id"])) <= _ID_OK
        ][:MAX_SCAN]
        params = {
            "format": "metadata",
            "metadataHeaders": ["From", "Subject", "Authentication-Results"],
        }
        gate = asyncio.Semaphore(READ_PARALLEL)

        async def one(mid: str) -> Any:
            async with gate:
                try:
                    return await google.request(uid, "GET", f"{MESSAGES_URL}/{mid}", params=params)
                except GoogleNotConnected:
                    raise
                except GoogleAPIError:
                    return None  # one unreadable mail never hides the others

        got = await asyncio.gather(*(one(mid) for mid in ids))
        return [
            (s, mid)
            for mid, m in zip(ids, got, strict=True)
            if isinstance(m, dict) and (s := notice_from(m)) is not None
        ]

    async def _tell(self, uid: str, s: Sender, ids: list[str], n: Counts) -> int:
        now = self._ctx.now()
        new = [mid for mid in ids if await self._store.take(uid, "breach", mid, now) == "new"]
        if not new:
            return 0
        try:
            got = await self._ctx.sender.send(
                uid, "breach_notice", words.breach(s.service), due=now
            )
        except BaseException:
            await asyncio.shield(self._settle(uid, new, went=False))
            raise
        went = tally(got, n)
        await self._settle(uid, new, went=went)
        return len(new) if went else 0

    async def _settle(self, uid: str, ids: list[str], *, went: bool) -> None:
        for mid in ids:
            if went:
                await self._store.done(uid, "breach", mid)
            else:
                await self._store.release(uid, "breach", mid)


def _checked(cur: Outside, ctx: HelperContext, sent: int) -> Outside:
    now = ctx.now()
    b = cur.breach
    update: dict[str, Any] = {"checked_at": now.isoformat(), "notices": b.notices + sent}
    if sent:
        update["last_day"] = local(now, ctx.tz).date().isoformat()
    return cur.model_copy(update={"breach": b.model_copy(update=update)})


__all__ = ["JOB", "SENDERS", "BreachJob", "Sender", "gmail_query", "notice_from"]
