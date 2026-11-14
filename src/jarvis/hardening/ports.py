# src/jarvis/hardening/ports.py
"""The plug-in contract of R14 (docs/plans/r14-hardening.md "Part split", "The I0 seam list" 6).

Four parts are built in parallel. Each owns a module whose `build(ctx: HardeningContext) ->
HardeningPart` gets what it may use and hands back what the app wires for it; no part edits a
wiring file (`api/r14_wiring.py` leaves out a part that breaks this contract: "setup failed").

| Part        | Plan            | Module                    | Routes under                     |
|-------------|-----------------|---------------------------|----------------------------------|
| `backup`    | A · D3, D4      | `jarvis.backup.part`      | `/v1/backup`                     |
| `selfwatch` | B · D5–D7       | `jarvis.selfwatch.part`   | `/v1/selfwatch`                  |
| `skills`    | C · D8–D11      | `jarvis.skills.part`      | `/v1/skills`, `/v1/costs/ledger` |
| `noai`      | D · D1, D2, D12 | `jarvis.offline.r14_part` | none (its tool is R11's house's) |

- `HardeningPart`: its tools (names inside its `TOOL_FAMILIES`), its 5-minute jobs (`clock_jobs`,
  run first on both 5-minute paths and for the brief's owners, D7) and morning-tick jobs
  (`daily_jobs`), both only under the `R14_JOB_NAMES` its own, its privacy rows, its Vitals readers
  (`vitals`: `async (uid, now, tz) -> [OwnItem]`, items only under its own `VITALS_IDS`), the
  services the wiring or its own routes read (`SERVICE_OWNER`) and one plain status word.
- Named services the wiring reads: `backup_status` (A: `backup.ports.BackupStatus`, the ONE
  reader of the backups' facts for B and Vitals), `log_handler` (B: a `logging.Handler`, put once
  on the root logger), `tick_observer` (B: `ticks.TickObserver`, handed to every `run_jobs`),
  `offer` (C: `skills.ports.ToolOffer`, the brain's tool slot), `ledger` (C:
  `skills.ports.TokenLedger`, the brain's record slot), `phrases` (D: No-AI routers).
- `HardeningContext`: the settings, the document store, the audit chain, a LATE `state(name)`
  read of `app.state.<name>` (None when absent), the app's one notifier and a late read of Part
  A's backup status (None until A is built).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any, Literal, get_args
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from jarvis.backup.ports import BackupStatus
    from jarvis.config import Settings
    from jarvis.notify.ports import Notifier
    from jarvis.privacy.ports import PrivacySource
    from jarvis.storage.docs import Docs
    from jarvis.ticks import TickJob
    from jarvis.tools.audit import AuditTrail
    from jarvis.tools.base import Tool
    from jarvis.vitals.own import OwnItem

PartName = Literal["backup", "selfwatch", "skills", "noai"]
PARTS: tuple[PartName, ...] = get_args(PartName)
NOT_BUILT = "not built yet"

# The tool names a part may register (fnmatch patterns). D's `maint_service_request` is one of
# R11's house tools (`maint_*`, helpers/house/tools.py), so the `noai` part registers none.
TOOL_FAMILIES: Mapping[PartName, tuple[str, ...]] = {
    "backup": ("vitals_backups", "vitals_drill_start"),
    "selfwatch": (),
    "skills": ("skills_open",),
    "noai": (),
}
ROUTE_PREFIX: Mapping[PartName, tuple[str, ...]] = {
    "backup": ("/v1/backup",),
    "selfwatch": ("/v1/selfwatch",),
    "skills": ("/v1/skills", "/v1/costs/ledger"),
    "noai": (),
}
STATUS_ROUTE: Mapping[str, str] = {
    "backup": "/v1/backup",
    "selfwatch": "/v1/selfwatch",
    "skills": "/v1/skills",
}
R14_STATUS_ROUTE = "/v1/r14"  # every part's ready word (I0)
# Firestore collections (all `{prefix}<name>/...`); the guide's cards C66-C68 name every one.
COLLECTIONS: Mapping[PartName, tuple[str, ...]] = {
    "backup": ("backup_canary", "backup_status", "backup_drill", "backup_drills"),
    "selfwatch": ("selfwatch", "selfwatch_errors", "selfwatch_told"),
    "skills": ("token_ledger",),
    "noai": (),
}
# The jobs (beside R4's and R6's names); `selfwatch_clock` is the only 5-minute one.
R14_JOB_NAMES: tuple[str, ...] = (
    "backup_canary",
    "backup_drill",
    "selfwatch_daily",
    "selfwatch_clock",
)
JOB_OWNER: Mapping[str, PartName] = {
    "backup_canary": "backup",
    "backup_drill": "backup",
    "selfwatch_daily": "selfwatch",
    "selfwatch_clock": "selfwatch",
}
CLOCK_JOB_NAMES = frozenset({"selfwatch_clock"})
# A service only one part may offer.
SERVICE_OWNER: Mapping[str, PartName] = {
    "backup_status": "backup",
    "log_handler": "selfwatch",
    "tick_observer": "selfwatch",
    "offer": "skills",
    "ledger": "skills",
    "phrases": "noai",
}
# R14's Vitals items (ordinary Vitals items, so console-vitals.js is untouched) and their owners.
VITALS_IDS: Mapping[str, str] = {
    "backups": "Backups",
    "backup_drill": "Restore drill",
    "db_size": "Database size",
    "clocks": "JARVIS's clocks",
    "ai_parts": "Where the AI money goes",
}
VITALS_OWNER: Mapping[str, PartName] = {
    "backups": "backup",
    "backup_drill": "backup",
    "db_size": "backup",
    "clocks": "selfwatch",
    "ai_parts": "skills",
}
# Only the size rings from Vitals (amber 80 %, red 100 % of the free 1 GiB); the rest are said by
# their own kinds (`backup_problem`, `clock_stopped`) and never alerted from Vitals.
VITALS_QUIET = frozenset({"backups", "backup_drill", "clocks", "ai_parts"})
# Who raises each R14 alert kind (D4, D5): Part A alone the backup kinds, Part B the rest.
KIND_OWNER: Mapping[str, PartName] = {
    "job_failing": "selfwatch",
    "clock_stopped": "selfwatch",
    "brief_missed": "selfwatch",
    "errors_piling": "selfwatch",
    "spend_spike": "selfwatch",
    "deploy_changed": "selfwatch",
    "selfwatch_ok": "selfwatch",
    "backup_problem": "backup",
    "backup_ok": "backup",
}

VitalsReader = Callable[[str, datetime, ZoneInfo], Awaitable[Sequence["OwnItem"]]]


def tool_allowed(part: PartName, tool: str) -> bool:
    return any(fnmatchcase(tool, pattern) for pattern in TOOL_FAMILIES.get(part, ()))


@dataclass(frozen=True)
class HardeningPart:
    name: PartName
    tools: tuple[Tool, ...] = ()
    clock_jobs: tuple[TickJob, ...] = ()
    daily_jobs: tuple[TickJob, ...] = ()
    privacy: tuple[PrivacySource, ...] = ()
    vitals: tuple[VitalsReader, ...] = ()
    services: Mapping[str, Any] = field(default_factory=dict)
    ready: str = NOT_BUILT


@dataclass(frozen=True)
class HardeningContext:
    s: Settings
    docs: Docs | None
    audit: AuditTrail | None
    state: Callable[[str], Any]
    notifier: Callable[[], Notifier | None] = lambda: None
    backup_status: Callable[[], BackupStatus | None] = lambda: None


__all__ = [
    "CLOCK_JOB_NAMES",
    "COLLECTIONS",
    "JOB_OWNER",
    "KIND_OWNER",
    "NOT_BUILT",
    "PARTS",
    "R14_JOB_NAMES",
    "R14_STATUS_ROUTE",
    "ROUTE_PREFIX",
    "SERVICE_OWNER",
    "STATUS_ROUTE",
    "TOOL_FAMILIES",
    "VITALS_IDS",
    "VITALS_OWNER",
    "VITALS_QUIET",
    "HardeningContext",
    "HardeningPart",
    "PartName",
    "VitalsReader",
    "tool_allowed",
]
