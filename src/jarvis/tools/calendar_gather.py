# src/jarvis/tools/calendar_gather.py
"""Many single calendar creates of one round become ONE batch card (R11.1 O2; docs/plans/
r11-1-observations.md D4; Layer 4/5). O2's root cause was a brain that made sixty single
`calendar_create_event` calls: five cards a message, six rounds, one event made. `gathered`
turns more than `MANY` valid single creates without guests into one `calendar_create_events`
call per `limit` events before the gateway sees them, so the owner still gets one card that
lists everything. Each call must meet the batch's own limits (`calendar_batch.item_problem`):
one that does not is answered alone with its plain reason, and the good ones still go on the
card. The Brain calls it around each round (`core.brain._run_calls`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.tools.base import Tool
from jarvis.tools.calendar_batch import CREATE, SINGLE, item_problem
from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.tools.registry import ToolRegistry

log = get_logger(__name__)

MANY = 3  # more single creates than this in one round become one batch card
MERGED = (
    "Not run on its own: more than three events were asked for at once, so this one is on the "
    "single approval card for all of them (see the first result). Do not create it again. Next "
    "time put every event into one calendar_create_events call."
)
NOT_MADE = (
    "Not run: it was gathered with other events into one calendar_create_events call, and that "
    "batch was not made (see the first result). Nothing was created."
)
TOO_BIG = "Not run: this event can't go on the batch card ({why}). Fix it and send it again."

Spread = Callable[[list[GatewayResult]], list[GatewayResult]]


def gathered(
    calls: Sequence[ToolCall], registry: ToolRegistry, limit: int
) -> tuple[list[ToolCall], Spread]:
    """One round's calls as the gateway should see them, and how to give every original call its
    result back. More than `MANY` valid single creates without guests become one batch call per
    `limit` events, in place of the first of them; the others are answered `MERGED` (or
    `NOT_MADE` when their batch was not made). A call the batch's own limits refuse is answered
    alone with its plain reason (`TOO_BIG`); the good ones still go on the one card."""
    single, batch = registry.get(SINGLE), registry.get(CREATE)
    mergeable = [i for i, c in enumerate(calls) if _mergeable(c, single)]
    if single is None or batch is None or len(mergeable) <= MANY:
        return list(calls), lambda out: out
    refused = {i: why for i in mergeable if (why := item_problem(calls[i].arguments))}
    good = [i for i in mergeable if i not in refused]
    heads: dict[int, ToolCall] = {}
    head_of: dict[int, int] = {}
    for at in range(0, len(good), limit):
        part = good[at : at + limit]
        events = [dict(calls[i].arguments) for i in part]
        heads[part[0]] = ToolCall(id=calls[part[0]].id, name=CREATE, arguments={"events": events})
        head_of.update(dict.fromkeys(part, part[0]))
    merged = set(good) - set(heads)
    run = [heads.get(i, c) for i, c in enumerate(calls) if i not in merged and i not in refused]

    def spread(out: list[GatewayResult]) -> list[GatewayResult]:
        results = iter(out)
        back: dict[int, GatewayResult] = {}
        for i in range(len(calls)):
            if i not in merged and i not in refused:
                back[i] = next(results)
        made = (GatewayOutcome.AWAITING_CONFIRMATION, GatewayOutcome.EXECUTED)
        for i in merged:
            ok = back[head_of[i]].outcome in made
            back[i] = GatewayResult(GatewayOutcome.DENIED, error=MERGED if ok else NOT_MADE)
        for i, why in refused.items():
            back[i] = GatewayResult(GatewayOutcome.DENIED, error=TOO_BIG.format(why=why))
        return [back[i] for i in range(len(calls))]

    log.info(
        "single creates gathered into a batch",
        extra={"events": len(good), "refused": len(refused)},
    )
    return run, spread


def _mergeable(call: ToolCall, single: Tool | None) -> bool:
    if single is None or call.name != SINGLE or call.arguments.get("attendees"):
        return False
    try:
        single.validate(call.arguments)
    except ValueError:
        return False
    return True


__all__ = ["MANY", "MERGED", "NOT_MADE", "TOO_BIG", "gathered"]
