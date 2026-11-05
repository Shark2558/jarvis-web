# src/jarvis/vault/reminders.py
"""Expiry reminders for vault documents (R2 D5; Layer 8 nudges; a tick job).

Once per owner per local day, at the first scheduler tick at or after the brief time (09:00 when
the brief is off), and also when the Vault panel opens (`check`), every CONFIRMED live item is
compared with its thresholds (the item's 180 / 90 / 60 / 30 / 14 / 7 / 1 days, plus "expires
today" and "expired"). One alert per threshold per item, recorded in `vault_alerts/{uid}` (ids and
dates only). After missed days only the most urgent unsent threshold is sent and the older ones
are marked sent; at most 3 alerts a run, more become one summary. Alert text is a fixed template
(never model text, never a holder label or the last 4). A send that fails is retried the next day.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.alerts import AlertSink
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx
from jarvis.vault.models import ME, TYPES, Item, VaultIndex, days_left
from jarvis.vault.service import IST, VaultService

log = get_logger(__name__)
DEFAULT_BRIEF_TIME = dt.time(9, 0)
MAX_ALERTS = 3
EXPIRED_QUIET_DAYS = 30  # an item expired longer ago than this is marked, not announced
CLAIM_STALE_S = 300  # a run that died half-way may be taken over after 5 minutes
EXPIRED, TODAY = -1, 0  # thresholds beyond the day counts
HOW = "Open the console and go to Vault."

BriefTime = Callable[[str], Awaitable[dt.time | None]]
ZoneFor = Callable[[str], Awaitable[ZoneInfo]]


def _key(threshold: int) -> str:
    return "expired" if threshold == EXPIRED else str(threshold)


def _when(left: int) -> str:
    if left < 0:
        return "has expired"
    if left == 0:
        return "expires today"
    return f"expires in {left} day" + ("" if left == 1 else "s")


def _word(label: str) -> str:
    first = label.split(" ")[0]
    return label if first.isupper() else label.lower()


def alert_text(detail: str, label: str, whose: str, left: int, on: dt.date) -> str:
    if detail == "type":
        who = "your" if whose == "you" else "a family member's"
        return f"JARVIS: {who} {_word(label)} {_when(left)} ({on:%d %b %Y})."
    return f"JARVIS: a document in your vault {_when(left)}. {HOW}"


def summary_text(n: int) -> str:
    return f"JARVIS: {n} documents in your vault need attention. {HOW}"


@dataclass(frozen=True)
class _Candidate:
    item: Item
    left: int
    fresh: tuple[str, ...]  # every unsent threshold now reached (all get marked sent)
    key: str  # the most urgent one


def _candidate(item: Item, today: dt.date, sent: dict[str, Any]) -> _Candidate | None:
    left = days_left(item, today)
    if not item.dates_confirmed or left is None:
        return None
    ladder = [*item.reminders, TODAY, EXPIRED]
    reached = [t for t in ladder if left <= t and _key(t) not in sent]
    if not reached:
        return None
    return _Candidate(item, left, tuple(_key(t) for t in reached), _key(min(reached)))


def _parse(value: Any) -> dt.datetime | None:
    try:
        when = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.UTC)


def _sent(doc: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {k: dict(v) for k, v in (doc.get("sent") or {}).items() if isinstance(v, dict)}


class VaultReminders:
    name = "vault_reminders"
    budget_s = 30.0

    def __init__(
        self,
        service: VaultService,
        alerts: AlertSink,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        brief_time: BriefTime | None = None,
        zone_for: ZoneFor | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._svc = service
        self._alerts = alerts
        self._d = docs
        self._col = f"{prefix}vault_alerts"
        self._brief_time = brief_time
        self._zone_for = zone_for
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        ran = sent = failed = 0
        for uid in owners:
            try:
                n = await self._one(uid, scheduled=True)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("vault reminders failed", extra={"error": type(exc).__name__})
                failed += 1  # review M1: counted, so the tick says "failed"
                continue
            if n is not None:
                ran += 1
                sent += n
        return {"owners": ran, "alerts": sent, "failed": failed}

    async def check(self, uid: str) -> int:
        """Run now if today's run has not happened (the Vault panel opened). Never raises."""
        try:
            return await self._one(uid, scheduled=False) or 0
        except Exception as exc:  # noqa: BLE001
            log.warning("vault reminder check failed", extra={"error": type(exc).__name__})
            return 0

    async def _local(self, uid: str) -> dt.datetime:
        zone = await self._zone_for(uid) if self._zone_for else IST
        return self._clock().astimezone(zone)

    async def _one(self, uid: str, *, scheduled: bool) -> int | None:
        local = await self._local(uid)
        today = local.date()
        if scheduled:
            at = (await self._brief_time(uid)) if self._brief_time else None
            if local.time() < (at or DEFAULT_BRIEF_TIME):
                return None
        path = f"{self._col}/{uid}"
        sent_state = await self._claim(path, today)
        if sent_state is None:
            return None
        index = await self._svc.index(uid)
        count = await self._deliver(uid, index, today, sent_state, path)
        live = {i.id for i in index.live_items()}
        await asyncio.shield(self._finish(path, today, sent_state, live))
        return count

    async def _claim(self, path: str, today: dt.date) -> dict[str, dict[str, str]] | None:
        """Take today's run in a transaction (only one caller wins), or None. The sent state is
        returned with it; an unfinished claim may be taken over once it has gone stale."""
        now = self._clock()

        async def fn(tx: DocTx) -> dict[str, dict[str, str]] | None:
            doc = await tx.get(path) or {}
            if doc.get("last_run_day") == today.isoformat():
                at = _parse(doc.get("claimed_at"))
                if (
                    doc.get("done") is True
                    or at is None
                    or (now - at).total_seconds() < CLAIM_STALE_S
                ):
                    return None
            sent = _sent(doc)
            tx.set(
                path,
                {
                    "last_run_day": today.isoformat(),
                    "claimed_at": now.isoformat(),
                    "done": False,
                    "sent": sent,
                },
            )
            return sent

        return await self._d.transaction(fn)

    async def _mark(self, path: str, marks: dict[str, dict[str, str]]) -> None:
        """Record sent alerts at once (merged into the stored state), so a cancel or a crash
        right after a send can never make the next run send it again."""

        async def fn(tx: DocTx) -> None:
            doc = await tx.get(path) or {}
            sent = _sent(doc)
            for item_id, keys in marks.items():
                sent.setdefault(item_id, {}).update(keys)
            tx.set(path, {**doc, "sent": sent})

        await self._d.transaction(fn)

    async def _finish(
        self, path: str, today: dt.date, sent: dict[str, dict[str, str]], live: set[str]
    ) -> None:
        async def fn(tx: DocTx) -> None:
            doc = await tx.get(path) or {}
            merged = _sent(doc)
            for item_id, keys in sent.items():
                merged.setdefault(item_id, {}).update(keys)
            kept = {k: v for k, v in merged.items() if k in live}
            tx.set(
                path,
                {
                    "last_run_day": today.isoformat(),
                    "claimed_at": doc.get("claimed_at"),
                    "done": True,
                    "sent": kept,
                },
            )

        await self._d.transaction(fn)

    async def _deliver(
        self,
        uid: str,
        index: VaultIndex,
        today: dt.date,
        sent: dict[str, dict[str, str]],
        path: str,
    ) -> int:
        due: list[_Candidate] = []
        for item in index.live_items():
            known = sent.setdefault(item.id, {})
            cand = _candidate(item, today, known)
            if cand is None:
                continue
            if cand.left < -EXPIRED_QUIET_DAYS:  # long expired: mark, don't announce
                known.update({k: today.isoformat() for k in cand.fresh})
                continue
            due.append(cand)
        due.sort(key=lambda c: c.left)
        if not due:
            return 0
        detail = index.settings.alert_detail
        if len(due) > MAX_ALERTS:
            texts = [summary_text(len(due))]
        else:
            texts = [
                alert_text(
                    detail,
                    TYPES.get(c.item.type, TYPES["other"]).label,
                    "you" if c.item.holder_id == ME else "family",
                    c.left,
                    c.item.expires_on or today,
                )
                for c in due
            ]
        delivered = 0
        groups = [due] if len(due) > MAX_ALERTS else [[c] for c in due]
        for text, group in zip(texts, groups, strict=True):
            result = await self._alerts.send(uid, text, kind="vault_expiry")
            if result.sent:  # a failed send is retried tomorrow
                delivered += 1
                marks = {c.item.id: {k: today.isoformat() for k in c.fresh} for c in group}
                for item_id, keys in marks.items():
                    sent[item_id].update(keys)
                await asyncio.shield(self._mark(path, marks))
        return delivered


__all__ = ["VaultReminders", "alert_text", "summary_text"]
