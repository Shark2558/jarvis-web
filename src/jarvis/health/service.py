# src/jarvis/health/service.py
"""The self-health check (R4 D5/D6). Deterministic: probes -> rollup -> stored -> fixed-template
line -> alert on change. No model is called anywhere, so it works with the brain off.

Alerts (through the notify port, `Signal(source="system")`) follow `jarvis.health.changes`: a
status must hold for two checks; only `down` rings; `degraded` is a silent note; a recovery is
announced once. What the owner was last TOLD is stored with the report, so an alert that failed
to send is retried on the next check. A check inside `CHECK_COOLDOWN_S` of the last one returns
the stored report unless forced (the tick forces). A store that is down never fails the check:
state is then kept in memory and the report is marked `persisted=False`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from jarvis.health.changes import Outgoing, Plan, plan
from jarvis.health.models import HealthReport, HealthState, ProbeResult, Status
from jarvis.health.probes import Probe, crashed_result, run_probe
from jarvis.health.report import compose_line, rollup
from jarvis.health.store import HealthStore
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.voice.service import SpeakRequest

log = get_logger(__name__)

CHECK_COOLDOWN_S = 30.0


class Speaker(Protocol):
    """What the service needs from the voice (a `VoiceService`)."""

    async def speak(self, uid: str, req: SpeakRequest) -> Any: ...


class HealthService:
    def __init__(
        self,
        probes: Sequence[Probe],
        store: HealthStore,
        *,
        notifier: Notifier | None = None,
        voice: Speaker | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._probes = tuple(probes)
        self._store = store
        self._notifier = notifier
        self._voice = voice
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}
        self._memory: dict[str, HealthState] = {}

    async def check(self, uid: str, *, force: bool = False) -> HealthReport:
        """Run every probe at once, store the result, alert on change. Never raises because of
        the store; a fresh-enough stored report is returned unless `force`."""
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            prior = await self._load(uid)
            if not force and prior is not None and self._fresh(prior.report):
                return prior.report
            report = await self._run_probes(uid)
            alerted = prior.alerted if prior is not None else {}
            streaks = prior.streaks if prior is not None else {}
            changes = plan(report, alerted, streaks)
            told = await self._deliver(uid, changes, alerted)
            state = HealthState(report=report, alerted=told, streaks=changes.streaks)
            self._memory[uid] = state
            if await self._save(uid, state):
                return report
            return report.model_copy(update={"persisted": False})

    def _fresh(self, report: HealthReport) -> bool:
        return 0 <= self._clock() - report.at < CHECK_COOLDOWN_S

    async def last(self, uid: str) -> HealthReport | None:
        return await self._store.last(uid)

    async def speak(self, uid: str) -> Any | None:
        """Say the last result aloud through the voice service; None when there is nothing to
        say or no voice. Voice errors reach the caller."""
        report = await self._store.last(uid)
        if report is None or self._voice is None:
            return None
        return await self._voice.speak(uid, SpeakRequest(text=compose_line(report)))

    async def _run_probes(self, uid: str) -> HealthReport:
        ran = await asyncio.gather(
            *(run_probe(p, uid, clock=self._clock) for p in self._probes), return_exceptions=True
        )
        results: list[ProbeResult] = []
        for probe, out in zip(self._probes, ran, strict=True):
            if isinstance(out, BaseException):
                results.append(crashed_result(probe, clock=self._clock))
            elif out is not None:
                results.append(out)
        done = tuple(results)
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


__all__ = ["CHECK_COOLDOWN_S", "HealthService", "Speaker"]
