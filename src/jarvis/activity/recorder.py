# src/jarvis/activity/recorder.py
"""The gateway observer that writes Activity rows (R1 plan D7; Layer 4 -> 7).

Told after each call's audit entry (`jarvis.tools.observers`). It writes the plain-words row and
nothing else: no query text of a read, no result, no model words. A failed write is logged (error
class only) and never fails the tool call. Owner comes from the call's scope ("uid:session").
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from jarvis.activity.models import ActivityItem
from jarvis.activity.store import ActivityStore, day_key, owner_ok
from jarvis.activity.words import describe
from jarvis.core import channel
from jarvis.logging import get_logger
from jarvis.tools import taint
from jarvis.tools.audit import args_hash
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.observers import GatewayEvent
from jarvis.tools.registry import ToolRegistry
from jarvis.undo.models import UndoRef

log = get_logger(__name__)

_OUTCOMES = {
    "executed": "done",
    "error": "failed",
    "awaiting_confirmation": "waiting",
    "denied": "refused",
    "declined": "declined",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ActivityRecorder:
    def __init__(
        self,
        store: ActivityStore,
        registry: ToolRegistry,
        *,
        timezone: str = "Asia/Kolkata",
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.store = store
        self.registry = registry
        self._tz = ZoneInfo(timezone)
        self._clock = clock

    def _channel(self) -> str:
        if channel.on_telegram():
            return "telegram"
        return "voice" if taint.spoken_in_context() else "console"

    async def on_event(self, event: GatewayEvent) -> None:
        try:
            await self._record(event)
        except Exception as exc:  # noqa: BLE001 - Activity never fails a tool call
            log.warning("activity row not written", extra={"error": type(exc).__name__})

    async def _record(self, e: GatewayEvent) -> None:
        uid, _, sid = (e.scope or "").partition(":")
        outcome = _OUTCOMES.get(e.outcome)
        if outcome is None or not uid or not owner_ok(uid):
            return
        kind, words = describe(e.tool, e.args, e.risk, outcome, self.registry)
        undo_id = None
        if kind == "delete" and outcome == "done" and e.result is not None:
            if getattr(e.result, "outcome", None) is GatewayOutcome.EXECUTED:
                ref = UndoRef.from_result(e.result.result)
                undo_id = ref.undo_id if ref else None
        now = self._clock()
        item = ActivityItem(
            id=f"act_{secrets.token_hex(10)}",
            user_id=uid,
            at=now,
            tool=e.tool[:64],
            risk=str(e.risk.value),
            kind=kind,  # type: ignore[arg-type]
            outcome=outcome,  # type: ignore[arg-type]
            words=words,
            channel=self._channel(),  # type: ignore[arg-type]
            offline=channel.answered_offline(),
            session_id=sid[:128] or None,
            trace_id=e.entry.trace_id if e.entry else None,
            audit_seq=e.entry.seq if e.entry else None,
            undo_id=undo_id,
            call_key=args_hash(e.args),
        )
        await self.store.add(item, day_key(now.astimezone(self._tz).date()))


__all__ = ["ActivityRecorder"]
