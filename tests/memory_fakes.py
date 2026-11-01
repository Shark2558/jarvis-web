# tests/memory_fakes.py — slice 8 helpers: a MemoryService on MemoryDocs with a fixed clock, a
# private + a training brain, and a scripted extraction reply. A plain module (not conftest) so
# test files can import it.
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from billing_fakes import PAID_TIERS, Clock, PricedMock, billing

from jarvis.billing import Billing
from jarvis.core.models import Session, Turn
from jarvis.llm.base import Role
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.recall.service import MemoryService
from jarvis.recall.store import MemoryStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

UID = "u_owner"
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)  # 11:30 IST
MOCK_TIERS = {t: f"mock-{t.value}" for t in ModelTier}


def extraction(
    facts: list[dict[str, Any]] | None = None, replace: list[dict[str, Any]] | None = None
) -> str:
    """What the FAST model returns for one learning run."""
    return json.dumps({"facts": facts or [], "replace": replace or []})


def brains(
    private: MockProvider | None = None,
    training: MockProvider | None = None,
    *,
    paid: bool = False,
    default: str = "private",
) -> BrainRegistry:
    return BrainRegistry(
        [
            BrainSpec(
                id="private",
                label="Claude",
                provider=private or MockProvider(),
                tiers=PAID_TIERS if paid else MOCK_TIERS,
            ),
            BrainSpec(
                id="training",
                label="Gemini (free)",
                provider=training or MockProvider(),
                tiers=MOCK_TIERS,
                trains_on_content=True,
            ),
        ],
        default_id=default,
    )


@dataclass
class Rig:
    docs: MemoryDocs
    store: MemoryStore
    svc: MemoryService
    brains: BrainRegistry
    private: MockProvider
    training: MockProvider
    billing: Billing
    audit: AuditLog
    clock: Clock
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def spec(self) -> BrainSpec:
        return self.brains.get("private")

    @property
    def training_spec(self) -> BrainSpec:
        return self.brains.get("training")


def rig(
    *,
    paid: bool = False,
    docs: MemoryDocs | None = None,
    max_runs: int = 20,
    private: MockProvider | None = None,
) -> Rig:
    d = docs if docs is not None else MemoryDocs()
    p = private or (PricedMock(per_call=0.0005) if paid else MockProvider())
    t = MockProvider()
    reg = brains(p, t, paid=paid)
    clock = Clock(NOW)
    bill = billing(reg, docs=d, clock=clock)
    audit = AuditLog()
    store = MemoryStore(d)
    svc = MemoryService(
        store=store,
        brains=reg,
        billing=bill,
        audit=audit,
        tz="Asia/Kolkata",
        clock=clock,
        max_runs=max_runs,
    )
    return Rig(d, store, svc, reg, p, t, bill, audit, clock)


def session_with(*owner: str, minutes_ago: int = 0, sid: str = "sess_learn") -> Session:
    """A conversation with these owner messages (each answered), the first `minutes_ago` old."""
    s = Session(id=sid, user_id=UID)
    at = NOW - timedelta(minutes=minutes_ago)
    for i, text in enumerate(owner):
        s.append(Turn(role=Role.USER, content=text, created_at=at + timedelta(seconds=i)))
        s.append(Turn(role=Role.ASSISTANT, content="Noted, Sir."))
    return s
