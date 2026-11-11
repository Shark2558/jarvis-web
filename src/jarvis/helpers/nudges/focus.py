# src/jarvis/helpers/nudges/focus.py
"""The focus nudge of item 10 (D9): at his chosen times (OFF by default), "Top priority now"
with the top pending item from every part's pending sources (`ctx.pending_all()`, Part A's among
them). The ranking is D9's, in code: overdue, then due today, then urgency, then his own pin
(weight), then the due time. A `PendingItem` label is JARVIS's own words or his own (the port's
contract); it is cleaned to one short line. Nothing pending: nothing is sent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from jarvis.helpers.kinds import NudgeKind
from jarvis.helpers.nudges.models import NudgeSettings
from jarvis.helpers.nudges.schedule import due, slots
from jarvis.helpers.nudges.service import NudgeService, Plan, minute_key
from jarvis.helpers.ports import MAX_LABEL, PendingItem

KIND: NudgeKind = "nudge_focus"
TEXT = "Top priority now, Sir: {label}."
_ORDER = {"overdue": 0, "today": 1, "soon": 2, "later": 3}
_LAST = datetime.max.replace(tzinfo=UTC)


def rank(items: list[PendingItem]) -> list[PendingItem]:
    def key(i: PendingItem) -> tuple[int, int, datetime]:
        when = i.due if i.due is None or i.due.tzinfo else i.due.replace(tzinfo=UTC)
        return (_ORDER.get(i.urgency, 4), -i.weight, when or _LAST)

    return sorted(items, key=key)


def label(item: PendingItem) -> str:
    one = " ".join("".join(c if c.isprintable() else " " for c in item.label).split())
    return one[:MAX_LABEL].rstrip(" .")


def plans(svc: NudgeService, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
    n = s.nudge(KIND)
    if not n.on:
        return []
    at = due(slots(KIND, n, svc.day_of(now), svc.zone), now)
    if at is None:
        return []

    async def words() -> str | None:
        top = rank(await svc.pending(uid, now))
        return TEXT.format(label=label(top[0])) if top and label(top[0]) else None

    return [Plan(KIND, minute_key(KIND, at), at, words)]


__all__ = ["KIND", "TEXT", "label", "plans", "rank"]
