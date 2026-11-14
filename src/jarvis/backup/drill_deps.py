# src/jarvis/backup/drill_deps.py
"""What the restore drill's three modules share (`drill`, `drill_start`, `drill_end`;
docs/plans/r14-hardening.md D4): its dependencies, the drill copy's reader, his clock and the
switches. No logic of its own, so the three import it without a cycle.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from jarvis.backup import verify
from jarvis.backup.log import DrillLog, month_key
from jarvis.backup.ports import BackupAdmin, DrillWalk, ReadOnlyDocs
from jarvis.backup.status import BackupStatusService, Teller
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.ticks import time_left as tick_time_left
from jarvis.vitals.models import zone_of


class Walker(DrillWalk, ReadOnlyDocs, Protocol):
    """The drill copy's reader: its collections, counts and samples, and get / query."""


@dataclass(frozen=True)
class DrillDeps:
    s: Settings
    admin: BackupAdmin
    walk: Callable[[], Walker]
    live: ReadOnlyDocs
    log: DrillLog
    status: BackupStatusService
    teller: Teller
    ring: Keyring | None
    rate: Callable[[], Awaitable[float]]
    clock: Callable[[], dt.datetime]
    prefix: str = "jarvis_"
    time_left: verify.TimeLeft = tick_time_left
    keys: verify.Keys = field(default=verify.APP_KEYS)

    def on(self) -> bool:
        return self.s.backup_checks_enabled and self.s.backup_drill_enabled

    def local(self, now: dt.datetime) -> dt.datetime:
        return now.astimezone(zone_of(self.s.user_timezone))

    def month(self, now: dt.datetime) -> str:
        return month_key(self.local(now))


def run_key(at: dt.datetime) -> str:
    """A drill's own name for its told-once mark: when it started (or was refused), UTC."""
    return at.astimezone(dt.UTC).strftime("%Y%m%d%H%M%S")


def short_id(name: str) -> str:
    return name.rsplit("/", 1)[-1][:200]


__all__ = ["DrillDeps", "Walker", "run_key", "short_id"]
