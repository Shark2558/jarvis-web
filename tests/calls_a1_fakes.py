# tests/calls_a1_fakes.py — R18 A1 test rig: a real gateway with the calls tools over the
# in-memory call store, a clock, a passkey policy, an approval guard and a call starter.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.calls.approvals import CallsService, GrantBook
from jarvis.calls.cards import CardBuilder, Estimator, TokenRate
from jarvis.calls.limits import Limits
from jarvis.calls.models import CallCard, LanguageResult, SpeechOption
from jarvis.calls.prices import SpeechPrice
from jarvis.calls.store import MemoryCallStore
from jarvis.calls.tools import calls_tools
from jarvis.core.guardrails import ConfirmationGate, PendingAction
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

UID = "u_0123456789abcdef"
SCOPE = f"{UID}:calls"
NUMBER = "+919000000001"
NOON_IST = datetime(2026, 11, 27, 6, 30, tzinfo=UTC)
PRICES = {
    SpeechOption.GOOGLE: SpeechPrice(SpeechOption.GOOGLE, 2.0, 2.5, 3600, 1_000_000),
    SpeechOption.AZURE: SpeechPrice(SpeechOption.AZURE, 0.0, 0.0, can_bill=False),
}
RATE = TokenRate(input_inr=8.8, output_inr=44.0, cache_read_inr=0.88)


class Clock:
    def __init__(self, at: datetime = NOON_IST) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kw: float) -> None:
        self.at = self.at + timedelta(**kw)


class Passkeys:
    def __init__(self, required: bool = False) -> None:
        self.required = required

    async def passkey_required(self, uid: str) -> bool:
        return self.required


@dataclass
class Guard:
    """The approval guard: when passkeys are in force, a card that can't be undone needs a proof
    made for it (here: the string "pk:<card id>")."""

    passkeys: Passkeys
    seen: list[str] = field(default_factory=list)

    async def check_approval(self, user_id: str, action: PendingAction, proof: Any) -> str | None:
        self.seen.append(action.id)
        if not action.irreversible or not self.passkeys.required:
            return None
        if proof != f"pk:{action.id}":
            raise PermissionError("needs your passkey")
        return "passkey ab12cd34"


@dataclass
class Starter:
    started: list[tuple[str, str, str]] = field(default_factory=list)
    fail: bool = False

    async def start(self, uid: str, card: CallCard, approval_id: str) -> str:
        if self.fail:
            raise RuntimeError("engine down")
        self.started.append((uid, card.id, approval_id))
        return "call_00000000000a"


@dataclass
class Rig:
    store: MemoryCallStore
    service: CallsService
    gateway: Gateway
    audit: AuditLog
    clock: Clock
    passkeys: Passkeys
    guard: Guard
    starter: Starter


async def rig(*, passkey: bool = False, languages: tuple[str, ...] = ("en-IN", "ml-IN")) -> Rig:
    store, clock, passkeys = MemoryCallStore(), Clock(), Passkeys(passkey)
    await store.save_settings(UID, {"owner_first_name": "Sam"})
    for lang in languages:
        await store.put_language_result(
            LanguageResult(
                lang=lang,
                option=SpeechOption.AZURE,
                checked_at=NOON_IST,
                passed=True,
                inr_per_minute=0.0,
            )
        )
    audit = AuditLog()
    builder = CardBuilder(store, Estimator(PRICES, RATE), is_template=lambda n: True)
    limits = Limits(store, clock=clock)
    starter = Starter()
    service = CallsService(
        store,
        builder,
        limits,
        grants=GrantBook(clock),
        passkeys=passkeys,
        starter=starter,
        audit=audit,
    )
    reg = ToolRegistry()
    for t in calls_tools(service):
        reg.register(t)
    guard = Guard(passkeys)
    gateway = Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=audit, approval_guard=guard
    )
    return Rig(store, service, gateway, audit, clock, passkeys, guard, starter)


async def known(store: MemoryCallStore, number: str = NUMBER) -> None:
    """Make `number` one JARVIS called before (a week ago)."""
    await store.count_call(UID, (NOON_IST - timedelta(days=7)).date(), number)
