# src/jarvis/api/r14_wiring.py
"""R14 on the app (docs/plans/r14-hardening.md "The I0 seam list" 6, 7): the four parts' one join.

- `wire_r14(app, s, docs, audit)`: builds each part (`jarvis.hardening.ports`) into
  `app.state.r14_parts`, after the R11 helpers and BEFORE the gateway (their tools). A part whose
  build raises, or that names itself, a tool, a job or a service it doesn't own, is left empty
  ("setup failed") and the others still run. Then `install_services`: Part B's tick observer
  onto `app.state.tick_observer` (every `run_jobs` of the tick and the 5-minute route hands it
  each job's outcome) and its errors handler, once, onto the root logger; Part D's No-AI phrases.
- `r14_tools(parts)`: every part's tools, for `tools.setup.build_gateway(r14=...)`.
- `r14_tick_jobs(app)`: the parts' morning-tick jobs (`api/tick_wiring.tick_jobs`).
- `r14_clock_jobs(app)`: the parts' 5-minute jobs, first on both 5-minute paths (D7).
- `R14Vitals` / `app.state.r14_vitals`: the parts' Vitals items (`vitals.own.OwnSources.r14`).
- `r14_privacy_sources(app)`: the parts' privacy rows, for `api/personal.py`.
- `backup_status(app)`: Part A's `BackupStatus`, the one reader of the backups' facts.
- `bind_brain(app)`: Part C's offer and ledger into the brain's two slots (`Brain.slots`), the
  offer only while `tool_offer` is "by_skill", the ledger only while `token_ledger_enabled`.
- `install_r14_routes(app)`: `GET /v1/r14` and the parts' routers (`api/backup.py`,
  `api/selfwatch.py`, `api/skills.py`; each part owns its own).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from importlib import import_module
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from jarvis.api.backup import router as backup_router
from jarvis.api.r4_wiring import _notifier
from jarvis.api.r14_status import router as status_router
from jarvis.api.selfwatch import router as selfwatch_router
from jarvis.api.skills import router as skills_router
from jarvis.backup.ports import BackupStatus
from jarvis.config import Settings
from jarvis.hardening.ports import (
    CLOCK_JOB_NAMES,
    JOB_OWNER,
    PARTS,
    SERVICE_OWNER,
    VITALS_OWNER,
    HardeningContext,
    HardeningPart,
    PartName,
    tool_allowed,
)
from jarvis.logging import get_logger
from jarvis.privacy.ports import PrivacySource
from jarvis.skills.ports import BrainSlots
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail
from jarvis.tools.base import Tool
from jarvis.vitals.own import OwnItem

log = get_logger(__name__)

PART_MODULES: Mapping[PartName, str] = {
    "backup": "jarvis.backup.part",
    "selfwatch": "jarvis.selfwatch.part",
    "skills": "jarvis.skills.part",
    "noai": "jarvis.offline.r14_part",
}
SETUP_FAILED = "setup failed"
_INSTALLED: list[logging.Handler] = []  # the one errors handler on the root logger, or none


def _build(name: PartName, ctx: HardeningContext) -> HardeningPart:
    part: HardeningPart = import_module(PART_MODULES[name]).build(ctx)
    return part


def _check_jobs(name: PartName, part: HardeningPart) -> None:
    for job, clock in [(j, True) for j in part.clock_jobs] + [(j, False) for j in part.daily_jobs]:
        jname = getattr(job, "name", None)
        if JOB_OWNER.get(str(jname)) != name or (jname in CLOCK_JOB_NAMES) is not clock:
            where = "clock" if clock else "daily"
            raise ValueError(f"part {name} offers a {where} job it doesn't own: {jname}")


def check_part(name: PartName, part: object) -> HardeningPart:
    """The part's contract: its own name, and only the tools, jobs and services it owns."""
    if not isinstance(part, HardeningPart) or part.name != name:
        raise ValueError(f"part {name} must return HardeningPart({name!r})")
    bad = [t.name for t in part.tools if not tool_allowed(name, t.name)]
    if bad:
        raise ValueError(f"part {name} registers tools it doesn't own: {bad}")
    _check_jobs(name, part)
    taken = [k for k, owner in SERVICE_OWNER.items() if k in part.services and owner != name]
    if taken:
        raise ValueError(f"part {name} offers services it doesn't own: {taken}")
    return part


def build_parts(ctx: HardeningContext) -> dict[PartName, HardeningPart]:
    built: dict[PartName, HardeningPart] = {}
    for name in PARTS:
        try:
            built[name] = check_part(name, _build(name, ctx))
        except Exception as exc:  # noqa: BLE001 - one part never stops the others or the app
            log.error(
                "R14 part left out: setup failed",
                extra={"part": name, "error": type(exc).__name__},
            )
            built[name] = HardeningPart(name, ready=SETUP_FAILED)
    return built


def _parts(app: FastAPI) -> Mapping[PartName, HardeningPart]:
    return getattr(app.state, "r14_parts", None) or {}


def backup_status(app: FastAPI) -> BackupStatus | None:
    part = _parts(app).get("backup")
    status = part.services.get("backup_status") if part is not None else None
    return status if callable(getattr(status, "facts", None)) else None


