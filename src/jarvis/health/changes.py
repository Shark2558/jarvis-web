# src/jarvis/health/changes.py
"""What to tell the owner after a check (R4 D6, integrator decisions D-B2 / D-B3). Pure: no I/O.

- A status must hold for `DEBOUNCE_CHECKS` checks in a row before the owner is told (a one-check
  blip never alerts); a recovery needs `RECOVERY_CHECKS` clear checks in a row. Until then the
  owner's last-told status for that integration stands.
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

from jarvis.alerts import AlertKind
from jarvis.health.models import HealthReport, ProbeResult, Status
from jarvis.health.report import NOMINAL, compose_line

DEBOUNCE_CHECKS = 2
RECOVERY_CHECKS = 3  # a flapping probe gives one fault, not a fault / recovered loop
WATCHED_ELSEWHERE = frozenset({"home"})  # R5.1 D4: the home watchdog alerts for it (no double ring)
Streaks = Mapping[str, tuple[Status, int]]


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


def next_streaks(results: tuple[ProbeResult, ...], prior: Streaks) -> dict[str, tuple[Status, int]]:
    out: dict[str, tuple[Status, int]] = {}
    for r in results:
        before = prior.get(r.key)
        count = before[1] + 1 if before is not None and before[0] == r.status else 1
        out[r.key] = (r.status, count)
    return out


def _confirmed(
    results: tuple[ProbeResult, ...], streaks: Streaks, alerted: Mapping[str, Status]
) -> dict[str, Status]:
    def needed(r: ProbeResult) -> int:
        recovering = r.status == "ok" and alerted.get(r.key, "ok") != "ok"
        return RECOVERY_CHECKS if recovering else DEBOUNCE_CHECKS

    return {
        r.key: r.status if streaks[r.key][1] >= needed(r) else alerted.get(r.key, "ok")
        for r in results
        if r.key not in WATCHED_ELSEWHERE
    }


def plan(report: HealthReport, alerted: Mapping[str, Status], prior: Streaks) -> Plan:
    streaks = next_streaks(report.results, prior)
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
    "DEBOUNCE_CHECKS",
    "RECOVERY_CHECKS",
    "WATCHED_ELSEWHERE",
    "Outgoing",
    "Plan",
    "next_streaks",
    "plan",
]
