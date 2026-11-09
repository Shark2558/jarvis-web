# tests/test_r4_i2_flap_budget.py -- R4 I2 F2: flapping health / vitals urgent alerts never consume
# the Telegram urgent budget reserved for burglar / hazard rings.
from __future__ import annotations

from datetime import timedelta

from health_fakes import UID as HUID
from health_fakes import Clock as HClock
from health_fakes import Flip, Notes
from notify_fakes import NOON, build
from telegram_fakes import UID

from jarvis.health.changes import RECOVERY_CHECKS, plan
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.health.service import CHECK_COOLDOWN_S, HealthService
from jarvis.health.store import HealthStore
from jarvis.notify.ports import Decision, Signal
from jarvis.notify.storm import (
    MAX_SOFT_URGENT_PER_HOUR,
    SOFT_URGENT_GAP,
    Storm,
)
from jarvis.storage.docs import MemoryDocs

RING = Decision(action="ring", reason="urgent", urgency="urgent")


def fault(subject: str = "home") -> Signal:
    return Signal(source="system", kind="health_fault", subject=subject)


def vitals(subject: str = "claude") -> Signal:
    return Signal(source="system", kind="vitals_critical", subject=subject)


# ---- storm ------------------------------------------------------------------------------------


def test_the_same_fault_rings_at_most_once_per_gap() -> None:
    storm = Storm()

    first = storm.admit("u", fault(), RING, NOON)
    again = storm.admit("u", fault(), RING, NOON + timedelta(minutes=10))
    later = storm.admit("u", fault(), RING, NOON + SOFT_URGENT_GAP + timedelta(seconds=1))

    assert (first.admit, again.admit, later.admit) == (True, False, True)
    assert again.reason == "flap_gap"


def test_a_different_subject_has_its_own_gap() -> None:
    storm = Storm()

    assert storm.admit("u", fault("home"), RING, NOON).admit
    assert storm.admit("u", fault("redis"), RING, NOON).admit
    assert storm.admit("u", vitals("claude"), RING, NOON).admit


def test_health_and_vitals_rings_are_capped_per_hour_and_the_burglar_ring_still_goes() -> None:
    storm = Storm()
    results = [
        storm.admit("u", fault(f"k{i}"), RING, NOON + timedelta(minutes=i)).admit
        for i in range(MAX_SOFT_URGENT_PER_HOUR + 3)
    ]
    burglar = storm.admit(
        "u",
        Signal(source="home", kind="home_intruder", camera="gate"),
        Decision(action="ring", reason="intruder", urgency="urgent"),
        NOON + timedelta(minutes=20),
    )
    hazard = storm.admit(
        "u",
        Signal(source="home", kind="home_hazard", camera="kitchen"),
        Decision(action="ring", reason="emergency", urgency="urgent"),
        NOON + timedelta(minutes=21),
    )

    assert results.count(True) == MAX_SOFT_URGENT_PER_HOUR
    assert burglar.admit and hazard.admit


def test_a_failed_send_gives_the_slot_back() -> None:
    storm = Storm()
    storm.admit("u", fault(), RING, NOON)

    storm.rollback("u", fault(), NOON)

    assert storm.admit("u", fault(), RING, NOON + timedelta(seconds=5)).admit


# ---- telegram: its own bucket -----------------------------------------------------------------


async def test_health_and_vitals_alerts_do_not_draw_from_the_urgent_budget() -> None:
    w = await build(with_push=False)
    for _ in range(40):
        await w.alerts.send(UID, "Fault.", kind="health_fault")
        await w.alerts.send(UID, "Red.", kind="vitals_critical")

    burglar = await w.alerts.send(UID, "Burglar.", kind="home_intruder")

    assert burglar.sent


# ---- changes: recovery needs a clear streak ---------------------------------------------------


def report(status: str, at: float = 1.0) -> HealthReport:
    row = ProbeResult(key="redis", label="Redis", status=status, reason="x", at=at)  # type: ignore[arg-type]
    return HealthReport(overall=status, results=(row,), at=at)  # type: ignore[arg-type]


def test_recovery_needs_three_clear_checks() -> None:
    told = {"redis": "down"}
    streaks: dict = {"redis": ("ok", RECOVERY_CHECKS - 2)}

    # R5.1 D14: the checks are 5 minutes apart (a legacy 2-field streak has no times)
    early = plan(report("ok", 301.0), told, streaks)  # streak is now RECOVERY_CHECKS - 1
    done = plan(report("ok", 602.0), told, early.streaks)

    assert RECOVERY_CHECKS == 3
    assert early.messages == ()
    assert [m.kind for m in done.messages] == ["health_recovered"]


async def test_a_probe_flapping_two_bad_two_good_for_an_hour_rings_at_most_twice() -> None:
    clock = HClock()
    flip = Flip()
    notes = Notes()
    svc = HealthService(
        [flip.probe], HealthStore(MemoryDocs(), prefix="jarvis_"), notifier=notes, clock=clock
    )

    for status in ("down", "down", "ok", "ok") * 15:  # an hour, a check every minute
        flip.status = status
        clock.now += max(60.0, CHECK_COOLDOWN_S + 1)
        await svc.check(HUID, force=True)

    rings = [k for k in notes.kinds() if k == "health_fault"]
    assert len(rings) <= 2
    assert len(notes.kinds()) <= 3
