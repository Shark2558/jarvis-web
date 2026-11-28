# src/jarvis/helpers/nudges/posture.py
"""R8 row 181 (docs/plans/r8-vision.md 4.7; I0 seam S15, builder C): the posture nudge.

The home camera's posture rule (`jarvis.coach.home.posture`, on the home laptop) marks a slouch
held 60 seconds with a `tip` widget carrying the span's start (`since`) and how long it was held.
The cloud's coach-report handler (I1) passes each posture report to `on_report`, which asks
`PostureNudger.slouched` once per span. A nudge goes out only when:

- he switched the posture nudge on (`nudge_posture`, off until then) and it is inside its window
  and on one of its days (Helpers -> Nudges);
- this span has not been nudged (its start is the claim key: never twice for one slouch);
- fewer than `POSTURE_PER_HOUR` (3) posture nudges went out in the last hour and fewer than
  `POSTURE_PER_DAY` (8) today, whatever caps he set (the gate then applies his caps, snooze, stop
  and quiet hours as for every nudge).

The message is one fixed sentence (`jarvis.coach.words.POSTURE_NUDGE`). No count, angle or time
is in any message or log line. **Only the owner is nudged** (R8 I1, the review's safety item): a
report about "me" may nudge; a report about anyone else (a person he enrolled, `fp_`, or a body
the camera did not know, a guest) never does, though their tallies are still kept (D6). It
implements `jarvis.coach.ports.PostureNudge`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.coach.words import POSTURE_NUDGE
from jarvis.helpers.kinds import POSTURE_PER_DAY, POSTURE_PER_HOUR, NudgeKind
from jarvis.helpers.nudges.schedule import in_window
from jarvis.helpers.nudges.service import NudgeService, Plan, fixed
from jarvis.logging import get_logger

log = get_logger(__name__)

KIND: NudgeKind = "nudge_posture"
TEXT = POSTURE_NUDGE
HOLD_S = 60.0  # the home rule's own hold (jarvis.coach.home.posture.HOLD_S)
USE = "posture"
OWNER = "me"  # the only `who` a posture nudge is ever sent for (R8 I1)
_SENT = frozenset({"rang", "silent", "held"})  # what counts toward the caps (the gate's own)
_DELIVERED = frozenset({"rang", "silent"})


def _minute(at: datetime) -> str:
    return at.astimezone(UTC).replace(second=0, microsecond=0).isoformat()


class PostureNudger:
    """`PostureNudge` over Part C's nudge service (its store, the gate and its sender)."""

    def __init__(self, svc: NudgeService) -> None:
        self._svc = svc

    async def slouched(self, uid: str, *, held_s: float, at: float) -> bool:
        """A slouch held `held_s` seconds as of `at` (unix seconds): one nudge for its span,
        inside his switch, window and the caps. True when it reached him."""
        if not isinstance(held_s, int | float) or held_s < HOLD_S or held_s > 86_400:
            return False
        svc = self._svc
        now = svc.now()
        settings = await svc.settings(uid)
        n = settings.nudge(KIND)
        if not n.on or not in_window(n, now, svc.zone):
            return False
        if not await self._room(uid, now):
            log.info("posture nudge capped")
            return False
        since = round(float(at) - float(held_s))
        plan = Plan(KIND, f"{KIND}@s{since}", now, fixed(TEXT))
        outcome = await svc.deliver(uid, plan)
        log.info("posture nudge", extra={"outcome": outcome.split(":", 1)[0]})
        return outcome in _DELIVERED

    async def _room(self, uid: str, now: datetime) -> bool:
        """Fewer than 3 posture nudges in the last hour and 8 today (his own caps aside)."""
        svc = self._svc
        today = svc.day_of(now).isoformat()
        hour_ago = _minute(now - timedelta(hours=1))
        days = sorted({svc.day_of(now - timedelta(hours=1)).isoformat(), today})
        counted: list[tuple[str, dict[str, str]]] = [
            (day, e)
            for day in days
            for e in await svc.gate.sends(uid, day)
            if e.get("k") == KIND and e.get("o") in _SENT
        ]
        in_hour = sum(1 for _, e in counted if e.get("at", "") > hour_ago)
        on_day = sum(1 for day, _ in counted if day == today)
        return in_hour < POSTURE_PER_HOUR and on_day < POSTURE_PER_DAY


def _tips(view: Iterable[Mapping[str, Any]]) -> list[tuple[float, float]]:
    out = []
    for w in view:
        since, held = w.get("since"), w.get("held")
        if w.get("kind") != "tip" or w.get("text") != TEXT:
            continue
        if isinstance(since, int) and not isinstance(since, bool) and isinstance(held, int | float):
            out.append((float(since), float(held)))
    return out


async def on_report(nudger: Any, uid: str, report: Any) -> bool:
    """A home camera's coach report (`jarvis.home.ports.CoachReport`): a posture span's nudge,
    if its view asks for one and it is about him ("me"); nobody else is ever nudged."""
    if getattr(report, "use", None) != USE or getattr(report, "who", None) != OWNER:
        return False
    sent = False
    for since, held in _tips(getattr(report, "view", ()) or ()):
        sent = await nudger.slouched(uid, held_s=held, at=since + held) or sent
    return sent


__all__ = ["HOLD_S", "KIND", "OWNER", "TEXT", "USE", "PostureNudger", "on_report"]
