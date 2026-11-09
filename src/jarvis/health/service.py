# src/jarvis/health/service.py
"""The self-health check (R4 D5/D6; R5.1 D5/D7). Deterministic: probes -> rollup -> stored ->
fixed-template line and briefing -> alert on change. No model is called anywhere, so it works
with the brain off.

Alerts (through the notify port, `Signal(source="system")`) follow `jarvis.health.changes`: a
status must hold for two checks; only `down` rings; `degraded` is a silent note; a recovery is
announced once; the home bridge is left to the home watchdog (R5.1 D4). What the owner was last
TOLD is stored with the report, so an alert that failed to send is retried on the next check. A
check inside `CHECK_COOLDOWN_S` of the last one returns the stored report unless forced (the tick
and the pop-up force). A store that is down never fails the check: state is then kept in memory
and the report is marked `persisted=False`.

`check_stream` (R5.1 D7) is the same check, under the same per-owner lock, as events: `plan`
(every probe, in the fixed order they were given), one `result` per probe as it completes
(`status: "skipped"` for one that is not set up for this owner), then `done` (the report as
`view` gives it, plus the briefing). The check runs in a task of its own, so a client that goes
away mid-stream still gets the result stored and the alerts sent. `briefing` adds Vitals (an
optional dependency): a board that can't be read in `VITALS_TIMEOUT_S` never fails anything.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any, Protocol

from jarvis.health.briefing import EMPTY, Briefing, compose_briefing
from jarvis.health.changes import Outgoing, Plan, plan
from jarvis.health.models import LABELS, HealthReport, HealthState, ProbeResult, Status
from jarvis.health.probes import Probe, crashed_result, run_probe
from jarvis.health.report import compose_line, rollup, system_row, view
from jarvis.health.store import HealthStore
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.vitals.models import Board
from jarvis.voice.service import SpeakRequest

log = get_logger(__name__)

CHECK_COOLDOWN_S = 30.0
VITALS_TIMEOUT_S = 5.0
SKIPPED = "skipped"
NOT_SET_UP = "not set up"
STREAM_FAILED = "The check did not complete."
Event = dict[str, Any]
Emit = Callable[[Event], None]


class Speaker(Protocol):
    """What the service needs from the voice (a `VoiceService`)."""

    async def speak(self, uid: str, req: SpeakRequest) -> Any: ...


class VitalsReader(Protocol):
    """What the briefing needs from Vitals (`VitalsService.board`)."""

    async def board(self, uid: str) -> Board: ...


def _name(probe: Probe) -> str:
    return LABELS.get(probe.key, probe.label)


def plan_event(probes: Sequence[Probe]) -> Event:
    return {"type": "plan", "systems": [{"key": p.key, "name": _name(p)} for p in probes]}


def result_event(probe: Probe, result: ProbeResult | None, at: float) -> Event:
    if result is None:
        row = {"key": probe.key, "name": _name(probe), "status": SKIPPED, "reason": NOT_SET_UP}
        return {"type": "result", **row, "at": at}
    return {"type": "result", **system_row(result)}


def done_event(report: HealthReport, brief: Briefing) -> Event:
    return {"type": "done", **view(report), "briefing": brief.to_json()}


class HealthService:
    def __init__(
        self,
        probes: Sequence[Probe],
        store: HealthStore,
        *,
        notifier: Notifier | None = None,
        voice: Speaker | None = None,
        vitals: VitalsReader | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._probes = tuple(probes)
        self._store = store
        self._notifier = notifier
        self._voice = voice
        self._vitals = vitals
        self._vitals_timeout_s = VITALS_TIMEOUT_S
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}
        self._memory: dict[str, HealthState] = {}
        self._background: set[asyncio.Task[None]] = set()

    async def check(self, uid: str, *, force: bool = False) -> HealthReport:
        """Run every probe at once, store the result, alert on change. Never raises because of
        the store; a fresh-enough stored report is returned unless `force`."""
        return await self._checked(uid, force=force, emit=None)

    async def check_stream(self, uid: str, *, force: bool = False) -> AsyncIterator[Event]:
        """The same check as events (see the module docstring). Never raises: a failure ends the
        stream with `{"type": "error", "detail": STREAM_FAILED}` (fixed words)."""
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        # its own task: a client that goes away mid-stream never stops the save or the alerts
        task = asyncio.create_task(self._streamed(uid, force, queue))
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        while (event := await queue.get()) is not None:
            yield event

    async def _streamed(self, uid: str, force: bool, queue: asyncio.Queue[Event | None]) -> None:
        try:
            report = await self._checked(uid, force=force, emit=queue.put_nowait)
            queue.put_nowait(done_event(report, await self.briefing(uid, report)))
        except Exception as exc:  # noqa: BLE001 - the stream ends in fixed words
            log.error("health stream failed", extra={"error": type(exc).__name__})
            queue.put_nowait({"type": "error", "detail": STREAM_FAILED})
        finally:
            queue.put_nowait(None)  # the end of the stream

    async def _checked(self, uid: str, *, force: bool, emit: Emit | None) -> HealthReport:
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            prior = await self._load(uid)
            if not force and prior is not None and self._fresh(prior.report):
                if emit is not None:
                    self._replay(prior.report, emit)
                return prior.report
            report = await self._run_probes(uid, emit)
            alerted = prior.alerted if prior is not None else {}
            streaks = prior.streaks if prior is not None else {}
            changes = plan(report, alerted, streaks)
            told = await self._deliver(uid, changes, alerted)
            state = HealthState(report=report, alerted=told, streaks=changes.streaks)
            self._memory[uid] = state
            if await self._save(uid, state):
                return report
            return report.model_copy(update={"persisted": False})

    def _replay(self, report: HealthReport, emit: Emit) -> None:
        """A report reused inside the cooldown, told as the same events a run gives."""
        emit(plan_event(self._probes))
        stored = {r.key: r for r in report.results}
        for probe in self._probes:
            emit(result_event(probe, stored.get(probe.key), report.at))

    def _fresh(self, report: HealthReport) -> bool:
        return 0 <= self._clock() - report.at < CHECK_COOLDOWN_S

    async def last(self, uid: str) -> HealthReport | None:
        return await self._store.last(uid)

    async def briefing(self, uid: str, report: HealthReport | None) -> Briefing:
        """The spoken briefing of `report` with this owner's Vitals. A board that fails or hangs
        gives the briefing without vitals and one fixed sentence saying so."""
        if report is None:
            return EMPTY
        if self._vitals is None:
            return compose_briefing(report, None)
        try:
            async with asyncio.timeout(self._vitals_timeout_s):
                board = await self._vitals.board(uid)
        except Exception as exc:  # noqa: BLE001 - Vitals never fails the check
            log.warning("health briefing: vitals unreadable", extra={"error": type(exc).__name__})
            return compose_briefing(report, None, vitals_unreadable=True)
        return compose_briefing(report, board)

    async def speak(self, uid: str) -> Any | None:
        """Say the last result aloud through the voice service; None when there is nothing to
        say or no voice. Voice errors reach the caller."""
        report = await self._store.last(uid)
        if report is None or self._voice is None:
            return None
        return await self._voice.speak(uid, SpeakRequest(text=compose_line(report)))

    async def _run_probes(self, uid: str, emit: Emit | None = None) -> HealthReport:
        if emit is not None:
            emit(plan_event(self._probes))

        async def one(probe: Probe) -> ProbeResult | None:
            try:
                out = await run_probe(probe, uid, clock=self._clock)
            except Exception:  # noqa: BLE001 - a probe task that died outside its guard
                out = crashed_result(probe, clock=self._clock)
            if emit is not None:
                emit(result_event(probe, out, self._clock()))
            return out

        ran = await asyncio.gather(*(one(p) for p in self._probes))
        done = tuple(r for r in ran if r is not None)
        return HealthReport(overall=rollup(done), results=done, at=self._clock())

    async def _load(self, uid: str) -> HealthState | None:
        try:
            stored = await self._store.state(uid)
        except Exception as exc:  # noqa: BLE001 - a dead store never fails the check
            log.error("health store unreadable", extra={"error": type(exc).__name__})
            return self._memory.get(uid)
        return stored if stored is not None else self._memory.get(uid)

    async def _save(self, uid: str, state: HealthState) -> bool:
        try:
            await self._store.save(uid, state)
        except Exception as exc:  # noqa: BLE001 - the caller still gets the in-memory report
            log.error("health store not written", extra={"error": type(exc).__name__})
            return False
        return True

    async def _deliver(
        self, uid: str, changes: Plan, before: Mapping[str, Status]
    ) -> dict[str, Status]:
        """The `alerted` map after sending: what was sent is now told; what failed stays as it
        was, so the next check tries again."""
        if not changes.confirmed:
            return dict(before)  # nothing set up right now: leave what the owner was told alone
        told: dict[str, Status] = dict(changes.confirmed)
        if self._notifier is None:
            return {k: before.get(k, "ok") for k in told}
        for msg in changes.messages:
            if not await self._send(uid, msg):
                for key in msg.keys:
                    told[key] = before.get(key, "ok")
        return told

    async def _send(self, uid: str, msg: Outgoing) -> bool:
        notifier = self._notifier
        if notifier is None:
            return False
        try:
            signal = Signal(source="system", kind=msg.kind, subject=",".join(sorted(msg.keys)))
            await notifier.notify(uid, signal, msg.text)
        except Exception as exc:  # noqa: BLE001 - an alert that cannot go never fails the check
            log.error(
                "health alert not sent", extra={"kind": msg.kind, "error": type(exc).__name__}
            )
            return False
        return True


__all__ = [
    "CHECK_COOLDOWN_S",
    "STREAM_FAILED",
    "VITALS_TIMEOUT_S",
    "HealthService",
    "Speaker",
    "VitalsReader",
    "done_event",
    "plan_event",
    "result_event",
]
