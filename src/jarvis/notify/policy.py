# src/jarvis/notify/policy.py
"""The one alert policy (R3 D10): pure, deterministic, no model call. First match wins.

1 test -> ring.  2 switched off -> drop; "feed" -> drop (feed_only).  3 emergency (a hazard, or
words in `text`) -> ring.  4 an urgent kind -> ring.  5 VIP -> ring.  6 quiet hours: important ->
hold, info -> drop (feed_only).  7 otherwise important -> ring (silent when only urgent things
ring), info -> silent. Recognition only raises a level; it never lowers one.
R5.1 D3: a kind in DAYTIME_RING_KINDS rings outside quiet hours even when only urgent things ring.
R11 D5: a kind in EPHEMERAL_KINDS (a nudge) is dropped in quiet hours, never held: a "drink water"
kept for the morning summary is noise. It is decided before the VIP rule, after the urgent one.
"""

from __future__ import annotations

from datetime import datetime

from jarvis.notify.models import NotifySettings
from jarvis.notify.ports import DEFAULT_URGENCY, Decision, Signal, Urgency
from jarvis.notify.quiet import in_quiet
from jarvis.notify.terms import emergency

# R5.1 D3: important kinds that ring in waking hours even with "only urgent things ring" (still
# held, never rung, in quiet hours).
# R5.1 D13: the systems check runs around the clock, so a health fault / red vitals line must not
# wake the owner at night: both are "important" and ring only in waking hours.
# R6 D7, D14: the build book's notices (sealed, not sealed, a session closed) ring the same way.
DAYTIME_RING_KINDS = frozenset(
    {
        "home_offline_idle",
        "health_fault",
        "vitals_critical",
        "book_sealed",
        "book_seal_failed",
        "book_session_closed",
        # R11 D5: the helpers' reminders and weather / breach notices, and the five nudges
        "bill_due",
        "birthday",
        "chore_due",
        "maintenance_due",
        "weather_warning",
        "breach_notice",
        "nudge_standup",
        "nudge_hydrate",
        "nudge_activity",
        "nudge_free_time",
        "nudge_focus",
        "series_checkin",  # R11.1 D6: asked every time; held at night, never dropped
        "sos_contact_left",  # R7 D20: an emergency contact sent /stop; held at night
        # R14 D6: JARVIS's own health and its backups; held at night, never dropped
        "job_failing",
        "clock_stopped",
        "brief_missed",
        "errors_piling",
        "spend_spike",
        "deploy_changed",
        "backup_problem",
    }
)
# R11 D5: nudges are only worth hearing when they are due; in quiet hours they are dropped (feed
# only), never held for the morning summary.
EPHEMERAL_KINDS = frozenset(
    {"nudge_standup", "nudge_hydrate", "nudge_activity", "nudge_free_time", "nudge_focus"}
)


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
    quiet = in_quiet(now, settings.quiet, settings.tz)
    if quiet and signal.kind in EPHEMERAL_KINDS:
        return Decision(action="drop", reason="stale_at_night", urgency=level)
    if _is_vip(signal, settings):
        return Decision(action="ring", reason="vip", urgency="urgent")
    if quiet:
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


__all__ = ["DAYTIME_RING_KINDS", "EPHEMERAL_KINDS", "Policy", "decide", "urgency_of"]
