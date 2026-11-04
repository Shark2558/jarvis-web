# src/jarvis/activity/service.py
"""The Activity view (R1 plan D8; Layer 3 over the Layer 7 store).

Undo appears only where Recently deleted can really restore the item (`jarvis.undo`); nothing is
invented here. Every other row says why there is no Undo. Reads of one tool within one request
are grouped ("Looked at your calendar \u00b7 3 times"). A "waiting" row is hidden once the same
call has finished. Owner-scoped by path. "Today" is the owner's local day.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.activity.models import (
    ActivityItem,
    ActivityRow,
    ActivityView,
    UndoState,
    UndoView,
)
from jarvis.activity.store import ActivityStore, day_key
from jarvis.activity.words import PREFIXES, undo_note
from jarvis.logging import get_logger
from jarvis.tools.card import quoted
from jarvis.undo.models import KIND_WORDS, RestoreOutcome, RestoreStatus
from jarvis.undo.service import UndoBin

log = get_logger(__name__)

NOTE_UNDO_GONE = "No longer in Recently deleted \u2014 can't be undone"
NOTE_UNDO_EXPIRED = "Past the 30 days in Recently deleted \u2014 can't be undone"
TITLE_LIMIT = 120


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ActivityService:
    def __init__(
        self,
        store: ActivityStore,
        undo: UndoBin | None,
        *,
        timezone: str = "Asia/Kolkata",
        retention_days: int = 7,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.store = store
        self.undo = undo
        self._tz = ZoneInfo(timezone)
        self._clock = clock
        self.retention_days = retention_days

    def _local_day(self, offset_days: int = 0) -> str:
        return day_key(self._clock().astimezone(self._tz).date() - timedelta(days=offset_days))

    async def view(self, uid: str, day: str = "today") -> ActivityView:
        which = "yesterday" if day == "yesterday" else "today"
        rows = await self.store.day(uid, self._local_day(1 if which == "yesterday" else 0))
        rows = _without_finished_waits(rows)
        out: list[ActivityRow] = []
        groups: dict[tuple[str, str | None], int] = {}
        for r in rows:
            if r.kind == "read" and r.outcome == "done":
                groups[(r.tool, r.trace_id)] = groups.get((r.tool, r.trace_id), 0) + 1
        seen: set[tuple[str, str | None]] = set()
        for r in rows:
            key = (r.tool, r.trace_id)
            if r.kind == "read" and r.outcome == "done" and r.trace_id is not None:
                if key in seen:
                    continue
                seen.add(key)
                n = groups[key]
                out.append(await self._row(uid, r, f" \u00b7 {n} times" if n > 1 else ""))
            else:
                out.append(await self._row(uid, r, ""))
        return ActivityView(day=which, items=out)

    async def _row(self, uid: str, r: ActivityItem, suffix: str) -> ActivityRow:
        undo: UndoView | None = None
        note = ""
        if r.undo_id is not None:
            state = await self._undo_state(uid, r.undo_id)
            undo = UndoView(id=r.undo_id, state=state)
            note = {"expired": NOTE_UNDO_EXPIRED, "gone": NOTE_UNDO_GONE}.get(state, "")
        else:
            note = undo_note(r.tool, r.kind, r.outcome)
        return ActivityRow(
            id=r.id,
            at=r.at,
            words=r.words + suffix,
            outcome=r.outcome,
            channel=r.channel,
            offline=r.offline,
            undo=undo,
            undo_note=note,
        )

    async def _undo_state(self, uid: str, undo_id: str) -> UndoState:
        if self.undo is None:
            return "gone"
        try:
            item = await self.undo.store.get(uid, undo_id)
        except Exception as exc:  # noqa: BLE001 - unknown means no button
            log.warning("undo state unreadable", extra={"error": type(exc).__name__})
            return "gone"
        if item is None:
            return "gone"
        if item.restored:
            return "restored"
        return "expired" if item.expired(self.undo.now()) else "available"

    async def record_restore(
        self, uid: str, out: RestoreOutcome, *, session_id: str | None
    ) -> None:
        """The owner pressed Undo (api/deleted.py): a "You restored ..." row. Never raises."""
        if out.status is not RestoreStatus.RESTORED or out.kind is None:
            return
        now = self._clock()
        words = f"You restored the {KIND_WORDS[out.kind]} {quoted(out.title, TITLE_LIMIT)}"
        item = ActivityItem(
            id=f"act_{secrets.token_hex(10)}",
            user_id=uid,
            at=now,
            tool="deleted_restore",
            risk="reversible",
            kind="restore",
            outcome="done",
            words=words,
            channel="console",
            session_id=session_id,
        )
        try:
            await self.store.add(item, self._local_day())
        except Exception as exc:  # noqa: BLE001
            log.warning("restore row not written", extra={"error": type(exc).__name__})

    async def sweep(self, owners: Sequence[str]) -> int:
        keep_from = self._local_day(self.retention_days - 1)
        return await self.store.sweep(owners, keep_from=keep_from)


def _bare(words: str) -> str:
    for prefix in PREFIXES.values():
        if words.startswith(prefix):
            return words[len(prefix) :]
    return words


def _without_finished_waits(rows: list[ActivityItem]) -> list[ActivityItem]:
    """A waiting row is dropped when the same tool has a row for the same words that is not
    waiting (the card was approved, declined or refused)."""
    finished = {(r.tool, _bare(r.words)) for r in rows if r.outcome != "waiting"}
    return [
        r for r in rows if not (r.outcome == "waiting" and (r.tool, _bare(r.words)) in finished)
    ]


__all__ = ["ActivityService"]
