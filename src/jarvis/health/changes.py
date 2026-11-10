# src/jarvis/health/changes.py
"""What to tell the owner after a check (R4 D6, integrator decisions D-B2 / D-B3). Pure: no I/O.

- A status must hold for `DEBOUNCE_CHECKS` checks in a row before the owner is told (a one-check
  blip never alerts); a recovery needs `RECOVERY_CHECKS` clear checks in a row. Until then the
  owner's last-told status for that integration stands.
- R5.1 D14: streaks are TIME-based. A check counts toward a streak only if it is at least
  `COUNT_GAP_S` (4 minutes) after the previous counted check, so a pop-up run right after another
  (or `/run` plus `/run/stream`) cannot confirm a blip; a fault is confirmed by two counted checks
  (>= `DEBOUNCE_GAP_S` apart) and a recovery by three whose first and last are >=
  `RECOVERY_SPREAD_S` (8 minutes) apart. A streak is (status, count, first_at, last_counted_at);
  the times are None in a streak stored before R5.1 (counted as long ago).
- R5.1 D4: integrations in `WATCHED_ELSEWHERE` (the home bridge: the 5-minute watchdog's
  `home_offline` / `home_offline_idle` alert owns it) never produce a message here and never hold
  back "all clear"; they still appear in the report and the briefing.
- Only `down` rings (`health_fault`). `degraded` goes out as a silent info note
  (`health_degraded`). Getting worse (degraded -> down) rings; getting better (down -> degraded)
  is a note. All faults gone -> `health_recovered`.
- A recovery names only integrations that are PRESENT and ok now; an integration that stopped
  being set up never counts as recovered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from jarvis.alerts import AlertKind
from jarvis.health.models import HealthReport, ProbeResult, Status
from jarvis.health.report import NOMINAL, compose_line

DEBOUNCE_CHECKS = 2
RECOVERY_CHECKS = 3  # a flapping probe gives one fault, not a fault / recovered loop
DEBOUNCE_GAP_S = 240.0  # R5.1 D14: the two checks that confirm a fault are this far apart
COUNT_GAP_S = DEBOUNCE_GAP_S  # a check closer than this to the last counted one is not counted
RECOVERY_SPREAD_S = 480.0  # R5.1 D14: a recovery's checks span at least this long
WATCHED_ELSEWHERE = frozenset({"home"})  # R5.1 D4: the home watchdog alerts for it (no double ring)
# (status, count, first_at, last_counted_at); a 2-tuple (pre-R5.1 storage) is read as no times
Streak = tuple[Status, int, float | None, float | None]
Streaks = Mapping[str, Streak]


@dataclass(frozen=True)
class Outgoing:
    kind: AlertKind
    text: str
    keys: frozenset[str]  # the integrations this message is about (kept un-told if it fails)


@dataclass(frozen=True)
class Plan:
    streaks: Streaks
    confirmed: Mapping[str, Status]  # per present integration, the status that has held
    messages: tuple[Outgoing, ...]


def _streak(raw: tuple[object, ...]) -> Streak:
    status, count = cast(Status, raw[0]), int(cast(int, raw[1]))
    first = cast("float | None", raw[2]) if len(raw) > 2 else None
    last = cast("float | None", raw[3]) if len(raw) > 3 else None
    return (status, count, first, last)


def next_streaks(
    results: tuple[ProbeResult, ...], prior: Streaks, now: float | None = None
) -> dict[str, Streak]:
    """The streaks after a check at `now` (default: the newest probe time)."""
    at = now if now is not None else max((r.at for r in results), default=0.0)
    out: dict[str, Streak] = {}
    for r in results:
        before = _streak(prior[r.key]) if r.key in prior else None
        if before is None or before[0] != r.status:
            out[r.key] = (r.status, 1, at, at)
            continue
        _, count, first, last = before
        if last is None or at - last >= COUNT_GAP_S:
            out[r.key] = (r.status, count + 1, first, at)  # first stays None for a pre-R5.1 streak
        else:
            out[r.key] = before  # too soon after the last counted check: the same moment
    return out


def _held(r: ProbeResult, streak: Streak, recovering: bool) -> bool:
    _, count, first, last = streak
    if count < (RECOVERY_CHECKS if recovering else DEBOUNCE_CHECKS):
        return False
    if first is None or last is None:
        return True  # stored before R5.1: no times to judge by
    return last - first >= (RECOVERY_SPREAD_S if recovering else DEBOUNCE_GAP_S)


def _confirmed(
    results: tuple[ProbeResult, ...], streaks: Streaks, alerted: Mapping[str, Status]
) -> dict[str, Status]:
    def status(r: ProbeResult) -> Status:
        recovering = r.status == "ok" and alerted.get(r.key, "ok") != "ok"
        return r.status if _held(r, streaks[r.key], recovering) else alerted.get(r.key, "ok")

    return {r.key: status(r) for r in results if r.key not in WATCHED_ELSEWHERE}


def plan(report: HealthReport, alerted: Mapping[str, Status], prior: Streaks) -> Plan:
    streaks = next_streaks(report.results, prior, report.at)
    if not report.results:
        return Plan(streaks={}, confirmed={}, messages=())
    confirmed = _confirmed(report.results, streaks, alerted)
    told = {k: alerted.get(k, "ok") for k in confirmed}
    went_down = frozenset(k for k, s in confirmed.items() if s == "down" and told[k] != "down")
    went_slow = frozenset(
        k for k, s in confirmed.items() if s == "degraded" and told[k] != "degraded"
    )
    healed = frozenset(k for k, s in confirmed.items() if s == "ok" and told[k] != "ok")
    messages: list[Outgoing] = []
    if went_down:
        messages.append(Outgoing("health_fault", compose_line(report, only=went_down), went_down))
    if went_slow:
        messages.append(
            Outgoing("health_degraded", compose_line(report, only=went_slow), went_slow)
        )
    if healed and all(s == "ok" for s in confirmed.values()):
        messages.append(Outgoing("health_recovered", NOMINAL, healed))
    return Plan(streaks=streaks, confirmed=confirmed, messages=tuple(messages))


__all__ = [
    "COUNT_GAP_S",
    "DEBOUNCE_CHECKS",
    "DEBOUNCE_GAP_S",
    "RECOVERY_SPREAD_S",
    "RECOVERY_CHECKS",
    "WATCHED_ELSEWHERE",
    "Outgoing",
    "Plan",
    "next_streaks",
    "plan",
]
