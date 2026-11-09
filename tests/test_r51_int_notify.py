# tests/test_r51_int_notify.py -- R5.1 integrated fixes: D13 (health_fault / vitals_critical are
# "important" daytime rings, held at night, still capped by the storm) and the idle-alert switch.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import DAYTIME_RING_KINDS, decide
from jarvis.notify.ports import DEFAULT_URGENCY, Decision, Signal
from jarvis.notify.storm import MAX_SOFT_URGENT_PER_HOUR, SOFT_URGENT_KINDS, Storm

NOON_IST = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)
TWO_AM_IST = datetime(2026, 11, 9, 20, 30, tzinfo=UTC)
D13 = ("health_fault", "vitals_critical")


@pytest.mark.parametrize("kind", D13)
def test_d13_kind_is_important_and_a_daytime_ring(kind: str) -> None:
    assert DEFAULT_URGENCY[kind] == "important"
    assert kind in DAYTIME_RING_KINDS


@pytest.mark.parametrize("kind", D13)
def test_d13_rings_in_waking_hours_even_when_only_urgent_things_ring(kind: str) -> None:
    d = decide(Signal(source="system", kind=kind, subject="x"), NotifySettings(), NOON_IST)
    assert d.action == "ring"


@pytest.mark.parametrize("kind", D13)
def test_d13_is_held_never_rung_at_night(kind: str) -> None:
    d = decide(Signal(source="system", kind=kind, subject="x"), NotifySettings(), TWO_AM_IST)
    assert d.action == "hold"


@pytest.mark.parametrize(
    "kind", ["home_hazard", "home_intruder", "home_offline", "home_arm_failed"]
)
def test_hazards_burglar_and_armed_offline_stay_urgent(kind: str) -> None:
    assert DEFAULT_URGENCY[kind] == "urgent"
    d = decide(Signal(source="home", kind=kind), NotifySettings(), TWO_AM_IST)
    assert d.action == "ring"


def test_the_soft_caps_still_bound_the_d13_kinds_when_important() -> None:
    assert SOFT_URGENT_KINDS == frozenset(D13)
    storm = Storm()
    ring = Decision(action="ring", reason="important", urgency="important")
    got = [
        storm.admit(
            "u",
            Signal(source="system", kind="health_fault", subject=f"k{i}"),
            ring,
            NOON_IST + timedelta(minutes=i),
        ).admit
        for i in range(MAX_SOFT_URGENT_PER_HOUR + 3)
    ]
    assert got.count(True) == MAX_SOFT_URGENT_PER_HOUR
    same = storm.admit(
        "u", Signal(source="system", kind="vitals_critical", subject="a"), ring, NOON_IST
    )
    again = storm.admit(
        "u",
        Signal(source="system", kind="vitals_critical", subject="a"),
        ring,
        NOON_IST + timedelta(minutes=5),
    )
    assert not again.admit or not same.admit  # the per-subject gap or the hourly cap


def test_the_idle_alert_follows_the_armed_alert_switch_when_never_set() -> None:
    s = NotifySettings(kinds={"home_offline": "off"})
    assert s.switch("home_offline_idle") == "off"
    d = decide(Signal(source="home", kind="home_offline_idle"), s, NOON_IST)
    assert d.action == "drop"


def test_the_idle_alert_own_setting_wins() -> None:
    s = NotifySettings(kinds={"home_offline": "off", "home_offline_idle": "on"})
    assert s.switch("home_offline_idle") == "on"
    s2 = NotifySettings(kinds={"home_offline": "on", "home_offline_idle": "feed"})
    assert s2.switch("home_offline_idle") == "feed"


# ---- the idle alert is bounded: the 10 minute flap gap and an hourly cap (int-sec LOW 5) --------
def _idle() -> Signal:
    return Signal(source="home", kind="home_offline_idle")


def test_the_idle_alert_obeys_the_flap_gap() -> None:
    storm = Storm()
    ring = Decision(action="ring", reason="important", urgency="important")
    assert storm.admit("u", _idle(), ring, NOON_IST).admit
    again = storm.admit("u", _idle(), ring, NOON_IST + timedelta(minutes=5))
    assert not again.admit and again.reason == "flap_gap"


def test_the_idle_alert_is_capped_per_hour_and_the_cap_slides() -> None:
    from jarvis.notify.storm import FLAP_GAP, MAX_IDLE_PER_HOUR

    storm = Storm()
    ring = Decision(action="ring", reason="important", urgency="important")
    step = FLAP_GAP + timedelta(seconds=1)  # clears the gap each time, so only the cap bites
    got = [storm.admit("u", _idle(), ring, NOON_IST + step * i).admit for i in range(5)]
    assert got.count(True) == MAX_IDLE_PER_HOUR == 3
    later = storm.admit("u", _idle(), ring, NOON_IST + timedelta(hours=1, minutes=5))
    assert later.admit  # the first ring left the hour


def test_a_rolled_back_idle_alert_gives_both_the_gap_and_the_cap_slot_back() -> None:
    storm = Storm()
    ring = Decision(action="ring", reason="important", urgency="important")
    assert storm.admit("u", _idle(), ring, NOON_IST).admit
    storm.rollback("u", _idle(), NOON_IST)
    assert storm.admit("u", _idle(), ring, NOON_IST + timedelta(seconds=30)).admit
