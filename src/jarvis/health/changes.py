# src/jarvis/health/changes.py
"""What to tell the owner after a check (R4 D6, integrator decisions D-B2 / D-B3). Pure: no I/O.

- A status must HOLD for `DEBOUNCE_CHECKS` consecutive checks before it counts (a single timeout
  blip never alerts). Until then the owner's last-told status for that integration stands.
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
    return {
        r.key: r.status if streaks[r.key][1] >= DEBOUNCE_CHECKS else alerted.get(r.key, "ok")
        for r in results
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


__all__ = ["DEBOUNCE_CHECKS", "Outgoing", "Plan", "next_streaks", "plan"]
