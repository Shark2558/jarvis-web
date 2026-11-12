# src/jarvis/api/r11_1_wiring.py
"""R11.1 on the app (docs/plans/r11-1-observations.md "The I0 seams"): the four parts' one join.

- `wire_r11_1(app, s, docs, audit)`: builds each part (`jarvis.fixes.ports`) into
  `app.state.r111_parts`, BEFORE the R11 helpers are wired, so the parts' clock and daily jobs ride
  the helpers' two composites (`fix_clock_jobs` / `fix_daily_jobs`, read by `r11_wiring._wire`).
  A part whose build raises, or that names itself or a tool it doesn't own, is left empty
  ("setup failed") and the other three still run. With the helpers switched off the parts' jobs
  do not run; their tools and routes still work.
- `fix_tools(parts)`: every part's tools, for `tools.setup.build_gateway(r111=...)`.
- `install_r11_1_routes(app)`: the four parts' routers (`/v1/series`, `/v1/input`,
  `/v1/facegroups`, `/v1/picture`) (each part owns its `api/fix_<part>.py`).
- `fix_privacy_sources(app)`: the parts' privacy rows, for `api/personal.py`.
- `fix_phrases(app)` / `install_fix_phrases(app)`: the parts' No-AI phrase routers
  (`services["phrases"]`), put into `BrainMode` once, after the helpers' own (R11.1 I1,
  INTEGRATION-A 3.2), whether the helpers are on or off.
- `fix_brief(app)`: the parts' morning-brief contributors (`services["brief"]`), for the
  brief's Helpers lines (`r11_wiring.helpers_brief`; INTEGRATION-A 3.3).
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import Any

from fastapi import FastAPI

from jarvis.api.fix_files import router as files_router
from jarvis.api.fix_look import router as look_router
from jarvis.api.fix_photos import router as photos_router
from jarvis.api.fix_plan import router as plan_router
from jarvis.api.r4_wiring import _notifier
from jarvis.config import Settings
from jarvis.fixes.ports import PARTS, FixContext, FixPart, PartName, tool_allowed
from jarvis.logging import get_logger
from jarvis.privacy.ports import PrivacySource
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail
from jarvis.tools.base import Tool

log = get_logger(__name__)

PART_MODULES: Mapping[PartName, str] = {
    "plan": "jarvis.series.part",
    "files": "jarvis.understand.part",
    "photos": "jarvis.facegroups.part",
    "look": "jarvis.picture.part",
}
SETUP_FAILED = "setup failed"


def _build(name: PartName, ctx: FixContext) -> FixPart:
    part: FixPart = import_module(PART_MODULES[name]).build(ctx)
    return part


def check_part(name: PartName, part: object) -> FixPart:
    """The part's contract: its own name, and only tools inside its families."""
    if not isinstance(part, FixPart) or part.name != name:
        raise ValueError(f"part {name} must return FixPart({name!r})")
    bad = [t.name for t in part.tools if not tool_allowed(name, t.name)]
    if bad:
        raise ValueError(f"part {name} registers tools it doesn't own: {bad}")
    return part


def build_parts(ctx: FixContext) -> dict[PartName, FixPart]:
    built: dict[PartName, FixPart] = {}
    for name in PARTS:
        try:
            built[name] = check_part(name, _build(name, ctx))
        except Exception as exc:  # noqa: BLE001 - one part never stops the others or the app
            log.error(
                "R11.1 part left out: setup failed",
                extra={"part": name, "error": type(exc).__name__},
            )
            built[name] = FixPart(name, ready=SETUP_FAILED)
    return built


async def wire_r11_1(
    app: FastAPI, s: Settings, docs: Docs | None, audit: AuditTrail | None
) -> None:
    """The four parts on `app.state.r111_parts`, after R6 and before the R11 helpers."""
    st = app.state

    def late(name: str) -> Any:
        return getattr(st, name, None)

    ctx = FixContext(s=s, docs=docs, audit=audit, state=late, notifier=lambda: _notifier(app))
    st.r111_parts = build_parts(ctx)


def _parts(app: FastAPI) -> Mapping[PartName, FixPart]:
    return getattr(app.state, "r111_parts", None) or {}


def fix_tools(parts: Mapping[PartName, FixPart] | None) -> tuple[Tool, ...]:
    return tuple(t for p in (parts or {}).values() for t in p.tools)


def fix_clock_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    return tuple(j for p in _parts(app).values() for j in p.clock_jobs)


def fix_daily_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    return tuple(j for p in _parts(app).values() for j in p.daily_jobs)


def fix_privacy_sources(app: FastAPI) -> tuple[PrivacySource, ...]:
    return tuple(src for p in _parts(app).values() for src in p.privacy)


def fix_phrases(app: FastAPI) -> tuple[Any, ...]:
    """The parts' No-AI routers (`BrainMode.add_phrases`)."""
    return tuple(r for p in _parts(app).values() for r in p.services.get("phrases", ()) or ())


def install_fix_phrases(app: FastAPI) -> None:
    """Put the parts' phrases into the app's BrainMode once (a phrase already there is left),
    ONE AT A TIME (code review L1): a phrase that does not fit is an error in the log, with its
    name and how many were left, and never drops the others or stops the start. The AI still
    answers those words; in No-AI mode that phrase is not understood."""
    mode = getattr(app.state, "brain_mode", None)
    if mode is None:
        return
    new = [r for r in fix_phrases(app) if r not in mode.phrases]
    for n, router in enumerate(new, start=1):
        try:
            mode.add_phrases([router])
        except ValueError as exc:
            log.error(
                "an R11.1 phrase did not fit into No-AI mode",
                extra={
                    "phrase": getattr(router, "__name__", type(router).__name__),
                    "left": len(new) - n,
                    "reason": str(exc),
                },
            )


def fix_brief(app: FastAPI) -> tuple[Any, ...]:
    """The parts' brief contributors (`helpers.ports.BriefContributor`), read when the brief
    is made (a part built later, or one that has none, is simply absent)."""
    return tuple(c for p in _parts(app).values() if (c := p.services.get("brief")) is not None)


def install_r11_1_routes(app: FastAPI) -> None:
    for router in (plan_router, files_router, photos_router, look_router):
        app.include_router(router)


__all__ = [
    "PART_MODULES",
    "SETUP_FAILED",
    "build_parts",
    "check_part",
    "fix_brief",
    "fix_clock_jobs",
    "fix_daily_jobs",
    "fix_phrases",
    "fix_privacy_sources",
    "fix_tools",
    "install_fix_phrases",
    "install_r11_1_routes",
    "wire_r11_1",
]
