# src/jarvis/backup/tools.py
"""Part A's two tools and its desk (docs/plans/r14-hardening.md D4, D12; `hardening.ports`
`TOOL_FAMILIES["backup"]`). Deterministic: no model call; both answer with fixed words, so No-AI
mode can say them (Part D routes "when was my last backup" / "test my backup" to them).

- `vitals_backups` (R1, row `vitals`): the backups' facts: set up or not, the last copy and how
  many Google keeps, the size, the rupee estimate a month, the last drill's result. Counts and
  times only.
- `vitals_drill_start` (R2, row `vitals_change`): ALWAYS a card (`ask_when`), never part of
  Approve all (`PendingAction.bulk_ok` is False for it: I1's one-line guard, INTEGRATION-A
  "Needs I1"), at most `backup_drill_manual_per_month` a month. Approving it asks for a drill at
  the next morning tick (`Drill.request`); it restores nothing itself.

`BackupDesk` is what the tools and the routes (`api/backup.py`) share.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jarvis.backup.drill import NOT_SET_UP_LINE, Drill
from jarvis.backup.log import DrillLog, DrillResult
from jarvis.backup.status import (
    REASON_WORDS,
    RETENTION_DAYS,
    BackupStatusService,
    StatusDoc,
    monthly_inr,
)
from jarvis.billing.service import rupees
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Tool
from jarvis.vitals.models import zone_of

SHOW = "vitals_backups"
START = "vitals_drill_start"
MIB = 1024 * 1024
SHOWN = "Checked the backups"
ASKED = "Asked for a restore drill"
NOT_SET_UP_SAID = (
    "Backups aren't set up yet, Sir: no copy of your data is kept. The one-time step turns them "
    "on: bash deploy/backup_setup.sh in Cloud Shell."
)
NO_COPY_SAID = "Backups are on, Sir; Google hasn't made the first copy yet."


def when_words(at: dt.datetime, tz: dt.tzinfo) -> str:
    local = at.astimezone(tz)
    return f"{local.day} {local:%b}, {local:%H:%M}"


def drill_words(last: DrillResult | None, tz: dt.tzinfo) -> str:
    if last is None:
        return "No restore drill has run yet."
    on = f"{last.at.astimezone(tz).day} {last.at.astimezone(tz):%b}"
    if last.outcome == "passed":
        return f"The last restore drill passed on {on}."
    if last.outcome == "skipped":
        return f"The last restore drill on {on} was skipped: there was no vault to open."
    why = REASON_WORDS.get(last.reason or "unknown", REASON_WORDS["unknown"])
    return f"The last restore drill on {on} failed: {why}."


@dataclass(frozen=True)
class BackupDesk:
    s: Settings
    status: BackupStatusService
    log: DrillLog
    drill: Drill | None
    rate: Callable[[], Awaitable[float]]

    async def month_inr(self, doc: StatusDoc) -> float | None:
        if not doc.size_bytes:
            return None
        drills = 1 if self.s.backup_drill_enabled else 0
        return monthly_inr(doc.size_bytes, await self.rate(), drills=drills)

    def _spoken(self, doc: StatusDoc, last: DrillResult | None, inr: float | None) -> str:
        tz = zone_of(self.s.user_timezone)
        if not doc.set_up:
            return NOT_SET_UP_SAID
        if doc.newest_at is None:
            return f"{NO_COPY_SAID} {drill_words(last, tz)}"
        cost = f", about {rupees(inr)} a month" if inr is not None else ""
        copy = f"Your last backup is from {when_words(doc.newest_at, tz)}, Sir"
        return (
            f"{copy}; Google keeps each copy {RETENTION_DAYS} days{cost}. {drill_words(last, tz)}"
        )

    async def summary(self) -> dict[str, Any]:
        doc, last = await self.status.doc(), await self.log.last_result()
        state, inr = await self.log.state(), await self.month_inr(doc)
        return {
            "set_up": doc.set_up,
            "schedule": doc.schedule_now,
            "last_copy": doc.newest_at.isoformat() if doc.newest_at else None,
            "copies": doc.copies,
            "size_mb": round(doc.size_bytes / MIB, 1) if doc.size_bytes else None,
            "documents": doc.document_count,
            "month_inr": inr,
            "drill": last.words if last is not None else None,
            "drill_at": last.at.isoformat() if last is not None else None,
            "drill_running": state.phase != "idle" or state.requested_at is not None,
            "spoken": self._spoken(doc, last, inr),
        }

    async def request(self) -> str:
        return NOT_SET_UP_LINE if self.drill is None else await self.drill.request()


def card_text(s: Settings) -> str:
    n = s.backup_drill_manual_per_month
    return (
        "Start a restore drill: JARVIS opens the newest backup in a throw-away copy, checks it "
        f"and deletes it (about ₹2 at 100 MB, never over {rupees(s.backup_drill_max_inr)}; at "
        f"most {n} a month)"
    )


def backup_tools(desk: BackupDesk) -> tuple[Tool, ...]:
    async def show(_: dict[str, Any]) -> dict[str, Any]:
        return await desk.summary()

    async def start(_: dict[str, Any]) -> dict[str, Any]:
        return {"message": await desk.request()}

    empty: dict[str, Any] = {"type": "object", "properties": {}}
    return (
        Tool(
            SHOW,
            "Say when JARVIS's data was last backed up: whether backups are set up, the last "
            "copy (Google keeps each 7 days), the size, about how much it costs a month in "
            "rupees and the last restore drill's result. Read-only.",
            empty,
            ActionRisk.READ_ONLY,
            show,
            agent="vitals",
            activity_words=SHOWN,
        ),
        Tool(
            START,
            'Ask for a restore drill ("test my backup"): at the next morning check JARVIS opens '
            "the newest backup in a throw-away copy, checks that nothing is missing and that his "
            "locked documents open, then deletes the copy. Always a card he approves; at most "
            "2 a month.",
            empty,
            ActionRisk.REVERSIBLE,
            start,
            agent="vitals",
            summarize=lambda _: card_text(desk.s),
            ask_when=lambda _: True,
            activity_words=ASKED,
        ),
    )


__all__ = ["ASKED", "SHOW", "SHOWN", "START", "BackupDesk", "backup_tools", "card_text"]
