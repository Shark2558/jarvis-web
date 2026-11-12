# src/jarvis/series/words.py
"""Small pure helpers of the plans (R11.1 O2b): the key a check-in question is claimed under."""

from __future__ import annotations

import hashlib

from jarvis.series.models import Plan, PlanSession


def told_key(plan: Plan, s: PlanSession) -> str:
    """One question per session AND time: a session moved to a new time is asked about again
    after it, never twice for the same time."""
    raw = f"{plan.id}|{s.event_id}|{int(s.start.timestamp())}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


__all__ = ["told_key"]
