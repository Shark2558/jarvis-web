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
# - `reads_over(rules, audit)` (I1): the gateway's governed path for background reads
#   (`jarvis.tools.background.BackgroundReads`) over a fake gateway view: the default policy plus
#   the rules `rules()` gives (None: no permission service, which fails closed), every tool a
#   known read-only one. `NO_ROWS` is a permission service with no row set (every row its
#   default). A part's fakes that swap `permissions` swap `reads` with it.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.gate import GateStore, HelperSender
from jarvis.helpers.kinds import PartName
from jarvis.helpers.ports import HelperContext, PendingSource
from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import decide
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog, AuditTrail
from jarvis.tools.background import BackgroundReads
from jarvis.tools.policy import OwnerRules, Policy, PolicyRule

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


class NoRows:
    """His permission service with no row set: every row reads as its default."""

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return []


NO_ROWS = NoRows()


class AnyReadRegistry:
    """A fake gateway registry: every tool name is a known read-only tool (`known` narrows it)."""

    def __init__(
        self, known: frozenset[str] | None = None, risk: ActionRisk = ActionRisk.READ_ONLY
    ):
        self.known, self.risk = known, risk

    def get(self, name: str) -> Any:
        if self.known is not None and name not in self.known:
            return None
        return SimpleNamespace(name=name, risk=self.risk)


def reads_over(
    rules: Callable[[], OwnerRules | None],
    audit: AuditTrail,
    *,
    now: Callable[[], datetime] | None = None,
    registry: Any = None,
) -> BackgroundReads:
    """BackgroundReads over a fake gateway view (the default policy, `rules()` read per call)."""
    reg = registry if registry is not None else AnyReadRegistry()

    def view() -> Any:
        return SimpleNamespace(policy=Policy(), rules=rules(), audit=audit, registry=reg)

    return BackgroundReads(view, audit=audit, now=now)


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
    audit = AuditLog()
    c = HelperContext(
        settings=s,
        docs=docs,
        sender=send.for_part(part),
        owners=(UID,),
        tz=s.user_timezone,
        prefix=s.firestore_prefix,
        now=clock,
        audit=audit,
        pending_all=lambda: pending,
        permissions=lambda: None,
        reads=reads_over(lambda: NO_ROWS, audit, now=clock),
    )
    return c, notifier, docs, clock


__all__ = [
    "NOON_IST",
    "NO_ROWS",
    "TWO_AM_IST",
    "UID",
    "AnyReadRegistry",
    "Clock",
    "FakeNotifier",
    "NoRows",
    "ctx",
    "reads_over",
    "sender",
    "settings",
]
