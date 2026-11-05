# tests/test_gateway_spoken.py -- R2 I1 (review C H2): a card proposed on a spoken turn remembers
# it (`PendingAction.spoken`), and approving it later on screen, outside that turn, runs the tool
# with `ToolContext.spoken` set, so a note or a thing written from it records `voice` origin (never
# vouches), not `typed`. Generic, at gateway level; the kb and belongings ends are checked too.
from __future__ import annotations

from typing import Any

from kb_fakes import UID, build_rig

from jarvis.belongings.service import BelongingsService
from jarvis.belongings.store import BelongingsStore
from jarvis.belongings.tools import belongings_tools
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, PendingAction
from jarvis.kb.tools import notes_tools
from jarvis.keyring import Keyring
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.context import current_tool_context
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

SCOPE = f"{UID}:sess_1"


class Seen:
    def __init__(self) -> None:
        self.spoken: list[bool] = []

    def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        ctx = current_tool_context()
        self.spoken.append(bool(ctx and ctx.spoken))
        return {"ok": True}


def _gw(*tools: Tool, rules: list[PolicyRule] | None = None) -> Gateway:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog())


def _write(seen: Seen, *, spoken_ok: bool = False) -> Tool:
    return Tool(
        "thing_write",
        "test",
        {"type": "object", "properties": {"n": {"type": "integer"}}},
        ActionRisk.REVERSIBLE,
        seen,
        summary_template="Write {n}",
        spoken_ok=spoken_ok,
    )


def _call(n: int = 1) -> ToolCall:
    return ToolCall(id=f"c{n}", name="thing_write", arguments={"n": n})


async def test_a_card_proposed_on_a_spoken_turn_runs_spoken_when_approved_on_screen() -> None:
    seen = Seen()
    gw = _gw(_write(seen))
    with context_trust(untrusted=False, spoken=True):
        card = await gw.execute(_call(), scope=SCOPE)
    assert card.outcome is GatewayOutcome.AWAITING_CONFIRMATION and card.pending
    assert card.pending.spoken is True
    done = await gw.execute(_call(), scope=SCOPE, confirmation_id=card.pending.id)
    assert done.outcome is GatewayOutcome.EXECUTED
    assert seen.spoken == [True]


async def test_a_typed_card_runs_not_spoken() -> None:
    seen = Seen()
    ask = PolicyRule(tool_pattern="thing_write", effect=Effect.ASK, source="owner")
    gw = _gw(_write(seen), rules=[ask])
    with context_trust(untrusted=False):
        card = await gw.execute(_call(), scope=SCOPE)
    assert card.pending is not None and card.pending.spoken is False
    await gw.execute(_call(), scope=SCOPE, confirmation_id=card.pending.id)
    assert seen.spoken == [False]


async def test_a_spoken_write_that_runs_at_once_runs_spoken() -> None:
    seen = Seen()
    gw = _gw(_write(seen, spoken_ok=True))
    with context_trust(untrusted=False, spoken=True):
        out = await gw.execute(_call(), scope=SCOPE)
    assert out.outcome is GatewayOutcome.EXECUTED and seen.spoken == [True]


async def test_a_typed_duplicate_of_a_spoken_card_keeps_it_spoken() -> None:
    seen = Seen()
    ask = PolicyRule(tool_pattern="thing_write", effect=Effect.ASK, source="owner")
    gw = _gw(_write(seen), rules=[ask])
    with context_trust(untrusted=False, spoken=True):
        first = await gw.execute(_call(), scope=SCOPE)
    with context_trust(untrusted=False):
        again = await gw.execute(_call(), scope=SCOPE)
    assert first.pending and again.pending and again.pending.id == first.pending.id
    stored = await gw.gate.get(first.pending.id)
    assert stored is not None and stored.spoken is True
    await gw.execute(_call(), scope=SCOPE, confirmation_id=first.pending.id)
    assert seen.spoken == [True]


async def test_a_spoken_duplicate_of_a_typed_card_makes_it_spoken() -> None:
    seen = Seen()
    ask = PolicyRule(tool_pattern="thing_write", effect=Effect.ASK, source="owner")
    gw = _gw(_write(seen), rules=[ask])
    with context_trust(untrusted=False):
        first = await gw.execute(_call(), scope=SCOPE)
    with context_trust(untrusted=False, spoken=True):
        await gw.execute(_call(), scope=SCOPE)
    assert first.pending is not None
    stored = await gw.gate.get(first.pending.id)
    assert stored is not None and stored.spoken is True


async def test_a_re_proposed_card_keeps_spoken() -> None:
    """A spoken card whose text changed before approval is withdrawn and proposed again outside
    the turn: the new card is still spoken."""
    seen = Seen()
    words = {"n": "first"}

    def card(_: dict[str, Any]) -> str:
        return f"Write {words['n']}"

    tool = Tool(
        "thing_write",
        "test",
        {"type": "object", "properties": {"n": {"type": "integer"}}},
        ActionRisk.REVERSIBLE,
        seen,
        summarize=card,
    )
    gw = _gw(tool)
    with context_trust(untrusted=False, spoken=True):
        first = await gw.execute(_call(), scope=SCOPE)
    assert first.pending is not None
    words["n"] = "second"
    again = await gw.execute(_call(), scope=SCOPE, confirmation_id=first.pending.id)
    assert again.outcome is GatewayOutcome.AWAITING_CONFIRMATION and again.pending
    assert again.pending.id != first.pending.id and again.pending.spoken is True
    assert seen.spoken == []


def test_a_card_stored_before_the_field_reads_as_not_spoken() -> None:
    old = PendingAction.model_validate(
        {"tool": "x", "arguments": {}, "risk": "irreversible", "summary": "x"}
    )
    assert old.spoken is False


# ---- the kb and belongings ends ----------------------------------------------------------------


async def test_a_spoken_note_approved_on_screen_is_stored_with_voice_origin() -> None:
    r = build_rig()
    reg = ToolRegistry()
    for t in notes_tools(r.svc):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    call = ToolCall(id="n1", name="kb_add_note", arguments={"text": "the plumber is Ravi"})
    with context_trust(untrusted=False, spoken=True):
        card = await gw.execute(call, scope=SCOPE)
    assert card.pending is not None and card.pending.spoken
    done = await gw.execute(call, scope=SCOPE, confirmation_id=card.pending.id)
    assert done.outcome is GatewayOutcome.EXECUTED, done.error
    (note,) = (await r.store.load(UID)).notes
    assert note.origin == "voice"


async def test_a_spoken_thing_approved_on_screen_is_stored_with_voice_origin() -> None:
    ring = Keyring(bytes(range(1, 33)))
    svc = BelongingsService(BelongingsStore(MemoryDocs(), ring))
    reg = ToolRegistry()
    for t in belongings_tools(svc):
        reg.register(t)
    ask = PolicyRule(tool_pattern="belongings_*", effect=Effect.ASK, source="owner")
    gw = Gateway(registry=reg, policy=Policy([ask]), gate=ConfirmationGate(), audit=AuditLog())
    args = {"item": "passport", "place": "the blue file"}
    call = ToolCall(id="b1", name="belongings_put", arguments=args)
    with context_trust(untrusted=False, spoken=True):
        card = await gw.execute(call, scope=SCOPE)
    assert card.pending is not None and card.pending.spoken
    done = await gw.execute(call, scope=SCOPE, confirmation_id=card.pending.id)
    assert done.outcome is GatewayOutcome.EXECUTED, done.error
    (thing,) = (await svc.state(UID)).live()
    assert thing.origin == "voice"
