# src/jarvis/brief/store.py
"""Brief settings and records on the Docs port (Layer 7).

Layout:  {prefix}brief_settings/{uid}        enabled, time, ai_summary, inbox_delivery, tz, …
         {prefix}briefs/{uid}_{YYYY-MM-DD}   user_id, date, json(BriefRecord)

Every state change that two callers could race on is a transaction: the generation claim
(create if absent; retake only a failed record, a stale claim, or a forced ready one), the
finish (only by the current claim holder), and the inbox `sending` mark (taken once, before the
Gmail call, never reset to "off": at most one inbox message per day). Retention uses an
equality query on `user_id` only, so no composite index is needed.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from jarvis.brief.models import BriefRecord, BriefSettings, InboxState, InboxStatus, Trigger
from jarvis.brief.schedule import claim_is_stale
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)


class ClaimOutcome(StrEnum):
    CLAIMED = "claimed"  # the caller generates now
    BUSY = "busy"  # someone else is generating (fresh claim)
    EXISTS = "exists"  # a ready brief exists and no regeneration was asked for
    CAPPED = "capped"  # today's generation budget is spent


@dataclass(frozen=True)
class Claim:
    outcome: ClaimOutcome
    record: BriefRecord


def _check(uid: str, day: str) -> None:
    if not safe_id(uid):
        raise ValueError("invalid user id")
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError:
        raise ValueError("date must be YYYY-MM-DD") from None


def _encode(rec: BriefRecord) -> dict[str, Any]:
    return {"user_id": rec.user_id, "date": rec.date, "json": rec.model_dump_json()}


def _decode(doc: dict[str, Any] | None) -> BriefRecord | None:
    if doc is None:
        return None
    try:
        return BriefRecord.model_validate_json(str(doc["json"]))
    except (KeyError, ValueError):
        log.error("unreadable brief document")
        return None


class BriefStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._settings = f"{prefix}brief_settings"
        self._briefs = f"{prefix}briefs"

    def _settings_path(self, uid: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._settings}/{uid}"

    def _brief_path(self, uid: str, day: str) -> str:
        _check(uid, day)
        return f"{self._briefs}/{uid}_{day}"

    # ---- settings -----------------------------------------------------------------------------

    @staticmethod
    def _settings_of(doc: dict[str, Any] | None) -> BriefSettings:
        if doc is None:
            return BriefSettings()
        try:
            return BriefSettings.model_validate(doc, strict=False)
        except ValidationError:
            log.error("unreadable brief settings; using defaults")
            return BriefSettings()

    async def get_settings(self, uid: str) -> BriefSettings:
        return self._settings_of(await self._d.get(self._settings_path(uid)))

    async def update_settings(
        self, uid: str, change: Callable[[BriefSettings], BriefSettings]
    ) -> BriefSettings:
        """Read-modify-write in one transaction. `change` may raise: nothing is written."""
        path = self._settings_path(uid)

        async def fn(tx: DocTx) -> BriefSettings:
            new = change(self._settings_of(await tx.get(path)))
            tx.set(path, new.model_dump(mode="json"))
            return new

        return await self._d.transaction(fn)

    # ---- briefs -------------------------------------------------------------------------------

    async def get_brief(self, uid: str, day: str) -> BriefRecord | None:
        return _decode(await self._d.get(self._brief_path(uid, day)))

    async def claim(
        self,
        uid: str,
        day: str,
        *,
        tz: str,
        trigger: Trigger,
        force: bool,
        now: datetime,
        max_generations: int,
    ) -> Claim:
        path = self._brief_path(uid, day)

        async def fn(tx: DocTx) -> Claim:
            cur = _decode(await tx.get(path))
            if cur is not None:
                if cur.status == "generating" and not claim_is_stale(cur, now):
                    return Claim(ClaimOutcome.BUSY, cur)
                if cur.status == "ready" and not force:
                    return Claim(ClaimOutcome.EXISTS, cur)
                if cur.generations >= max_generations:
                    return Claim(ClaimOutcome.CAPPED, cur)
            new = _claimed(cur, uid=uid, day=day, tz=tz, trigger=trigger, now=now)
            tx.set(path, _encode(new))
            return Claim(ClaimOutcome.CLAIMED, new)

        return await self._d.transaction(fn)

    async def finish(self, rec: BriefRecord) -> bool:
        """Store the finished record iff its claim is still the current one. Fields others
        may have changed meanwhile (seen_at, inbox) are taken from the stored copy."""
        path = self._brief_path(rec.user_id, rec.date)

        async def fn(tx: DocTx) -> bool:
            cur = _decode(await tx.get(path))
            if cur is None or cur.claim_id != rec.claim_id:
                return False
            tx.set(
                path, _encode(rec.model_copy(update={"seen_at": cur.seen_at, "inbox": cur.inbox}))
            )
            return True

        return await self._d.transaction(fn)

    async def _swap(
        self, uid: str, day: str, fn: Callable[[BriefRecord], BriefRecord | None]
    ) -> BriefRecord | None:
        """Transactional read → `fn` → write. `fn` returns None to leave the record alone."""
        path = self._brief_path(uid, day)

        async def tx_fn(tx: DocTx) -> BriefRecord | None:
            cur = _decode(await tx.get(path))
            new = fn(cur) if cur is not None else None
            if new is not None:
                tx.set(path, _encode(new))
            return new

        return await self._d.transaction(tx_fn)

    async def begin_inbox(self, uid: str, day: str, now: datetime) -> BriefRecord | None:
        """Take the at-most-once mark: ready + "off" → "sending". None if anyone already did."""

        def take(cur: BriefRecord) -> BriefRecord | None:
            if cur.status != "ready" or cur.inbox.status != "off":
                return None
            return cur.model_copy(update={"inbox": InboxState(status="sending", at=now)})

        return await self._swap(uid, day, take)

    async def end_inbox(
        self, uid: str, day: str, state: InboxState, *, expect: InboxStatus = "sending"
    ) -> bool:
        def settle(cur: BriefRecord) -> BriefRecord | None:
            if cur.inbox.status != expect:
                return None
            return cur.model_copy(update={"inbox": state})

        return await self._swap(uid, day, settle) is not None

    async def mark_seen(self, uid: str, day: str, now: datetime) -> BriefRecord | None:
        return await self._swap(uid, day, lambda cur: cur.model_copy(update={"seen_at": now}))

    async def prune(self, uid: str, *, keep_from: date) -> int:
        """Delete this owner's briefs dated before `keep_from`."""
        if not safe_id(uid):
            raise ValueError("invalid user id")
        rows = await self._d.query(Query(self._briefs, where=("user_id", uid)))
        cutoff = keep_from.isoformat()
        old = [doc_id for doc_id, d in rows if str(d.get("date") or "") < cutoff]
        if old:
            await self._d.write([Delete(f"{self._briefs}/{doc_id}") for doc_id in old])
        return len(old)


def _claimed(
    cur: BriefRecord | None, *, uid: str, day: str, tz: str, trigger: Trigger, now: datetime
) -> BriefRecord:
    """A fresh claim. Today's counters, inbox state and seen mark carry over (at-most-once per
    day), and so does any earlier content, which stays visible while the new one is made."""
    base = BriefRecord(
        user_id=uid,
        date=day,
        tz=tz,
        status="generating",
        claim_id=secrets.token_urlsafe(12),
        claimed_at=now,
        trigger=trigger,
    )
    if cur is None:
        return base.model_copy(update={"generations": 1})
    keep = {
        k: getattr(cur, k)
        for k in (
            "data",
            "ai",
            "ai_note",
            "text",
            "created_at",
            "seen_at",
            "inbox",
            "ai_calls_today",
        )
    }
    return base.model_copy(update={**keep, "generations": cur.generations + 1})


__all__ = ["BriefStore", "Claim", "ClaimOutcome"]
