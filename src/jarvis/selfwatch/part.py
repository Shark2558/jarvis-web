# src/jarvis/selfwatch/part.py
"""R14 Part B (self-health): the part's one join with the app (`jarvis.hardening.ports`,
docs/plans/r14-hardening.md D5-D7).

`build(ctx)` gives the app, while `selfwatch_enabled` (on by default):

- `clock_jobs`: `selfwatch_clock` (run first on both 5-minute paths, for the brief's owners);
- `daily_jobs`: `selfwatch_daily` (the morning tick);
- `services`: `tick_observer` (every job's outcome from the tick, the watchdog and the Home-off
  route) and `log_handler` (the errors handler, installed once on the root logger), and
  `status` (read by `GET /v1/selfwatch`);
- `vitals`: the item `clocks`; `privacy`: the row `selfwatch_told`.

Everything it needs from the app is read late (the brief, the billing, the notifier), so the
part is built before them. No tool, no model call, no money: plain code on the existing clocks.
Without a document store (never in the app) it watches in memory only.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from jarvis import __version__
from jarvis.hardening.ports import HardeningContext, HardeningPart, VitalsReader
from jarvis.selfwatch.jobs import Watch
from jarvis.selfwatch.status import READY, Status, ToldPrivacy
from jarvis.selfwatch.vitals import clocks_item
from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.own import OwnItem

OFF = "off"


def vitals_of(watch: Watch) -> tuple[VitalsReader, ...]:
    async def clocks(uid: str, now: datetime, tz: ZoneInfo) -> Sequence[OwnItem]:
        return [clocks_item(await watch.clocks.read(watch.docs), now, tz)]

    return (clocks,)


def watch_of(ctx: HardeningContext) -> Watch:
    def late(name: str) -> Any:
        return lambda: ctx.state(name)

    return Watch(
        ctx.s,
        ctx.docs if ctx.docs is not None else MemoryDocs(),
        notifier=ctx.notifier,
        brief=late("brief"),
        billing=late("billing"),
        version=__version__,
    )


def build(ctx: HardeningContext) -> HardeningPart:
    if not ctx.s.selfwatch_enabled:
        return HardeningPart("selfwatch", ready=OFF)
    watch = watch_of(ctx)
    return HardeningPart(
        "selfwatch",
        clock_jobs=(watch.clock_job,),
        daily_jobs=(watch.daily_job,),
        privacy=(ToldPrivacy(watch),),
        vitals=vitals_of(watch),
        services={
            "tick_observer": watch.observe,
            "log_handler": watch.errors,
            "status": Status(watch),
        },
        ready=READY,
    )


__all__ = ["OFF", "build", "vitals_of", "watch_of"]
