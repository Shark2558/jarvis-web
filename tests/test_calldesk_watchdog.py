"""R18 C: the watchdog restores the owner's audio whenever the desk ends, restarts it with a
growing pause, and stops on a stop request or a final exit code (plan section 8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.calldesk import watchdog as wd


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


@dataclass
class Child:
    code: int
    runs_for: float
    clock: Clock

    def wait(self) -> int:
        self.clock.now += self.runs_for
        return self.code


@dataclass
class Rig:
    codes: list[tuple[int, float]]
    clock: Clock = field(default_factory=Clock)
    restores: int = 0
    starts: list[float] = field(default_factory=list)
    stop_at_start: int | None = None
    fail_restore: bool = False

    def start(self) -> Child:
        self.starts.append(self.clock.now)
        code, runs = self.codes.pop(0)
        return Child(code, runs, self.clock)

    def restore(self) -> None:
        self.restores += 1
        if self.fail_restore:
            raise RuntimeError("COM went away")

    def stop(self) -> bool:
        return self.stop_at_start is not None and len(self.starts) >= self.stop_at_start

    def supervisor(self) -> wd.Supervisor:
        return wd.Supervisor(self.start, self.restore, self.stop, self.clock.sleep, self.clock)


def test_restores_at_start_and_after_every_exit_then_stops_on_request() -> None:
    rig = Rig([(1, 10.0), (1, 10.0), (0, 5.0)])
    assert rig.supervisor().run() == wd.EXIT_OK
    assert len(rig.starts) == 3 and rig.restores == 1 + 3


def test_pause_grows_while_it_keeps_crashing_and_resets_after_a_quiet_run() -> None:
    rig = Rig([(1, 1.0)] * 7 + [(1, wd.STABLE_S + 1.0), (0, 1.0)])
    rig.supervisor().run()
    gaps = [b - a for a, b in zip(rig.starts, rig.starts[1:], strict=False)]
    pauses = [round(g - 1.0) for g in gaps[:7]]
    assert pauses == [2, 5, 15, 30, 60, 60, 60]
    assert round(gaps[7] - (wd.STABLE_S + 1.0)) == 2


def test_final_codes_end_it_without_a_restart() -> None:
    for code in (wd.EXIT_NOT_LINKED, wd.EXIT_ALREADY_RUNNING, wd.EXIT_CONFIG):
        rig = Rig([(code, 1.0)])
        assert rig.supervisor().run() == code
        assert len(rig.starts) == 1 and rig.restores == 2


def test_a_stop_request_during_the_pause_ends_it() -> None:
    rig = Rig([(1, 1.0), (1, 1.0)], stop_at_start=1)
    assert rig.supervisor().run() == wd.EXIT_OK
    assert len(rig.starts) == 1


def test_a_failing_restore_never_kills_the_watchdog() -> None:
    rig = Rig([(1, 1.0), (0, 1.0)], fail_restore=True)
    assert rig.supervisor().run() == wd.EXIT_OK and rig.restores == 3


def test_a_desk_that_cannot_start_is_retried() -> None:
    rig = Rig([(0, 1.0)])
    calls = {"n": 0}

    def start() -> Child:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("python not found")
        return rig.start()

    sup = wd.Supervisor(start, rig.restore, rig.stop, rig.clock.sleep, rig.clock)
    assert sup.run() == wd.EXIT_OK and calls["n"] == 2
