# src/jarvis/series/sync.py
"""A followed plan kept true to the owner's calendar (R11.1 O2b; code review M1; Layer 5). Pure:
no I/O. The owner may move or delete a session's event himself in Google Calendar; JARVIS's
record follows him, so it never asks about an event that is gone, asks after the time he chose,
plans around the sessions he placed by hand, and never adds a second row for one session.

- `span_of`: an event's start and end (a timed event; None for an all-day entry).
- `synced`: the plan as his calendar has it now: a session whose event moved takes the new time;
  one whose event is gone (and only when the listing was complete) is `removed`. A done session
  keeps its answer.
- `carried`: those changes put onto the plan as it is stored now (a transaction may re-read it).
- `relinked`: a batch item made again (its event was deleted by hand, then the list was sent
  again) fills its old row with the new event instead of adding a session.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from jarvis.series.models import Plan, PlanSession
from jarvis.tools.calendar_batch import Made

KEEPS_ITS_ANSWER = frozenset({"done", "removed"})


def _when(part: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(part["dateTime"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else None


def span_of(event: Mapping[str, Any]) -> tuple[datetime | None, datetime | None]:
    return _when(event.get("start")), _when(event.get("end"))


def session_synced(
    s: PlanSession, event: Mapping[str, Any] | None, *, complete: bool = True, now: datetime
) -> PlanSession:
    """One session as its event is now (None: the event is gone)."""
    if event is None or event.get("status") == "cancelled":
        if complete and s.batch and s.state not in KEEPS_ITS_ANSWER:
            return s.model_copy(update={"state": "removed", "answered_at": now})
        return s
    start, end = span_of(event)
    if start is None or end is None or end <= start or (start, end) == (s.start, s.end):
        return s
    return s.model_copy(update={"start": start, "end": end})


def synced(
    plan: Plan, events: Mapping[str, Mapping[str, Any]], *, complete: bool, now: datetime
) -> Plan:
    """`events`: the plan's events by id as Google has them now. `complete`: the listing held
    every one of them (else nothing is taken for deleted)."""
    rows = [
        session_synced(s, events.get(s.event_id), complete=complete, now=now) for s in plan.sessions
    ]
    return plan if rows == plan.sessions else plan.model_copy(update={"sessions": rows})


def carried(stored: Plan, fresh: Plan) -> Plan:
    """`fresh`'s times and removals put onto `stored` (by event id); his answers stay."""
    by_id = {s.event_id: s for s in fresh.sessions}
    rows: list[PlanSession] = []
    for s in stored.sessions:
        f = by_id.get(s.event_id)
        if f is None:
            rows.append(s)
            continue
        update: dict[str, Any] = {"start": f.start, "end": f.end}
        if f.state == "removed" and s.state not in KEEPS_ITS_ANSWER:
            update.update(state="removed", answered_at=f.answered_at)
        rows.append(s.model_copy(update=update))
    return stored.model_copy(update={"sessions": rows})


def relinked(
    sessions: Sequence[PlanSession], new: Sequence[Made], title_max: int
) -> tuple[list[PlanSession], list[Made]]:
    """(the rows with re-made batch items filled in, the events that are new sessions)."""
    rows = list(sessions)
    at = {(s.batch, s.item): i for i, s in enumerate(rows) if s.batch and s.item}
    rest: list[Made] = []
    for m in new:
        i = at.get((m.batch, m.n))
        if i is None:
            rest.append(m)
            continue
        old = rows[i]
        update: dict[str, Any] = {
            "event_id": m.event_id,
            "title": m.title[:title_max],
            "start": m.start,
            "end": m.end,
        }
        if old.state == "removed":
            update.update(state="planned", answered_at=None)
        rows[i] = old.model_copy(update=update)
    return rows, rest


__all__ = ["carried", "relinked", "session_synced", "span_of", "synced"]
