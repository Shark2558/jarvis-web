# tests/r11_fakes.py -- R11 I0 shared fakes (docs/plans/r11-free-helpers.md; BRIEF-COMMON.md).
# Imported bare (`from r11_fakes import ...`) by the I0 tests, the parts' tests and
# evals/r11_helpers. Each part keeps its OWN extra fakes in `tests/r11_fakes_<a|b|c|d>.py` (unique
# names, so the four branches never clash when merged).
#
# - `Clock`: a settable "now" (aware, UTC by default).
# - `FakeNotifier`: the `Notifier` port; records (uid, kind, message, named) and answers the
#   Delivery the test chooses (ring + Telegram by default), or applies the REAL policy
#   (`policy=True`: quiet hours, ephemeral nudges, daytime rings) so a part can prove "held at
#   02:00" without the whole service.
# - `sender(...)`: a HelperSender on MemoryDocs with the fake notifier and a clock.
# - `ctx(part, ...)`: a HelperContext for one part, everything a part may touch, all fakes.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jarvis.config import Settings
from jarvis.helpers.gate import GateStore, HelperSender
from jarvis.helpers.kinds import PartName
from jarvis.helpers.ports import HelperContext, PendingSource
from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import decide
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

UID = "u_r11_owner"
NOON_IST = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)  # 12:00 in Asia/Kolkata
TWO_AM_IST = datetime(2026, 11, 9, 20, 30, tzinfo=UTC)  # 02:00 in Asia/Kolkata


@dataclass
class Clock:
    at: datetime = NOON_IST

    def __call__(self) -> datetime:
        return self.at


@dataclass
class FakeNotifier:
    """`delivery`: what every call answers, unless `policy` is on (then the real decision decides:
    ring/silent -> delivered on Telegram, hold -> held, drop -> dropped)."""

    clock: Callable[[], datetime] = field(default_factory=Clock)
    delivery: Delivery = field(
        default_factory=lambda: Delivery(action="ring", reason="test", telegram=True)
    )
    policy: bool = False
    settings: NotifySettings = field(default_factory=NotifySettings)
    fail: bool = False
    calls: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        if self.fail:
            raise RuntimeError("the notifier is down")
        self.calls.append((uid, signal.kind, message, named_message))
        self.signals.append(signal)
        if not self.policy:
            return self.delivery
        d = decide(signal, self.settings, self.clock())
        if d.action in ("ring", "silent"):
            return Delivery(action=d.action, reason=d.reason, telegram=True)
        return Delivery(action=d.action, reason=d.reason)


def settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


def sender(
    *,
    clock: Clock | None = None,
    notifier: FakeNotifier | None = None,
    docs: MemoryDocs | None = None,
    **over: Any,
) -> tuple[HelperSender, FakeNotifier, MemoryDocs, Clock]:
    clock = clock or Clock()
    notifier = notifier or FakeNotifier(clock=clock)
    docs = docs or MemoryDocs()
    s = settings(**over)
    return HelperSender(notifier, GateStore(docs), s, now=clock), notifier, docs, clock


def ctx(
    part: PartName,
    *,
    pending: tuple[PendingSource, ...] = (),
    **over: Any,
) -> tuple[HelperContext, FakeNotifier, MemoryDocs, Clock]:
    """A part's context on fakes: no keyring, no Google, no billing, no brains (a part that needs
    one adds it with `dataclasses.replace(ctx, keyring=...)`)."""
    send, notifier, docs, clock = sender(**over)
    s = settings(**over)
    c = HelperContext(
        settings=s,
        docs=docs,
        sender=send.for_part(part),
        owners=(UID,),
        tz=s.user_timezone,
        prefix=s.firestore_prefix,
        now=clock,
        audit=AuditLog(),
        pending_all=lambda: pending,
        permissions=lambda: None,
    )
    return c, notifier, docs, clock


__all__ = [
    "NOON_IST",
    "TWO_AM_IST",
    "UID",
    "Clock",
    "FakeNotifier",
    "ctx",
    "sender",
    "settings",
]
