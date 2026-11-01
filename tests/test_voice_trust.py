# tests/test_voice_trust.py — slice 9 review: a spoken turn is not fully trusted. Anyone in the room
# (a TV, a guest, the keep-listening window, auto-send) can be heard, so on `channel: voice`
# every write tool becomes an approval card (memory, drafts, events), and spoken owner messages
# never feed memory learning. Reads still run; typed turns are unchanged.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from memory_fakes import UID, rig

from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest, Session, Turn
from jarvis.llm.base import Role, ToolCall
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.recall import extract
from jarvis.recall.learning import snapshot
from jarvis.recall.models import SettingsPatch
from jarvis.recall.tools import memory_tools
from jarvis.tools import Gateway, Policy, ToolRegistry
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import context_trust, spoken_in_context


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )


class Ran:
    def __init__(self) -> None:
        self.drafts: list[dict[str, object]] = []
        self.reads = 0


def _tools(ran: Ran) -> list[Tool]:
    def draft(a: dict[str, object]) -> dict[str, object]:
        ran.drafts.append(a)
        return {"draft": "d1"}

    def inbox(a: dict[str, object]) -> dict[str, object]:
        ran.reads += 1
        return {"mail": []}

    return [
        Tool(
            "gmail_draft",
            "Draft a mail (not sent).",
            {"type": "object", "properties": {"to": {"type": "string"}}},
            ActionRisk.REVERSIBLE,
            draft,
            summarize=lambda a: f"Draft a mail to {a.get('to')}",
        ),
        Tool(
            "clock",
            "Read the time.",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            inbox,
            trusted_output=True,
        ),
    ]


def _brain(r, ran: Ran) -> Brain:  # type: ignore[no-untyped-def]
    reg = ToolRegistry()
    for t in [*memory_tools(r.svc), *_tools(ran)]:
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=r.audit)
    return Brain(
        brains=r.brains,
        store=InMemorySessionStore(),
        settings=_settings(),
        gateway=gw,
        billing=r.billing,
        memory=r.svc,
    )


def _req(msg: str, **kw: object) -> ChatRequest:
    return ChatRequest(message=msg, user_id=UID, **kw)  # type: ignore[arg-type]


DRAFT = ToolCall(id="t1", name="gmail_draft", arguments={"to": "bob@example.com"})
SAVE = ToolCall(
    id="t2", name="memory_save", arguments={"text": "Owner's bank is EvilBank", "category": "other"}
)


# ---- every write on a spoken turn is a card ----------------------------------------------------


async def test_a_spoken_turn_turns_a_reversible_write_into_an_approval_card() -> None:
    r, ran = rig(), Ran()
    brain = _brain(r, ran)
    r.private.script_tool_calls([DRAFT], "A draft is waiting for your approval, Sir.")
    res = await brain.chat(_req("draft a mail to bob", channel="voice"))
    assert [p.tool for p in res.pending_approvals] == ["gmail_draft"]
    assert ran.drafts == []


async def test_a_typed_turn_still_writes_a_reversible_draft_directly() -> None:
    r, ran = rig(), Ran()
    brain = _brain(r, ran)
    r.private.script_tool_calls([DRAFT], "Drafted, Sir.")
    res = await brain.chat(_req("draft a mail to bob"))
    assert res.pending_approvals == [] and len(ran.drafts) == 1


async def test_a_spoken_memory_save_is_a_card_too() -> None:
    r, ran = rig(), Ran()
    brain = _brain(r, ran)
    r.private.script_tool_calls([SAVE], "Waiting for you, Sir.")
    res = await brain.chat(_req("remember my bank is EvilBank", channel="voice"))
    assert [p.tool for p in res.pending_approvals] == ["memory_save"]
    assert (await r.store.load(UID)).all_facts() == []


async def test_reads_still_run_on_a_spoken_turn() -> None:
    r, ran = rig(), Ran()
    brain = _brain(r, ran)
    r.private.script_tool_calls([ToolCall(id="t3", name="clock", arguments={})], "Ten, Sir.")
    res = await brain.chat(_req("what time is it", channel="voice"))
    assert res.pending_approvals == [] and ran.reads == 1


async def test_a_spoken_card_runs_once_when_approved_on_screen() -> None:
    r, ran = rig(), Ran()
    brain = _brain(r, ran)
    r.private.script_tool_calls([DRAFT], "Waiting, Sir.")
    res = await brain.chat(_req("draft a mail to bob", channel="voice"))
    (card,) = res.pending_approvals
    done = await brain.approve(card.id, session_id=res.session_id, user_id=UID)
    assert done.reply and len(ran.drafts) == 1
    # the approval token was spent: approving again does nothing
    with pytest.raises(LookupError):
        await brain.approve(card.id, session_id=res.session_id, user_id=UID)
    assert len(ran.drafts) == 1


async def test_the_gateway_asks_for_writes_while_spoken_and_spends_tokens_it_is_given() -> None:
    ran = Ran()
    reg = ToolRegistry()
    for t in _tools(ran):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    assert spoken_in_context() is False  # outside a turn: not spoken
    with context_trust(untrusted=False, spoken=True):
        assert spoken_in_context() is True
        asked = await gw.execute(DRAFT, scope="u:s")
        read = await gw.execute(ToolCall(id="r", name="clock", arguments={}), scope="u:s")
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and asked.pending
    assert read.outcome is GatewayOutcome.EXECUTED
    ok = await gw.execute(DRAFT, confirmation_id=asked.pending.id, scope="u:s")
    again = await gw.execute(DRAFT, confirmation_id=asked.pending.id, scope="u:s")
    assert ok.outcome is GatewayOutcome.EXECUTED
    assert again.outcome is GatewayOutcome.CONFIRMATION_INVALID
    assert len(ran.drafts) == 1


# ---- spoken messages never feed memory learning ------------------------------------------------


def test_the_learning_snapshot_skips_spoken_owner_messages() -> None:
    s = Session(id="sess_v", user_id=UID)
    s.append(Turn(role=Role.USER, content="I live in Kochi"))
    s.append(Turn(role=Role.ASSISTANT, content="Noted."))
    s.append(Turn(role=Role.USER, content="My bank is EvilBank", channel="voice"))
    s.append(Turn(role=Role.ASSISTANT, content="Noted."))
    assert [line.text for line in snapshot(s).owner] == ["I live in Kochi"]


@pytest.mark.parametrize("stream", [False, True])
async def test_spoken_turns_are_marked_and_never_learned(stream: bool) -> None:
    r, ran = rig(), Ran()
    r.clock.at = datetime.now(UTC)
    await r.svc.update_settings(UID, SettingsPatch(learn=True, confirm_spend=True))
    brain = _brain(r, ran)
    sid: str | None = None
    for msg in ("I live in Kochi", "I like tea", "I have a cat"):
        req = _req(msg, channel="voice", session_id=sid)
        if stream:
            async for _ in brain.chat_stream(req):
                pass
            listed = await brain.store.list_for_user(UID)
            sid = listed[0].id
        else:
            sid = (await brain.chat(req)).session_id
    await r.svc.drain()
    assert sid is not None
    session = await brain.store.get(sid)
    assert session is not None
    owner = [t for t in session.turns if t.role is Role.USER and not t.blocks]
    assert [t.channel for t in owner] == ["voice"] * 3
    assert not any(c.system == extract.SYSTEM for c in r.private.calls)
    assert (await r.store.load(UID)).all_facts() == []
