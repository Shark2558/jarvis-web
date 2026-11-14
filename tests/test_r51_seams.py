# tests/test_r51_seams.py -- R5.1 I0 seams (docs/plans/r5-1-observations.md D3): the laptop that
# stops answering while DISARMED gets its own alert kind, rings in waking hours even when only
# urgent things ring, and is held (never rung) in quiet hours; the offline threshold is 3 beats.
from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args

import pytest

from jarvis.alerts import HOME_ALERT_KINDS, AlertKind
from jarvis.config import Settings
from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import DAYTIME_RING_KINDS, decide
from jarvis.notify.ports import DEFAULT_URGENCY, Signal

NOON_IST = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)  # 12:00 in Asia/Kolkata
TWO_AM_IST = datetime(2026, 11, 9, 20, 30, tzinfo=UTC)  # 02:00 in Asia/Kolkata
R11_DAYTIME = (
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
)


def _signal(kind: str) -> Signal:
    return Signal(source="home", kind=kind)  # type: ignore[arg-type]


def test_home_offline_idle_is_a_known_important_home_kind() -> None:
    assert "home_offline_idle" in get_args(AlertKind)
    assert "home_offline_idle" in HOME_ALERT_KINDS
    assert DEFAULT_URGENCY["home_offline_idle"] == "important"
    # R5.1 D13 added health_fault and vitals_critical (tests/test_r51_int_notify.py); R6 the
    # build book's three notices (tests/test_r6_seams.py)
    # R11 D5: the helpers' reminders, weather / breach notices and nudges (tests/test_r11_seams.py)
    assert DAYTIME_RING_KINDS == frozenset(
        {"home_offline_idle", "health_fault", "vitals_critical"}
        | {"book_sealed", "book_seal_failed", "book_session_closed"}
        | set(R11_DAYTIME)
        | {"series_checkin"}  # R11.1 D6 (tests/test_r11_1_seams.py)
        | {"sos_contact_left"}  # R7 D20 (tests/test_r7_seams.py)
        # R14 D6: self-health and backups (tests/test_r14_seams.py)
        | {"job_failing", "clock_stopped", "brief_missed", "errors_piling", "spend_spike"}
        | {"deploy_changed", "backup_problem"}
    )


def test_idle_offline_rings_in_the_day_even_when_only_urgent_things_ring() -> None:
    settings = NotifySettings(ring_for="urgent")
    d = decide(_signal("home_offline_idle"), settings, NOON_IST)
    assert d.action == "ring"


def test_idle_offline_is_held_in_quiet_hours() -> None:
    settings = NotifySettings(ring_for="urgent")
    d = decide(_signal("home_offline_idle"), settings, TWO_AM_IST)
    assert d.action == "hold"


@pytest.mark.parametrize("kind", ["home_package", "approval_waiting", "vault_expiry"])
def test_other_important_kinds_stay_silent_when_only_urgent_things_ring(kind: str) -> None:
    d = decide(_signal(kind), NotifySettings(ring_for="urgent"), NOON_IST)
    assert d.action == "silent"


def test_offline_threshold_is_three_beats_and_the_alert_is_on_by_default() -> None:
    s = Settings(_env_file=None)
    assert s.home_offline_after_s == 360
    assert s.home_offline_alert == "always"
    armed_only = Settings(_env_file=None, home_offline_alert="armed_only")
    assert armed_only.home_offline_alert == "armed_only"
