# src/jarvis/health/service.py
"""The self-health check (R4 D5/D6). Deterministic: probes -> rollup -> stored -> fixed-template
line -> alert on change. No model is called anywhere, so it works with the brain off.

Alerts (through the notify port, `Signal(source="system")`): a fault that was not there at the
last check raises `health_fault` (urgent) naming only the NEW faults; when every fault is gone,
`health_recovered` (info). A steady fault is not repeated.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Any

from jarvis.alerts import AlertKind
from jarvis.health.models import HealthReport
from jarvis.health.probes import Probe, run_probe
from jarvis.health.report import compose_line, rollup
from jarvis.health.store import HealthStore
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.voice.service import SpeakRequest

log = get_logger(__name__)


class HealthService:
    def __init__(
        self,
        probes: Sequence[Probe],
        store: HealthStore,
        *,
        notifier: Notifier | None = None,
        voice: Any | None = None,  # a VoiceService (speak(uid, SpeakRequest))
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._probes = tuple(probes)
        self._store = store
        self._notifier = notifier
        self._voice = voice
        self._clock = clock

    async def check(self, uid: str) -> HealthReport:
        """Run every probe at once, store the result, alert on change. Raises only if the
        store cannot be read or written (the caller counts that owner as failed)."""
        ran = await asyncio.gather(*(run_probe(p, uid, clock=self._clock) for p in self._probes))
        results = tuple(r for r in ran if r is not None)
        report = HealthReport(overall=rollup(results), results=results, at=self._clock())
        before = await self._store.last(uid)
        await self._store.save(uid, report)
        await self._alert(uid, before, report)
        return report

    async def last(self, uid: str) -> HealthReport | None:
        return await self._store.last(uid)

    async def speak(self, uid: str) -> Any | None:
        """Say the last result aloud through the voice service; None when there is nothing to
        say or no voice. Voice errors reach the caller."""
        report = await self._store.last(uid)
        if report is None or self._voice is None:
            return None
        return await self._voice.speak(uid, SpeakRequest(text=compose_line(report)))

    async def _alert(self, uid: str, before: HealthReport | None, now: HealthReport) -> None:
        if self._notifier is None:
            return
        old = before.faulty_keys if before is not None else frozenset()
        new = now.faulty_keys - old
        if new:
            await self._send(uid, "health_fault", compose_line(now, only=new))
        elif old and not now.faulty_keys:
            await self._send(uid, "health_recovered", compose_line(now))

    async def _send(self, uid: str, kind: AlertKind, text: str) -> None:
        assert self._notifier is not None
        try:
            await self._notifier.notify(uid, Signal(source="system", kind=kind), text)
        except Exception as exc:  # noqa: BLE001 - an alert that cannot go never fails the check
            log.error("health alert not sent", extra={"kind": kind, "error": type(exc).__name__})


__all__ = ["HealthService"]
