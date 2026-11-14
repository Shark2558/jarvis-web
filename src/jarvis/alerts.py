# src/jarvis/alerts.py
"""The alerts port (R1 D6; Layer 8 notifications). Other features call it; Telegram implements it.

`AlertSink.send(uid, text, kind=...)` never raises for "can't send": it returns an `AlertResult`
with `sent=False` and a short reason. `text` is always written by JARVIS code from a fixed
template, never model text and never other people's words. `NoAlerts` is used when Telegram is off
or unpaired.

R3 (docs/plans/r3-home-camera.md D10, D12): the home kinds, and two keywords every sink accepts:
`silent` (deliver without a sound) and `photo` (one small JPEG for a burglar alert the owner opted
in to; held in memory, never stored, logged or audited). A sink that can't do either ignores it.
R11 (docs/plans/r11-free-helpers.md D5): thirteen helper kinds; `R11_ALERT_KINDS` lists them.
R11.1 (docs/plans/r11-1-observations.md): two more; `R11_1_ALERT_KINDS` lists them.
R7 (docs/plans/r7-mobile.md D25): five more; `R7_ALERT_KINDS` lists them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

AlertKind = Literal[
    "approval_waiting",
    "offline_on",
    "offline_off",
    "brief_ready",
    "vault_expiry",
    "test",
    # R3 D10: home alerts (the level of each is notify.ports.DEFAULT_URGENCY)
    "home_intruder",
    "home_hazard",
    "home_package",
    "home_greeting",
    "home_offline",
    "home_online",
    "home_arm_failed",
    "home_summary",
    # R5.1 (docs/plans/r5-1-observations.md D3): the laptop stopped answering while DISARMED
    "home_offline_idle",
    # R4 (docs/plans/r4-vitals-health-people.md D4, D6): vitals + self-health. Levels in
    # notify.ports.DEFAULT_URGENCY: vitals_critical/health_fault important (D13), the rest info.
    "vitals_warn",
    "vitals_critical",
    "health_fault",
    "health_recovered",
    "health_degraded",
    # R6 (docs/plans/r6-build-book.md D7, D14): the build book. All "important" daytime rings
    # (notify.policy DAYTIME_RING_KINDS): held in quiet hours, rung in waking hours.
    "book_sealed",
    "book_seal_failed",
    "book_session_closed",
    # R11 (docs/plans/r11-free-helpers.md D5): the free proactive helpers, every one sent through
    # `helpers.gate.HelperSender`. Levels in notify.ports.DEFAULT_URGENCY: disaster_alert urgent
    # (rings at night); the reminders, weather_warning and breach_notice "important" daytime rings
    # (held at night); the five nudges "important" daytime rings that are EPHEMERAL (dropped at
    # night, never held); weather_note info.
    "disaster_alert",
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
    "weather_note",
    # R11.1 (docs/plans/r11-1-observations.md D6, D14): "did this study session happen?" is asked
    # every time, so it is an "important" daytime ring that is HELD at night (never dropped like a
    # nudge); "new faces to name" from the home laptop's photo folder is info (feed only).
    "series_checkin",
    "faces_to_name",
    # R7 (docs/plans/r7-mobile.md D5, D19, D20, D25): an SOS was sent and a phone was linked are
    # "urgent" (they ring at night) with no off switch (notify.models.NO_SWITCH), and no Telegram
    # cap may drop an SOS notice (notify.telegram_out.NO_CAP_KINDS); an emergency contact left is
    # an "important" daytime ring; a phone unlinked and "the watch has not synced" are info.
    "sos_sent",
    "phone_linked",
    "sos_contact_left",
    "phone_unlinked",
    "watch_stale",
    # R14 (docs/plans/r14-hardening.md D5, D6): JARVIS's own health and its backups. Seven are
    # "important" daytime rings held in quiet hours, under their own soft cap (notify.storm
    # SELF_KINDS: one per kind and subject per 30 minutes, 3 an hour in all); recovered and a
    # passed drill are info (feed only). Part A alone raises the two backup kinds.
    "job_failing",
    "clock_stopped",
    "brief_missed",
    "errors_piling",
    "spend_spike",
    "deploy_changed",
    "backup_problem",
    "selfwatch_ok",
    "backup_ok",
]
HOME_ALERT_KINDS: tuple[AlertKind, ...] = (
    "home_intruder",
    "home_hazard",
    "home_package",
    "home_greeting",
    "home_offline",
    "home_online",
    "home_arm_failed",
    "home_summary",
    "home_offline_idle",
)


@dataclass(frozen=True)
class AlertResult:
    """`queued`: not sent yet but kept to go out later (an alert held for quiet hours goes out in
    the morning summary), so a caller must not send it again."""

    sent: bool
    reason: str = ""
    queued: bool = False


@runtime_checkable
class AlertSink(Protocol):
    async def send(
        self,
        uid: str,
        text: str,
        *,
        kind: AlertKind,
        silent: bool = False,
        photo: bytes | None = None,
    ) -> AlertResult: ...


class NoAlerts:
    """The sink when nothing can deliver alerts: sends nothing and says why."""

    def __init__(self, reason: str = "not set up") -> None:
        self.reason = reason

    async def send(
        self,
        uid: str,
        text: str,
        *,
        kind: AlertKind,
        silent: bool = False,
        photo: bytes | None = None,
    ) -> AlertResult:
        return AlertResult(sent=False, reason=self.reason)


R11_ALERT_KINDS: tuple[AlertKind, ...] = (
    "disaster_alert",
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
    "weather_note",
)
R11_1_ALERT_KINDS: tuple[AlertKind, ...] = ("series_checkin", "faces_to_name")
R7_ALERT_KINDS: tuple[AlertKind, ...] = (
    "sos_sent",
    "phone_linked",
    "sos_contact_left",
    "phone_unlinked",
    "watch_stale",
)
R14_ALERT_KINDS: tuple[AlertKind, ...] = (
    "job_failing",
    "clock_stopped",
    "brief_missed",
    "errors_piling",
    "spend_spike",
    "deploy_changed",
    "backup_problem",
    "selfwatch_ok",
    "backup_ok",
)


__all__ = [
    "HOME_ALERT_KINDS",
    "R11_1_ALERT_KINDS",
    "R11_ALERT_KINDS",
    "R14_ALERT_KINDS",
    "R7_ALERT_KINDS",
    "AlertKind",
    "AlertResult",
    "AlertSink",
    "NoAlerts",
]
