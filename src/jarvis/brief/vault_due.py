# src/jarvis/brief/vault_due.py
"""The brief's Documents section (R2 D5): vault documents expiring within 90 days or expired in
the last 30, at most 5 lines.

Deterministic and never part of the AI-summary input (`brief.summarize` names its blocks one by
one). Only CONFIRMED dates count. The stored record keeps the type label, "you" / "family" and the
date; never a name, a title or the last 4. Absent (None) when nothing is due or the owner switched
the section off in the vault settings. Fails on its own (the service turns an error into a state).
"""

from __future__ import annotations

from datetime import date, tzinfo

from jarvis.brief.models import VaultDueItem, VaultDueSection
from jarvis.vault.service import VaultService

MAX_SHOWN = 5
WITHIN_DAYS = 90
EXPIRED_DAYS = 30


class VaultDueBrief:
    def __init__(self, svc: VaultService) -> None:
        self._svc = svc

    async def section(self, uid: str, tz: tzinfo, day: date) -> VaultDueSection | None:
        index = await self._svc.index(uid)
        if not index.settings.brief:
            return None
        due = self._svc.due_of(index, day, WITHIN_DAYS, EXPIRED_DAYS)
        if not due:
            return None
        items = tuple(
            VaultDueItem(
                type_label=d.type_label,
                whose=d.whose,  # type: ignore[arg-type]
                expires_on=d.expires_on.isoformat(),
                days_left=d.days_left,
            )
            for d in due[:MAX_SHOWN]
        )
        return VaultDueSection(
            total=len(due), items=items, state="ok", inbox_copy=index.settings.inbox_copy
        )


__all__ = ["EXPIRED_DAYS", "MAX_SHOWN", "WITHIN_DAYS", "VaultDueBrief"]
