# src/jarvis/health/report.py
"""Rollup and the spoken line (R4 D6). The line comes from FIXED templates and the fixed labels
of the probes; never model text and never a probe's reason (which can carry vendor words)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from jarvis.health.models import LABELS, HealthReport, ProbeResult, Status

NOMINAL = "All systems nominal, Sir."
NOTHING_WATCHED = "There are no systems to check, Sir."
_ORDER: dict[Status, int] = {"ok": 0, "degraded": 1, "down": 2}


def rollup(results: Iterable[ProbeResult]) -> Status:
    worst: Status = "ok"
    for r in results:
        if _ORDER[r.status] > _ORDER[worst]:
            worst = r.status
    return worst


def spoken_label(r: ProbeResult) -> str:
    """The code-side label for a known integration; the stored one only for an unknown key."""
    return LABELS.get(r.key, r.label)


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _sentence(names: Sequence[str], singular: str, plural: str) -> str:
    return f"{_join(names)} {singular if len(names) == 1 else plural}."


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def compose_line(report: HealthReport, *, only: frozenset[str] | None = None) -> str:
    """The sentence JARVIS says. `only` limits the faults named (a new fault alert)."""
    if not report.results:
        return NOTHING_WATCHED
    if report.overall == "ok":
        return NOMINAL
    chosen = [r for r in report.results if only is None or r.key in only]
    down = [spoken_label(r) for r in chosen if r.status == "down"]
    slow = [spoken_label(r) for r in chosen if r.status == "degraded"]
    parts: list[str] = []
    if down:
        parts.append(_sentence(down, "is not answering", "are not answering"))
    if slow:
        parts.append(_sentence(slow, "is degraded", "are degraded"))
    if not parts:
        return NOMINAL
    parts[0] = f"Attention: {parts[0]}" if len(parts) == 1 or down else parts[0]
    if len(parts) > 1:
        parts[1] = _cap(parts[1])
    return " ".join(parts)


__all__ = ["NOMINAL", "NOTHING_WATCHED", "compose_line", "rollup", "spoken_label"]
