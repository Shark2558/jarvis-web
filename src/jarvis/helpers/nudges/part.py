# src/jarvis/helpers/nudges/part.py
"""R11 Part C's plug-in (docs/plans/r11-free-helpers.md D2): `build(ctx)` returns everything the app
wires for stand-up, water, a planned activity that didn't happen, free-time ideas and the focus
nudge: the `nudge_*` / `freetime_*` tools, the clock jobs `nudges` and `activity_check`, the
privacy row `helpers_wellbeing`, a brief contributor, the No-AI phrases and the service the routes
(`api/helpers_nudges.py`) read.

Every nudge goes out through `ctx.sender` (the gate) with a `nudge_*` kind. The gate's own state
(snooze, stop, caps) is read and changed through I0's `GateStore` on the same documents the tab's
taps change (`/v1/helpers/gate/...`). His calendar is the Google connector (`ctx.google`, his
permission row decides each read); the rain hint for free time is Part B's weather when I1 joins
it (`ctx.rain`, see INTEGRATION-C.md), none until then. `calendar` / `rain` are for tests and the
eval (fakes).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.helpers.gate import GateStore
from jarvis.helpers.nudges.brief import NudgesBrief
from jarvis.helpers.nudges.calendar import (
    Agenda,
    CalendarSource,
    GoogleCalendar,
    RainSource,
    row_allows,
)
from jarvis.helpers.nudges.ideas import freetime_tools
from jarvis.helpers.nudges.jobs import ActivityJob, NudgesJob
from jarvis.helpers.nudges.phrases import PHRASES
from jarvis.helpers.nudges.privacy import wellbeing_privacy
from jarvis.helpers.nudges.service import NudgeService
from jarvis.helpers.nudges.store import NudgeStore, WellbeingStore
from jarvis.helpers.nudges.tools import nudge_tools
from jarvis.helpers.ports import HelperContext, HelperPart

READY = "ready"
READY_UNSEALED = "ready; the water and activity log is off (no token key)"


def _rain_from(ctx: HelperContext, rain: RainSource | None) -> Callable[[], RainSource | None]:
    if rain is not None:
        return lambda: rain
    joined: Any = getattr(ctx, "rain", None)  # I1: Part B's weather, read late
    return joined if callable(joined) else (lambda: None)


def service(
    ctx: HelperContext,
    *,
    calendar: CalendarSource | None = None,
    rain: RainSource | None = None,
) -> NudgeService:
    source = calendar or (GoogleCalendar(ctx.google) if ctx.google is not None else None)
    agenda = Agenda(source, allowed=row_allows(ctx.permissions), audit=ctx.audit, now=ctx.now)
    return NudgeService(
        store=NudgeStore(ctx.docs, prefix=ctx.prefix),
        well=WellbeingStore(ctx.docs, ctx.keyring, prefix=ctx.prefix),
        gate=GateStore(ctx.docs, prefix=ctx.prefix),
        sender=ctx.sender,
        agenda=agenda,
        rain=_rain_from(ctx, rain),
        pending=ctx.pending_all,
        tz=ctx.tz,
        now=ctx.now,
    )


def build(
    ctx: HelperContext,
    *,
    calendar: CalendarSource | None = None,
    rain: RainSource | None = None,
) -> HelperPart:
    svc = service(ctx, calendar=calendar, rain=rain)
    return HelperPart(
        name="nudges",
        tools=(*nudge_tools(svc), *freetime_tools(svc)),
        clock_jobs=(NudgesJob(svc, ctx.owners), ActivityJob(svc, ctx.owners)),
        privacy=(wellbeing_privacy(svc.store, svc.well),),
        brief=(NudgesBrief(svc),),
        phrases=PHRASES,
        services={"service": svc},
        ready=READY if svc.well.on else READY_UNSEALED,
    )


__all__ = ["READY", "READY_UNSEALED", "build", "service"]
