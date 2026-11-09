# tests/health_fakes.py -- stand-ins for the R4 self-health tests. Never imported from conftest.
from __future__ import annotations

from typing import Any

from jarvis.alerts import AlertKind
from jarvis.health.models import ProbeOutcome
from jarvis.health.probes import Probe
from jarvis.notify.ports import Delivery, Signal

UID = "u_owner"
NOW = 1_800_000_000.0


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Notes:
    """A Notifier that records what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, Signal, str]] = []

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        self.sent.append((uid, signal, message))
        return Delivery(action="ring", reason="test", telegram=True)

    def kinds(self) -> list[AlertKind]:
        return [s.kind for _, s, _ in self.sent]


def fixed(key: str, label: str, status: str, reason: str = "fine") -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        return ProbeOutcome(status, reason)  # type: ignore[arg-type]

    return Probe(key=key, label=label, check=check)


class Flip:
    """A probe whose answer the test changes between runs. Default: Redis, a probe whose faults
    alert (R5.1 D4: the home bridge's never do; the home watchdog owns that alert)."""

    def __init__(self, key: str = "redis", label: str = "Redis") -> None:
        self.status = "ok"
        self.probe = Probe(key=key, label=label, check=self._check)

    async def _check(self, _uid: str) -> ProbeOutcome:
        return ProbeOutcome(self.status, "x")  # type: ignore[arg-type]


class BoomProvider:
    """An LLM provider that fails the way the vendor does."""

    name = "boom"

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls = 0

    async def complete(self, **kw: Any) -> Any:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return object()
