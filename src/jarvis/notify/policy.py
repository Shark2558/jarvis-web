# src/jarvis/notify/policy.py
"""The one alert policy (R3 D10): pure, deterministic, no model call. First match wins.

1 test -> ring.  2 switched off -> drop; "feed" -> drop (feed_only).  3 emergency (a hazard, or
words in `text`) -> ring.  4 an urgent kind -> ring.  5 VIP -> ring.  6 quiet hours: important ->
hold, info -> drop (feed_only).  7 otherwise important -> ring (silent when only urgent things
ring), info -> silent. Recognition only raises a level; it never lowers one.
R5.1 D3: a kind in DAYTIME_RING_KINDS rings outside quiet hours even when only urgent things ring.
"""

from __future__ import annotations

from datetime import datetime

from jarvis.notify.models import NotifySettings
from jarvis.notify.ports import DEFAULT_URGENCY, Decision, Signal, Urgency
from jarvis.notify.quiet import in_quiet
from jarvis.notify.terms import emergency

# R5.1 D3: important kinds that ring in waking hours even with "only urgent things ring" (still
# held, never rung, in quiet hours).
DAYTIME_RING_KINDS = frozenset({"home_offline_idle"})


def urgency_of(kind: str) -> Urgency:
    return DEFAULT_URGENCY.get(kind, "important")


def _is_vip(signal: Signal, settings: NotifySettings) -> bool:
    if signal.child:
        return False
    if signal.vip:
        return True
    return signal.person_ref is not None and any(v.ref == signal.person_ref for v in settings.vip)


def decide(signal: Signal, settings: NotifySettings, now: datetime) -> Decision:
    level = urgency_of(signal.kind)
    if signal.kind == "test":
        return Decision(action="ring", reason="test", urgency=level)
    switch = settings.switch(signal.kind)
    if switch == "off":
        return Decision(action="drop", reason="switched_off", urgency=level)
    if switch == "feed":
        return Decision(action="drop", reason="feed_only", urgency=level)
    if signal.kind == "home_hazard" or emergency(signal.text):
        return Decision(action="ring", reason="emergency", urgency="urgent")
    if level == "urgent":
        reason = "intruder" if signal.kind == "home_intruder" else "urgent"
        return Decision(action="ring", reason=reason, urgency=level)
    if _is_vip(signal, settings):
        return Decision(action="ring", reason="vip", urgency="urgent")
    if in_quiet(now, settings.quiet, settings.tz):
        if level == "important":
            return Decision(action="hold", reason="quiet_hours", urgency=level)
        return Decision(action="drop", reason="feed_only", urgency=level)
    if level == "important":
        if settings.ring_for == "urgent" and signal.kind not in DAYTIME_RING_KINDS:
            return Decision(action="silent", reason="only_urgent_rings", urgency=level)
        return Decision(action="ring", reason="important", urgency=level)
    return Decision(action="silent", reason="info", urgency=level)


class Policy:
    """`NotifyPolicy` for the service: `decide(signal, settings, now)`."""

    def decide(self, signal: Signal, settings: NotifySettings, now: datetime) -> Decision:
        return decide(signal, settings, now)


__all__ = ["DAYTIME_RING_KINDS", "Policy", "decide", "urgency_of"]
