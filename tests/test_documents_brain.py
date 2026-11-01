# tests/test_documents_brain.py — slice 10 E in the core loop: a message with attachments carries
# the fenced note as a second block, the round is tainted from the first call, the doc tools are
# offered, a training brain never gets a file (refused up front, no empty conversation, never in
# its window later), streaming works too, and deleting the conversation deletes its files.
from __future__ import annotations

from typing import Any

import pytest
from doc_fakes import make_pdf

from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, InputRejected
from jarvis.core.models import ChatRequest
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.documents.tools import document_tools
from jarvis.llm.base import TextBlock, ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.taint import untrusted_in_context

UID = "owner"


class Rig:
    def __init__(self, settings: Settings) -> None:
        self.private, self.training = MockProvider(name="p"), MockProvider(name="t")
        brains = BrainRegistry(
            [
                BrainSpec(
                    id="claude", label="C", provider=self.private, tiers={t: "p" for t in ModelTier}
                ),
                BrainSpec(
                    id="free",
                    label="F",
                    provider=self.training,
                    tiers={t: "t" for t in ModelTier},
                    trains_on_content=True,
                ),
            ],
            default_id="claude",
        )
        self.docs = DocumentService(AttachmentStore(MemoryDocs()))
        self.trust: list[bool] = []
        reg = ToolRegistry()
        for t in document_tools(self.docs):
            reg.register(t)
        reg.register(
            Tool(
                "probe",
                "records whether the round counts as untrusted",
                {"type": "object", "properties": {}},
                ActionRisk.READ_ONLY,
                lambda _: self.trust.append(untrusted_in_context()) or {"ok": True},
            )
        )
        self.gateway = Gateway(
            registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()
        )
        self.store = InMemorySessionStore()
        self.brain = Brain(
            brains=brains,
            store=self.store,
            settings=settings,
            gateway=self.gateway,
            documents=self.docs,
        )

    async def upload(self, text: str = "Clause 7: rent is due on the 5th.") -> str:
        return (await self.docs.upload(UID, "Lease.pdf", make_pdf([text]))).id


@pytest.fixture
def rig(settings: Settings) -> Rig:
    return Rig(settings)


def _last_user_blocks(p: MockProvider) -> list[Any]:
    content = p.calls[-1].messages[-1].content
    assert isinstance(content, list)
    return content


async def test_a_message_with_a_file_carries_the_fenced_note(rig: Rig) -> None:
    aid = await rig.upload()
    resp = await rig.brain.chat(ChatRequest(message="When is rent due?", attachments=[aid]))
    blocks = _last_user_blocks(rig.private)
    assert isinstance(blocks[0], TextBlock) and blocks[0].text == "When is rent due?"
    assert isinstance(blocks[1], TextBlock) and blocks[1].text.startswith("[Attached: “Lease.pdf”")
    assert FENCE_PREFIX in blocks[1].text and "rent is due on the 5th" in blocks[1].text
    tools = {t.name for t in rig.private.calls[-1].tools or []}
    assert {"doc_read", "doc_search"} <= tools
    session = await rig.store.get(resp.session_id)
    assert session is not None
    owner = session.turns[0]
    assert owner.content == "When is rent due?" and [a.id for a in owner.attachments] == [aid]
    assert session.metadata.get("brain") == "claude"


async def test_the_first_round_after_an_attachment_is_untrusted(rig: Rig) -> None:
    aid = await rig.upload()
    rig.private.script_tool_calls([ToolCall(id="c1", name="probe")], "ok")
    await rig.brain.chat(ChatRequest(message="look", attachments=[aid]))
    rig.private.script_tool_calls([ToolCall(id="c2", name="probe")], "ok")
    await rig.brain.chat(ChatRequest(message="plain message"))  # a fresh conversation
    assert rig.trust == [True, False]


async def test_a_training_brain_is_refused_before_any_conversation_exists(rig: Rig) -> None:
    aid = await rig.upload()
    with pytest.raises(InputRejected, match="never shared"):
        await rig.brain.chat(ChatRequest(message="hi", attachments=[aid], brain="free"))
    assert await rig.store.list_for_user(UID) == []
    assert rig.training.calls == []
    still = await rig.docs.store.get(aid)
    assert still is not None and still.waiting  # the owner can switch brain and send again


async def test_an_unknown_attachment_leaves_no_empty_conversation(rig: Rig) -> None:
    with pytest.raises(InputRejected, match="no longer available"):
        await rig.brain.chat(ChatRequest(message="hi", attachments=["doc_" + "1" * 20]))
    assert await rig.store.list_for_user(UID) == []


async def test_switching_to_a_training_brain_later_never_sends_the_file(rig: Rig) -> None:
    aid = await rig.upload("TOP-SECRET-TERMS")
    r = await rig.brain.chat(ChatRequest(message="read this", attachments=[aid]))
    await rig.brain.chat(ChatRequest(message="and now?", session_id=r.session_id, brain="free"))
    sent = rig.training.calls[-1].messages
    assert all("TOP-SECRET-TERMS" not in m.text() for m in sent)
    assert rig.training.calls[-1].tools is None


async def test_attaching_in_an_existing_training_conversation_is_refused(rig: Rig) -> None:
    r = await rig.brain.chat(ChatRequest(message="hello", brain="free"))
    aid = await rig.upload()
    with pytest.raises(InputRejected, match="never shared"):
        await rig.brain.chat(
            ChatRequest(message="read", session_id=r.session_id, attachments=[aid])
        )
    session = await rig.store.get(r.session_id)
    assert session is not None and len(session.turns) == 2  # nothing stored


async def test_streaming_with_a_file_keeps_the_note_and_the_refs(rig: Rig) -> None:
    aid = await rig.upload()
    rig.private.script("Rent is due on the 5th.")
    chunks = [
        c async for c in rig.brain.chat_stream(ChatRequest(message="when?", attachments=[aid]))
    ]
    assert "".join(chunks).strip() == "Rent is due on the 5th."
    blocks = _last_user_blocks(rig.private)
    assert len(blocks) == 2 and FENCE_PREFIX in blocks[1].text
    (summary,) = await rig.store.list_for_user(UID)
    session = await rig.store.get(summary.id)
    assert session is not None and session.turns[0].attachments[0].id == aid


async def test_deleting_the_conversation_deletes_its_files(rig: Rig) -> None:
    aid = await rig.upload()
    r = await rig.brain.chat(ChatRequest(message="read", attachments=[aid]))
    att = await rig.docs.store.get(aid)
    assert att is not None
    assert await rig.brain.forget(r.session_id, user_id=UID)
    assert await rig.docs.store.get(aid) is None
    assert await rig.docs.store.chunks(att) == []


async def test_without_a_document_service_attachments_are_refused(settings: Settings) -> None:
    brain = Brain(
        router=Rig(settings).brain.router, store=InMemorySessionStore(), settings=settings
    )
    with pytest.raises(InputRejected, match="not available"):
        await brain.chat(ChatRequest(message="hi", attachments=["doc_" + "1" * 20]))
