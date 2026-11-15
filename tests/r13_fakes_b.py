# tests/r13_fakes_b.py -- R13 Part B's own fakes (BRIEF-COMMON.md: unique per part), built on I0's
# shared `r13_fakes` (the seeded in-memory store, FIXED IST clocks), never a copy of them. Imported
# bare (`from r13_fakes_b import ...`). No real personal data: the pilot's made-up pieces, a test
# key of 32 distinct bytes, a shop called "Dry cleaner".
#
#   rig(...)            B built on the seeded store (16 Nov 2026 09:00 IST), B's writer and an
#                       observer bound into it, a keyring, a recording notifier and a REAL gateway
#                       with B's five tools
#   Rig.tool(name, **)  one call through the gateway (tainted / spoken rounds on request)
#   FakeNotifier        records (uid, kind, message); `fail` raises, `held` answers "hold"
#   the pilot's pieces by name (BLUE_SHIRT ... SHORTS), its places and its first sock pair
#   TWIN                a second white formal shirt, near-identical to WHITE_SHIRT (LND-04)
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from r13_fakes import (
    PAIRS,
    PILOT,
    PLACES,
    UID,
    FixedClock,
    MemoryWardrobeStore,
    RecordingObserver,
    ev,
    ist,
    piece,
    seeded_store,
    wardrobe_context,
)

from jarvis.core.guardrails import ConfirmationGate
from jarvis.keyring import Keyring
from jarvis.llm.base import ToolCall
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import DocTx, MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayResult
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust
from jarvis.wardrobe.laundry import part as laundry_part
from jarvis.wardrobe.laundry.flows import Desk
from jarvis.wardrobe.laundry.store import Entry, LaundryDoc, ReviewDoc
from jarvis.wardrobe.laundry.writer import LaundryWriter
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Commit, WardrobePart

ROOT = bytes(range(1, 33))  # 32 distinct bytes: a test key, never a real one
(
    BLUE_SHIRT, WHITE_SHIRT, NAVY_SHIRT, TEE, TROUSERS, JEANS, KURTA, PYJAMA, VEST_A, VEST_B,
    UNDERPANTS, SOCK_L, SOCK_R, GREY_SOCK_1, GREY_SOCK_2, SHOE_L, SHOE_R, SNEAKER_L, SNEAKER_R,
    BELT, WATCH, JACKET, BLAZER, SHORTS,
) = (p.id for p in PILOT)  # fmt: skip
DRAWER, RACK, SHOE_RACK, TRAY, BASKET, TRAVEL = (p.id for p in PLACES)
SOCK_PAIR = PAIRS[0].id  # SOCK_L + SOCK_R
TWIN = "wi_" + "e" * 12  # a second "White formal shirt"


@dataclass
class FakeNotifier:
    sent: list[tuple[str, str, str]] = field(default_factory=list)
    fail: bool = False
    held: bool = False
    off: bool = False  # the app has no notifier: `ctx.notifier()` answers None

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
        self.sent.append((uid, signal.kind, message))
        if self.held:
            return Delivery(action="hold", reason="quiet_hours")
        return Delivery(action="ring", reason="test", telegram=True)


@dataclass
class Rig:
    store: MemoryWardrobeStore
    docs: MemoryDocs
    clock: FixedClock
    part: WardrobePart
    writer: LaundryWriter
    desk: Desk
    observer: RecordingObserver
    notifier: FakeNotifier
    gateway: Gateway
    audit: AuditLog
    scope: str = f"{UID}:s1"

    async def view(self) -> WardrobeView:
        return await self.store.view(UID)

    async def piece(self, pid: str) -> Piece:
        found = (await self.view()).piece(pid)
        assert found is not None, pid
        return found

    async def state(self, pid: str) -> str:
        return (await self.piece(pid)).state

    async def review(self) -> ReviewDoc:
        return await self.desk.store.read_review(self.docs.get, UID)

    async def open_entries(self) -> tuple[Entry, ...]:
        return tuple(e for e in (await self.review()).entries if e.closed_at is None)

    async def laundry(self) -> LaundryDoc:
        return await self.desk.store.read_laundry(self.docs.get, UID)

    async def commit(self, *events: Event) -> Any:
        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            return Commit(events=tuple(events))

        return await self.store.transact(UID, fn)

    async def wear(self, pid: str, plan: str | None = None) -> None:
        await self.commit(ev(pid, "wear_started", self.clock(), plan=plan))

    async def tool(
        self, name: str, *, tainted: bool = False, spoken: bool = False, **args: Any
    ) -> GatewayResult:
        call = ToolCall(id=f"t-{name}", name=name, arguments=dict(args))
        with context_trust(untrusted=tainted, spoken=spoken, owner_text="test"):
            return await self.gateway.execute(call, scope=self.scope)

    def text(self) -> str:
        """Everything stored, as one string (a needle search over every document)."""
        return repr(self.docs._data)  # noqa: SLF001 - the fake's own store, for needle checks


async def add_twin(store: MemoryWardrobeStore, clock: FixedClock) -> None:
    twin = piece(TWIN, "shirt", label="White formal shirt", colour="white", formality=5)
    twin = twin.model_copy(update={"place": RACK})

    async def fn(view: WardrobeView, tx: DocTx) -> Commit:
        return Commit(events=(ev(TWIN, "registered", clock(), place=RACK),), records=(twin,))

    await store.transact(UID, fn)


async def rig(
    *, keyring: bool = True, twin: bool = True, at: datetime | None = None, **settings: Any
) -> Rig:
    """B on the seeded pilot store, 16 Nov 2026 09:00 IST unless `at`; the clock then moves on
    one minute so a first tap is never at the registration's instant."""
    docs = MemoryDocs()
    clock = FixedClock(at or ist(2026, 11, 16, 9, 0))
    store, _ = await seeded_store(docs, clock)
    if twin:
        await add_twin(store, clock)
    clock.advance(minutes=1)
    notifier, observer = FakeNotifier(), RecordingObserver()
    ctx = wardrobe_context(docs, now=clock, store=store)
    if settings:
        ctx = dataclasses.replace(ctx, s=ctx.s.model_copy(update=settings))
    ctx = dataclasses.replace(
        ctx,
        keyring=Keyring(ROOT) if keyring else None,
        notifier=lambda: None if notifier.off else notifier,
    )
    part = laundry_part.build(ctx)
    writer = part.services["review_writer"]
    store.bind(review_writer=writer, observers=[observer])
    reg = ToolRegistry()
    for tool in part.tools:
        reg.register(tool)
    audit = AuditLog()
    gateway = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=audit)
    assert writer.desk is not None
    return Rig(store, docs, clock, part, writer, writer.desk, observer, notifier, gateway, audit)


__all__ = [
    "BASKET",
    "BELT",
    "BLAZER",
    "BLUE_SHIRT",
    "DRAWER",
    "GREY_SOCK_1",
    "GREY_SOCK_2",
    "JACKET",
    "JEANS",
    "KURTA",
    "NAVY_SHIRT",
    "PYJAMA",
    "RACK",
    "ROOT",
    "SHOE_L",
    "SHOE_R",
    "SHOE_RACK",
    "SHORTS",
    "SNEAKER_L",
    "SNEAKER_R",
    "SOCK_L",
    "SOCK_PAIR",
    "SOCK_R",
    "TEE",
    "TRAVEL",
    "TRAY",
    "TROUSERS",
    "TWIN",
    "UNDERPANTS",
    "VEST_A",
    "VEST_B",
    "WATCH",
    "WHITE_SHIRT",
    "FakeNotifier",
    "Rig",
    "add_twin",
    "rig",
]
