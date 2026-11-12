# src/jarvis/series/part.py
"""R11.1 Part A (Brain and calendar): the part's one join with the app (`jarvis.fixes.ports`).

What `build(ctx)` hands back:

- tools (through the gateway): `calendar_create_events` and `calendar_undo_events`
  (`series.batch`), `series_list`, `series_checkin` and `series_reschedule` (`series.tools`), and
  `gmail_inbox_summary` (`tools.gmail_digest`). The batch and the inbox summary work without
  plans; the `series_*` tools and the check-in job need `series_enabled` and a document store.
- `clock_jobs`: `series_checkin` (`series.job`), on the helpers' 5-minute clock.
- `privacy`: the "Calendar plans you follow" row.
- `services` (read by `api/fix_plan.py` per request, and by I1's wiring):
      series     the `SeriesService` (None: plans are off)
      brief      the brief's line for open check-ins (a `BriefContributor`)
      phrases    the No-AI routers (`BrainMode.add_phrases`)
      ensure     puts those routers into the app's BrainMode, once (see below)
- `ready`: one plain phrase.

On a server where the Google tools are off (outside dev: no Google client, or no key to keep its
tokens: `integrations.google.google_tools_configured`), the part offers no tool and runs no job,
as the single-event calendar and mail tools do; only its privacy row stays, so what was kept can
still be seen and deleted. In dev the tools are always there and say "Google is not linked".

Everything built around this part (Google, Recently deleted, the gateway, the helpers' clock, the
brain-mode switch) is read through `ctx.state(...)` when a call runs, never here. The No-AI
phrases are put into the app's one `BrainMode` the first time the part is called (`ensure`),
because the wiring has no slot for them yet (INTEGRATION-A.md, "Needs I1").
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from jarvis.fixes.ports import FixContext, FixPart
from jarvis.integrations.google import google_tools_configured
from jarvis.logging import get_logger
from jarvis.series.batch import BatchAPI
from jarvis.series.batch_tools import batch_tools
from jarvis.series.brief import PlansBrief
from jarvis.series.job import CheckinJob
from jarvis.series.phrases import route
from jarvis.series.privacy import series_privacy
from jarvis.series.service import SeriesService
from jarvis.series.store import SeriesStore
from jarvis.series.tools import series_tools
from jarvis.tools.base import Tool
from jarvis.tools.gmail_digest import inbox_tools

log = get_logger(__name__)

READY = "ready"
OFF_SWITCH = "ready: batches and the inbox summary; plans are off (JARVIS_SERIES_ENABLED)"
OFF_STORE = "ready: batches and the inbox summary; plans are off (no document store)"
OFF_GOOGLE = "off: Google is not set up on this server"
SERVICE, BRIEF, PHRASES, ENSURE = "series", "brief", "phrases", "ensure"


def _clock(ctx: FixContext) -> Callable[[], datetime]:
    """The helpers' clock when the app has one (read late), else UTC now."""

    def now() -> datetime:
        clock = ctx.state("helpers_now")
        return clock() if callable(clock) else datetime.now(UTC)

    return now


def _phrases(ctx: FixContext) -> Callable[[], bool]:
    """Put the plan phrases into the app's BrainMode, once. True when they are in."""

    told: list[object] = []  # the BrainMode already told about a full phrasebook (once)

    def ensure() -> bool:
        mode = ctx.state("brain_mode")
        if mode is None:
            return False
        if route not in mode.phrases:
            try:
                mode.add_phrases([route])
            except ValueError:  # the phrasebook is full: the AI still answers
                if not any(m is mode for m in told):
                    told.append(mode)
                    log.warning("the plan phrases did not fit into No-AI mode")
                return False
        return True

    return ensure


def _without_google(ctx: FixContext) -> FixPart:
    """No tool and no job; the privacy row over what an earlier set-up may have kept."""
    kept = SeriesStore(ctx.docs, prefix=ctx.prefix) if ctx.docs is not None else None
    return FixPart(
        "plan",
        privacy=(series_privacy(kept),) if kept is not None else (),
        services={SERVICE: None, PHRASES: (), ENSURE: lambda: False},
        ready=OFF_GOOGLE,
    )


def build(ctx: FixContext) -> FixPart:
    s, now = ctx.s, _clock(ctx)
    if s.env != "dev" and not google_tools_configured(s):
        return _without_google(ctx)

    def google() -> Any:
        return ctx.state("google")

    svc: SeriesService | None = None
    if s.series_enabled and ctx.docs is not None:
        store = SeriesStore(ctx.docs, prefix=ctx.prefix)
        svc = SeriesService(store, now=now, tz=s.user_timezone, google=google)
    api = BatchAPI(
        google,
        lambda: ctx.state("undo"),
        limit=s.calendar_batch_max,
        tz=s.user_timezone,
        book=svc,
    )
    tools: list[Tool] = batch_tools(api, limit=s.calendar_batch_max)
    tools += inbox_tools(google, max_reads=s.mail_summary_max_reads)
    ensure = _phrases(ctx)
    services: dict[str, Any] = {SERVICE: svc, PHRASES: (route,), ENSURE: ensure}
    if svc is None:
        ready = OFF_SWITCH if not s.series_enabled else OFF_STORE
        return FixPart("plan", tools=tuple(tools), services=services, ready=ready)
    tools += series_tools(svc, lambda: ctx.state("gateway"))
    notifier = ctx.notifier if ctx.notifier is not None else (lambda: None)
    job = CheckinJob(svc, notifier, now=now, tz=s.user_timezone, on_run=ensure)
    return FixPart(
        "plan",
        tools=tuple(tools),
        clock_jobs=(job,),
        privacy=(series_privacy(svc.store),),
        services={**services, BRIEF: PlansBrief(svc)},
        ready=READY,
    )


__all__ = ["BRIEF", "ENSURE", "PHRASES", "SERVICE", "build"]