async def wire_r14(app: FastAPI, s: Settings, docs: Docs | None, audit: AuditTrail | None) -> None:
    """The four parts on `app.state.r14_parts`, after R11 and before the gateway."""
    st = app.state

    def late(name: str) -> Any:
        return getattr(st, name, None)

    ctx = HardeningContext(
        s=s,
        docs=docs,
        audit=audit,
        state=late,
        notifier=lambda: _notifier(app),
        backup_status=lambda: backup_status(app),
    )
    st.r14_parts = build_parts(ctx)
    st.r14_vitals = R14Vitals(st.r14_parts)
    install_services(app)


def install_services(app: FastAPI) -> None:
    """Part B's tick observer and errors handler, Part D's phrases (each from its one owner)."""
    services = {k: p.services[k] for p in _parts(app).values() for k in p.services}
    observer = services.get("tick_observer")
    app.state.tick_observer = observer if callable(observer) else None
    handler = services.get("log_handler")
    if isinstance(handler, logging.Handler):
        install_log_handler(handler)
    install_r14_phrases(app)


def install_log_handler(handler: logging.Handler | None) -> None:
    """Exactly one R14 errors handler on the root logger: a new one replaces the old (an app
    built twice, as in the tests, never stacks two); None takes it off."""
    root = logging.getLogger()
    for old in _INSTALLED:
        root.removeHandler(old)
    _INSTALLED.clear()
    if handler is not None:
        root.addHandler(handler)
        _INSTALLED.append(handler)


def remove_log_handler(app: FastAPI) -> None:
    """At shutdown (I1): this app's errors handler comes off the root logger, so an app that has
    stopped never counts errors into its own state; another app's handler stays."""
    handler = _parts(app).get("selfwatch", HardeningPart("selfwatch")).services.get("log_handler")
    if handler in _INSTALLED:
        install_log_handler(None)


def install_r14_phrases(app: FastAPI) -> None:
    """Part D's phrases into the app's BrainMode once, ONE AT A TIME (as R11.1's and R7's): one
    that does not fit is an error in the log and never drops the others or stops the start."""
    mode = getattr(app.state, "brain_mode", None)
    part = _parts(app).get("noai")
    if mode is None or part is None:
        return
    new = [r for r in part.services.get("phrases", ()) or () if r not in mode.phrases]
    for n, router in enumerate(new, start=1):
        try:
            mode.add_phrases([router])
        except ValueError as exc:
            log.error(
                "an R14 phrase did not fit into No-AI mode",
                extra={
                    "phrase": getattr(router, "__name__", type(router).__name__),
                    "left": len(new) - n,
                    "reason": str(exc),
                },
            )


def r14_tools(parts: Mapping[PartName, HardeningPart] | None) -> tuple[Tool, ...]:
    return tuple(t for p in (parts or {}).values() for t in p.tools)


def r14_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    return tuple(j for p in _parts(app).values() for j in p.daily_jobs)


def r14_clock_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    return tuple(j for p in _parts(app).values() for j in p.clock_jobs)


def r14_privacy_sources(app: FastAPI) -> tuple[PrivacySource, ...]:
    return tuple(src for p in _parts(app).values() for src in p.privacy)


class R14Vitals:
    """`vitals.own.R14Reader`: every part's Vitals items, each part only under its own ids; a
    reader that raises is logged and the others still show."""

    def __init__(self, parts: Mapping[PartName, HardeningPart]) -> None:
        self._parts = parts

    async def items(self, uid: str, now: datetime, tz: ZoneInfo) -> Sequence[OwnItem]:
        out: list[OwnItem] = []
        for name, part in self._parts.items():
            for read in part.vitals:
                try:
                    got = await read(uid, now, tz)
                except Exception as exc:  # noqa: BLE001 - one part never breaks the board
                    log.warning(
                        "R14 vitals unreadable", extra={"part": name, "error": type(exc).__name__}
                    )
                    continue
                out.extend(i for i in got if VITALS_OWNER.get(i.provider.id) == name)
        return out


def bind_brain(app: FastAPI) -> None:
    """Part C's services into the brain's two slots (after the brain is built)."""
    st = app.state
    brain = getattr(st, "brain", None)
    part = _parts(app).get("skills")
    if brain is None or part is None:
        return
    s: Settings = st.settings
    offer = part.services.get("offer") if s.tool_offer == "by_skill" else None
    ledger = part.services.get("ledger") if s.token_ledger_enabled else None
    brain.slots = BrainSlots(
        offer=offer if callable(offer) else None,
        ledger=ledger if callable(getattr(ledger, "record", None)) else None,
    )


def install_r14_routes(app: FastAPI) -> None:
    for router in (status_router, backup_router, selfwatch_router, skills_router):
        app.include_router(router)


__all__ = [
    "PART_MODULES",
    "SETUP_FAILED",
    "R14Vitals",
    "backup_status",
    "bind_brain",
    "build_parts",
    "check_part",
    "install_log_handler",
    "remove_log_handler",
    "install_r14_phrases",
    "install_r14_routes",
    "install_services",
    "r14_clock_jobs",
    "r14_privacy_sources",
    "r14_tick_jobs",
    "r14_tools",
    "wire_r14",
]
