# tests/test_r51_int_debounce.py -- R5.1 D14: a fault is confirmed only by two checks at least
# 4 minutes apart; a recovery needs its checks spread over at least 8 minutes. A pop-up run right
# after another counts as the same moment and cannot confirm a blip.
from __future__ import annotations

from health_fakes import UID, Clock, Flip, Notes

from jarvis.health.changes import COUNT_GAP_S, DEBOUNCE_GAP_S, RECOVERY_SPREAD_S, plan
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.storage.docs import MemoryDocs


def rep(status: str, at: float) -> HealthReport:
    row = ProbeResult(key="redis", label="Redis", status=status, reason="x", at=at)  # type: ignore[arg-type]
    return HealthReport(overall=status, results=(row,), at=at)  # type: ignore[arg-type]


def test_the_constants_are_the_decision() -> None:
    assert DEBOUNCE_GAP_S == 240 and RECOVERY_SPREAD_S == 480 and COUNT_GAP_S == 240


def test_two_down_checks_seconds_apart_do_not_confirm() -> None:
    first = plan(rep("down", 1000.0), {}, {})
    second = plan(rep("down", 1005.0), {}, first.streaks)
    assert first.messages == () and second.messages == ()
    assert second.streaks["redis"][1] == 1  # the second check did not count


def test_two_down_checks_four_minutes_apart_confirm() -> None:
    first = plan(rep("down", 1000.0), {}, {})
    second = plan(rep("down", 1000.0 + DEBOUNCE_GAP_S), {}, first.streaks)
    assert [m.kind for m in second.messages] == ["health_fault"]


def test_a_burst_then_one_late_check_confirms_only_with_the_late_one() -> None:
    s = plan(rep("down", 1000.0), {}, {}).streaks
    for t in (1001.0, 1002.0, 1003.0):  # pop-up spam
        out = plan(rep("down", t), {}, s)
        assert out.messages == ()
        s = out.streaks
    late = plan(rep("down", 1000.0 + DEBOUNCE_GAP_S + 1), {}, s)
    assert [m.kind for m in late.messages] == ["health_fault"]


def test_recovery_needs_three_counted_checks_spread_over_eight_minutes() -> None:
    told = {"redis": "down"}
    a = plan(rep("ok", 0.0), told, {})
    b = plan(rep("ok", 120.0), told, a.streaks)  # too soon: not counted
    c = plan(rep("ok", 240.0), told, b.streaks)  # second counted check
    assert (a.messages, b.messages, c.messages) == ((), (), ())
    d = plan(rep("ok", 480.0), told, c.streaks)  # third counted check, 8 minutes after the first
    assert [m.kind for m in d.messages] == ["health_recovered"]


def test_recovery_spread_is_checked_even_for_three_counted_checks() -> None:
    told = {"redis": "down"}
    s = {"redis": ("ok", 2, 1000.0, 1000.0 + COUNT_GAP_S)}  # type: ignore[dict-item]
    early = plan(rep("ok", 1000.0 + COUNT_GAP_S * 2 - 1), told, s)  # not counted: gap < 4 min
    assert early.messages == ()
    ok = plan(rep("ok", 1000.0 + RECOVERY_SPREAD_S), told, s)  # third check, spread 8 min
    assert [m.kind for m in ok.messages] == ["health_recovered"]


def test_a_legacy_two_field_streak_still_counts() -> None:
    legacy = {"redis": ("down", 1)}
    out = plan(rep("down", 5.0), {}, legacy)  # type: ignore[arg-type]
    assert [m.kind for m in out.messages] == ["health_fault"]


def test_a_changed_status_restarts_the_streak() -> None:
    s = plan(rep("down", 0.0), {}, {}).streaks
    s = plan(rep("ok", 300.0), {}, s).streaks
    out = plan(rep("down", 600.0), {}, s)
    assert out.messages == ()


async def test_service_two_forced_runs_a_few_seconds_apart_never_alert() -> None:
    flip, notes, clock = Flip(), Notes(), Clock()
    svc = HealthService(
        [flip.probe],
        HealthStore(MemoryDocs(), prefix="jarvis_"),
        notifier=notes,
        clock=clock,
    )
    flip.status = "down"
    for _ in range(4):
        await svc.check(UID, force=True)
        clock.now += 40.0  # past the 30 s cooldown, far inside 4 minutes
    assert notes.sent == []
    clock.now += DEBOUNCE_GAP_S
    await svc.check(UID, force=True)
    assert notes.kinds() == ["health_fault"]


async def test_the_streak_times_survive_the_store() -> None:
    store = HealthStore(MemoryDocs(), prefix="jarvis_")
    flip, clock = Flip(), Clock()
    svc = HealthService([flip.probe], store, clock=clock)
    flip.status = "down"
    await svc.check(UID, force=True)
    state = await store.state(UID)
    assert state is not None
    status, count, first, last = state.streaks["redis"]
    assert (status, count, first, last) == ("down", 1, clock.now, clock.now)
