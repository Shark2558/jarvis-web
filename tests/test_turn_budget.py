# tests/test_turn_budget.py — slice 10 integration review L4 / L5: one owner message can propose at
# most 5 new approval cards and make at most 6 document tool calls (an injected "do it 50 times"
# can't flood the Approvals list or thrash the document cache); a duplicate proposal reads only its
# own conversation's waiting cards, never the whole list.
from __future__ import annotations

import pytest
from doc_fakes import make_pdf

from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, ConfirmationRequired, PendingAction
from jarvis.core.models import ChatRequest
from jarvis.documents.service import DocumentService
from jarvis.documents.store import CACHE_DOCS, AttachmentStore
from jarvis.documents.tools import document_tools
from jarvis.llm.base import ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.approvals import DocApprovalStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.budget import MAX_DOC_CALLS, MAX_NEW_CARDS, current_budget, turn_budget
from jarvis.tools.builtin import InMemoryWorld

R3 = ActionRisk.IRREVERSIBLE


def _sends(n: int, start: int = 0) -> list[ToolCall]:
    return [
        ToolCall(
            id=f"s{i}", name="send_message", arguments={"to": f"p{i}@example.com", "body": "hi"}
        )
        for i in range(start, start + n)
    ]


# ---- L4: approval cards per owner message --------------------------------------------------------


async def test_one_message_proposes_at_most_five_new_cards(
    brain: Brain, provider: MockProvider, gateway: Gateway, world: InMemoryWorld
) -> None:
    provider.script_tool_calls(_sends(MAX_NEW_CARDS + 3), "Several approvals are waiting, Sir.")
    resp = await brain.chat(ChatRequest(message="message everyone"))
    assert len(resp.pending_approvals) == MAX_NEW_CARDS
    assert len(await gateway.pending()) == MAX_NEW_CARDS and world.sent == []
    results = [
        b.content
        for b in provider.calls[-1].messages[-1].content  # type: ignore[union-attr]
        if hasattr(b, "content")
    ]
    refused = [r for r in results if "too many approvals" in r.lower()]
    assert len(refused) == 3 and all("nothing was proposed" in r.lower() for r in refused)
    entries = (await gateway.audit.tail(50)).entries  # type: ignore[attr-defined]
    assert sum(e.outcome == "denied" for e in entries) == 3
    # the next owner message has its own allowance
    provider.script_tool_calls(_sends(1, start=20), "One more is waiting.")
    again = await brain.chat(ChatRequest(message="and Ravi", session_id=resp.session_id))
    assert len(again.pending_approvals) == 1


async def test_a_repeated_proposal_is_not_a_new_card(
    brain: Brain, provider: MockProvider, gateway: Gateway
) -> None:
    provider.script_tool_calls(_sends(MAX_NEW_CARDS), "ok")
    resp = await brain.chat(ChatRequest(message="message them"))
    provider.script_tool_calls(_sends(MAX_NEW_CARDS) + _sends(1, start=9), "ok")
    again = await brain.chat(ChatRequest(message="again", session_id=resp.session_id))
    assert len(again.pending_approvals) == MAX_NEW_CARDS + 1  # the same 5 cards + 1 new
    assert len(await gateway.pending()) == MAX_NEW_CARDS + 1


def test_outside_a_turn_there_is_no_budget() -> None:
    assert current_budget() is None
    with turn_budget() as b:
        assert current_budget() is b and b.cards == MAX_NEW_CARDS and b.docs == MAX_DOC_CALLS
    assert current_budget() is None


async def test_a_proposal_reads_only_its_own_conversations_cards() -> None:
    docs = MemoryDocs()
    gate = ConfirmationGate(DocApprovalStore(docs))
    for i in range(40):
        await gate.store.put(
            PendingAction(
                tool="send_message",
                arguments={"to": f"x{i}"},
                risk=R3,
                summary=f"Send {i}",
                scope=f"owner:other{i}",
            )
        )
    mine = PendingAction(
        tool="send_message", arguments={"to": "a"}, risk=R3, summary="Send a", scope="owner:me"
    )
    reads = docs.reads
    with pytest.raises(ConfirmationRequired):
        await gate.check(mine)
    assert docs.reads - reads <= 2  # not the 40 other cards
    same = mine.model_copy(update={"id": "other_id"})
    with pytest.raises(ConfirmationRequired) as e:
        await gate.check(same)
    assert e.value.action.id == mine.id  # still de-duplicated
    assert len(await gate.pending()) == 41


# ---- L5: document tool calls per owner message ---------------------------------------------


class DocRig:
    def __init__(self, settings: Settings) -> None:
        self.provider = MockProvider(name="p")
        brains = BrainRegistry(
            [
                BrainSpec(
                    id="c", label="C", provider=self.provider, tiers={t: "p" for t in ModelTier}
                )
            ],
            default_id="c",
        )
        self.docs = DocumentService(AttachmentStore(MemoryDocs()))
        reg = ToolRegistry()
        for t in document_tools(self.docs):
            reg.register(t)
        self.gateway = Gateway(
            registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()
        )
        self.brain = Brain(
            brains=brains,
            store=InMemorySessionStore(),
            settings=settings,
            gateway=self.gateway,
            documents=self.docs,
        )


async def test_one_message_makes_at_most_six_document_calls(settings: Settings) -> None:
    rig = DocRig(settings)
    aid = (await rig.docs.upload("owner", "Lease.pdf", make_pdf(["Rent is due on the 5th."]))).id
    calls = [
        ToolCall(id=f"d{i}", name="doc_search", arguments={"doc_id": aid, "query": f"rent {i}"})
        for i in range(MAX_DOC_CALLS + 2)
    ]
    rig.provider.script_tool_calls(calls, "On the 5th, Sir.")
    resp = await rig.brain.chat(ChatRequest(message="rent?", attachments=[aid]))
    results = [
        b.content
        for b in rig.provider.calls[-1].messages[-1].content  # type: ignore[union-attr]
        if hasattr(b, "content")
    ]
    over = [r for r in results if "document limit for this request reached" in r.lower()]
    assert len(results) == MAX_DOC_CALLS + 2 and len(over) == 2
    # a new owner message: a fresh allowance
    rig.provider.script_tool_calls(calls[:1], "Still the 5th.")
    await rig.brain.chat(ChatRequest(message="sure?", session_id=resp.session_id))
    last = rig.provider.calls[-1].messages[-1].content
    assert "limit" not in str(last).lower()


def test_one_messages_document_calls_never_evict_each_other() -> None:
    assert CACHE_DOCS >= MAX_DOC_CALLS
