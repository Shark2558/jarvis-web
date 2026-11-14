# src/jarvis/backup/part.py
"""R14 Part A (backups and the restore drill): the part's one join with the app
(`jarvis.hardening.ports`; docs/plans/r14-hardening.md D3, D4, "Part split" A).

`build(ctx)` hands back `HardeningPart("backup")` with:
- tools `vitals_backups` (R1) and `vitals_drill_start` (R2, always a card, `bulk_ok=False` once
  I1 adds its guard), whenever there is a document store;
- daily jobs `backup_canary` and `backup_drill` (the existing morning tick);
- the Vitals reader (items `backups`, `backup_drill`, `db_size`) and the "Backups" privacy row;
- services `backup_status` (`backup.ports.BackupStatus`: the ONE reader of the backups' facts
  for Part B and Vitals) and `backup` (`tools.BackupDesk`, for its own routes).
The real Google adapters (`storage/firestore_admin.py`, `storage/firestore_walk.py`) are made
only on Firestore with a project id; otherwise the part runs with no admin ("off: not on
Firestore"): Vitals says "not set up" and nothing is asked of Google. The key comes from the
settings (`Keyring.from_settings`); the clock, the notifier and the live rupee rate are read
late from the app. `build_with` lets the tests and the eval pass their fakes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable

from jarvis.backup.canary import CanaryStore
from jarvis.backup.drill import Drill, DrillDeps, Walker
from jarvis.backup.jobs import BackupCanaryJob, BackupDrillJob
from jarvis.backup.log import DrillLog
from jarvis.backup.ports import BackupAdmin
from jarvis.backup.privacy import BackupsPrivacy
from jarvis.backup.readonly import read_only
from jarvis.backup.status import BackupStatusService, Teller
from jarvis.backup.tools import BackupDesk, backup_tools
from jarvis.backup.vitals import vitals_reader
from jarvis.config import SessionBackend, Settings
from jarvis.hardening.ports import HardeningContext, HardeningPart
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.vitals.models import zone_of

log = get_logger(__name__)

READY = "ready"
NO_FIRESTORE = "off: not on Firestore"
NO_KEY = "ready: no token key, so no canary and no drill"
NO_STORE = "off: no document store"


def admin_for(s: Settings) -> BackupAdmin | None:
    if s.session_backend is not SessionBackend.FIRESTORE or not s.firestore_project:
        return None
    from jarvis.storage.firestore_admin import FirestoreAdmin

    return FirestoreAdmin(project=s.firestore_project, live=s.firestore_database)


def walk_for(s: Settings) -> Callable[[], Walker]:
    def walk() -> Walker:
        from jarvis.storage.firestore_walk import FirestoreWalk

        return FirestoreWalk(project=s.firestore_project, live=s.firestore_database)

    return walk


def _clock(ctx: HardeningContext) -> Callable[[], dt.datetime]:
    def now() -> dt.datetime:
        late = ctx.state("helpers_now")
        at = late() if callable(late) else None
        return at if isinstance(at, dt.datetime) else dt.datetime.now(dt.UTC)

    return now


def _rate(ctx: HardeningContext) -> Callable[[], Awaitable[float]]:
    async def rate() -> float:
        fx = getattr(ctx.state("billing"), "fx", None)
        try:
            return float((await fx.rate()).inr_per_usd) if fx is not None else ctx.s.usd_inr_rate
        except Exception as exc:  # noqa: BLE001 - the configured rate, said: the cap uses it
            log.warning("backup costs: the live rate failed, the configured rate is used",
                        extra={"error": type(exc).__name__})  # fmt: skip
            return ctx.s.usd_inr_rate

    return rate


def build(ctx: HardeningContext) -> HardeningPart:
    return build_with(
        ctx, admin=admin_for(ctx.s), walk=walk_for(ctx.s), keys=Keyring.from_settings(ctx.s)
    )


def build_with(
    ctx: HardeningContext,
    *,
    admin: BackupAdmin | None,
    walk: Callable[[], Walker],
    keys: Keyring | None,
    clock: Callable[[], dt.datetime] | None = None,
) -> HardeningPart:
    if ctx.docs is None:
        return HardeningPart("backup", ready=NO_STORE)
    s, docs, prefix = ctx.s, ctx.docs, ctx.s.firestore_prefix
    now, zone = clock or _clock(ctx), zone_of(s.user_timezone)
    ring = keys
    drill_log = DrillLog(docs, prefix=prefix, clock=now, zone=zone)
    status = BackupStatusService(docs, drill_log, prefix=prefix, clock=now, zone=zone)
    teller = Teller(status, ctx.notifier)
    rate = _rate(ctx)
    drill = None
    if admin is not None:
        deps = DrillDeps(s=s, admin=admin, walk=walk, live=read_only(docs), log=drill_log,
                         status=status, teller=teller, ring=ring, rate=rate, clock=now,
                         prefix=prefix)  # fmt: skip
        drill = Drill(deps)
    desk = BackupDesk(s=s, status=status, log=drill_log, drill=drill, rate=rate,
                      keyed=ring is not None, clock=now)  # fmt: skip
    canaries = CanaryStore(docs, prefix=prefix, zone=zone)
    canary_job = BackupCanaryJob(s=s, canaries=canaries, status=status,
                                 teller=teller, admin=admin, ring=ring, clock=now)  # fmt: skip
    ready = NO_FIRESTORE if admin is None else (READY if ring is not None else NO_KEY)
    return HardeningPart(
        "backup",
        tools=backup_tools(desk),
        daily_jobs=(canary_job, BackupDrillJob(drill)),
        privacy=(BackupsPrivacy(status),),
        vitals=(vitals_reader(desk),),
        services={"backup_status": status, "backup": desk},
        ready=ready,
    )


__all__ = ["NO_FIRESTORE", "NO_KEY", "NO_STORE", "READY", "admin_for", "build", "build_with"]
