# src/jarvis/helpers/today/part.py
"""R11 Part A's plug-in (docs/plans/r11-free-helpers.md D2): `build(ctx)` returns everything the app
wires for bills and the prepared UPI payment, birthdays, top priority and what is pending.

Only `ctx` is used: its docs, keyring (None: bills are OFF, never in clear; birthdays and the top
priority still work), Google link (None: birthdays and to-dos say "connect Google"), the part's
own sender, the owner's live permission rows, the audit, the owners, the zone, the clock and
`pending_all()` (read late, so it sees every part). The services in `HelperPart.services` are
what `api/helpers_today.py` reads per request.
"""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.helpers.ports import HelperContext, HelperPart, PendingSource
from jarvis.helpers.today.bills import BillsService
from jarvis.helpers.today.birthdays import BirthdayReader
from jarvis.helpers.today.brief import TodayBrief
from jarvis.helpers.today.focus import ReadDeps, read_tools
from jarvis.helpers.today.jobs import BillsDueJob, BirthdaysJob
from jarvis.helpers.today.pending import BillsPending, GoogleTasksDue, PendingService, TasksPending
from jarvis.helpers.today.phrases import PHRASES
from jarvis.helpers.today.privacy import bills_privacy, birthdays_privacy
from jarvis.helpers.today.store import BillStore, Claims
from jarvis.helpers.today.tools import bill_tools

BILLS_TOLD, BIRTHDAYS_TOLD = "bills_told", "birthdays_told"
BILLS_KEEP_DAYS, BIRTHDAYS_KEEP_DAYS = 60, 400
READY = "Bills, birthdays and your top priority are ready."
READY_NO_KEY = "Birthdays and your top priority are ready; bills are off (no token key)."


def _with_own(
    everyone: Sequence[PendingSource], own: Sequence[PendingSource]
) -> tuple[PendingSource, ...]:
    """Every part's sources, with Part A's own included once (they are in `pending_all()` once
    the app has built the part; a test context may not have them)."""
    seen = {id(s) for s in everyone}
    return (*everyone, *(s for s in own if id(s) not in seen))


def build(ctx: HelperContext) -> HelperPart:
    store = BillStore(ctx.docs, ctx.keyring, prefix=ctx.prefix)
    bills = BillsService(store, tz=ctx.tz, now=ctx.now)
    reader = BirthdayReader(ctx.google, permissions=ctx.permissions, audit=ctx.audit, now=ctx.now)
    bills_told = Claims(ctx.docs, BILLS_TOLD, prefix=ctx.prefix, keep_days=BILLS_KEEP_DAYS)
    told = Claims(ctx.docs, BIRTHDAYS_TOLD, prefix=ctx.prefix, keep_days=BIRTHDAYS_KEEP_DAYS)
    own: list[PendingSource] = [BillsPending(bills)]
    if ctx.google is not None:
        tasks = GoogleTasksDue(ctx.google)
        own.append(TasksPending(tasks, permissions=ctx.permissions, tz=ctx.tz))
    pending = PendingService(lambda: _with_own(ctx.pending_all(), own))
    reads = ReadDeps(pending=pending, birthdays=reader, tz=ctx.tz, now=ctx.now)
    common = {"owners": ctx.owners, "tz": ctx.tz, "now": ctx.now}
    return HelperPart(
        name="today",
        tools=(*bill_tools(bills), *read_tools(reads)),
        clock_jobs=(
            BillsDueJob(bills, bills_told, ctx.sender, **common),  # type: ignore[arg-type]
            BirthdaysJob(bills, reader, told, ctx.sender, **common),  # type: ignore[arg-type]
        ),
        privacy=(bills_privacy(bills, bills_told), birthdays_privacy(told)),
        brief=(TodayBrief(bills, reader, pending),),
        pending=tuple(own),
        phrases=PHRASES,
        services={"bills": bills, "birthdays": reader, "pending": pending},
        ready=READY if store.available else READY_NO_KEY,
    )


__all__ = ["BILLS_TOLD", "BIRTHDAYS_TOLD", "build"]
