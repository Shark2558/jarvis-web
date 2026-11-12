# src/jarvis/helpers/nudges/focus.py
"""The focus nudge of item 10 (D9): at his chosen times (OFF by default), "Top priority now"
with the top pending item from every part's pending sources (`ctx.pending_all()`, Part A's among
them). The ranking is D9's, in code: overdue, then due today, then urgency, then his own pin
(weight), then the due time: `ports.rank`, the one definition Part A's pending list uses too
(integrated review fixes). A `PendingItem` label is JARVIS's own words or his own (the port's
contract); it is cleaned to one short line. Nothing pending: nothing is sent (the slot is kept).
Nothing came back because a source failed: `NotNow`, so the claim is released and the next clock
run tries again (inside the slot's 30 minutes).
"""

from __future__ import annotations

from datetime import datetime

from jarvis.helpers.kinds import NudgeKind
from jarvis.helpers.nudges.models import NudgeSettings
from jarvis.helpers.nudges.schedule import due, slots
from jarvis.helpers.nudges.service import NotNow, NudgeService, Plan, minute_key
from jarvis.helpers.ports import MAX_LABEL, PendingItem, rank

KIND: NudgeKind = "nudge_focus"
TEXT = "Top priority now, Sir: {label}."


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
        got = await svc.pending(uid, now)
        top = rank(list(got.items))
        if top and label(top[0]):
            return TEXT.format(label=label(top[0]))
        if got.failed:
            raise NotNow("a pending source failed")  # not "nothing pending": retry next run
        return None

    return [Plan(KIND, minute_key(KIND, at), at, words)]


__all__ = ["KIND", "TEXT", "label", "plans", "rank"]
