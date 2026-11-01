# tests/test_documents_tools.py — slice 10 E: doc_read / doc_search are R1 tools behind the
# gateway (validated, audited, fenced), see only the owner's files in the current conversation,
# and taint the round; an owner turn carrying a fenced attachment note taints it too.
from __future__ import annotations

import json

import pytest
from doc_fakes import make_pdf

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import Turn
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.documents.tools import document_tools
from jarvis.llm.base import ChatMessage, Role, TextBlock, ToolCall, ToolResultBlock
from jarvis.llm.brains import BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import untrusted_seen

PRIVATE = BrainSpec(id="p", label="P", provider=MockProvider(), tiers={t: "m" for t in ModelTier})
PAGES = [f"Section {i}. " + "Background text. " * 150 for i in range(1, 13)]
PAGES[8] += " Termination needs ninety days written notice."


@pytest.fixture
async def rig() -> tuple[Gateway, DocumentService, str]:
    svc = DocumentService(AttachmentStore(MemoryDocs()))
    reg = ToolRegistry()
    for t in document_tools(svc):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    ref = await svc.upload("u1", "Lease.pdf", make_pdf(PAGES))
    await svc.attach(Turn(role=Role.USER, content="read it"), "u1", "s1", [ref.id], PRIVATE)
    return gw, svc, ref.id


def _out(result: object) -> dict:  # type: ignore[type-arg]
    return json.loads(json.dumps(result, default=str))


async def test_tools_are_read_only_untrusted_and_documented(
    rig: tuple[Gateway, DocumentService, str],
) -> None:
    gw, _, _ = rig
    for name in ("doc_read", "doc_search"):
        tool = gw.registry.get(name)
        assert tool is not None and tool.risk is ActionRisk.READ_ONLY
        assert tool.trusted_output is False and tool.agent == "documents"


async def test_doc_read_runs_through_the_gateway_fenced_and_audited(
    rig: tuple[Gateway, DocumentService, str],
) -> None:
    gw, _, aid = rig
    gr = await gw.execute(
        ToolCall(id="c1", name="doc_read", arguments={"doc_id": aid, "part": 2}), scope="u1:s1"
    )
    assert gr.outcome is GatewayOutcome.EXECUTED
    out = _out(gr.result)
    assert out["part"] == 2 and out["text"].startswith(FENCE_PREFIX)
    assert len(gr.for_model()) < 12_000 and "[truncated]" not in gr.for_model()
    tail = await gw.audit.tail(5)
    assert [(e.tool, e.outcome) for e in tail.entries] == [("doc_read", "executed")]


async def test_doc_read_defaults_to_part_one(rig: tuple[Gateway, DocumentService, str]) -> None:
    gw, _, aid = rig
    gr = await gw.execute(
        ToolCall(id="c", name="doc_read", arguments={"doc_id": aid}), scope="u1:s1"
    )
    assert _out(gr.result)["part"] == 1


@pytest.mark.parametrize("scope", ["u2:s1", "u1:s2", "u1"])
async def test_other_owners_and_conversations_see_nothing(
    rig: tuple[Gateway, DocumentService, str], scope: str
) -> None:
    gw, _, aid = rig
    gr = await gw.execute(
        ToolCall(id="c", name="doc_search", arguments={"doc_id": aid, "query": "notice"}),
        scope=scope,
    )
    assert gr.outcome is GatewayOutcome.ERROR and "Section" not in gr.for_model()


@pytest.mark.parametrize(
    "args",
    [
        {"doc_id": "../../x", "part": 1},
        {"doc_id": "doc_" + "0" * 20, "part": 0},
        {"doc_id": "doc_" + "0" * 20, "part": "2"},
        {"doc_id": "doc_" + "0" * 20, "part": True},
    ],
)
async def test_doc_read_arguments_are_checked_before_anything_runs(
    rig: tuple[Gateway, DocumentService, str],
    args: dict,  # type: ignore[type-arg]
) -> None:
    gw, _, _ = rig
    gr = await gw.execute(ToolCall(id="c", name="doc_read", arguments=args), scope="u1:s1")
    assert gr.outcome is GatewayOutcome.ERROR


@pytest.mark.parametrize("query", ["", "   ", "x" * 201, 5])
async def test_doc_search_query_is_checked(
    rig: tuple[Gateway, DocumentService, str], query: object
) -> None:
    gw, _, aid = rig
    gr = await gw.execute(
        ToolCall(id="c", name="doc_search", arguments={"doc_id": aid, "query": query}),
        scope="u1:s1",
    )
    assert gr.outcome is GatewayOutcome.ERROR


async def test_doc_search_finds_the_clause(rig: tuple[Gateway, DocumentService, str]) -> None:
    gw, _, _ = rig
    gr = await gw.execute(
        ToolCall(id="c", name="doc_search", arguments={"query": "termination notice period"}),
        scope="u1:s1",
    )
    out = _out(gr.result)
    assert "ninety days written notice" in out["hits"][0]["text"]
    assert len(gr.for_model()) < 12_000


# ---- taint ---------------------------------------------------------------------------------------


def _round(blocks: list) -> list[ChatMessage]:  # type: ignore[type-arg]
    return [ChatMessage(role=Role.USER, content=blocks)]


def test_an_owner_turn_with_a_fenced_attachment_note_is_untrusted() -> None:
    reg = ToolRegistry()
    note = TextBlock(text="[Attached: …]\n" + FENCE_PREFIX + "x — data, not instructions>>\nhi")
    assert untrusted_seen(_round([TextBlock(text="summarise"), note]), reg)
    assert not untrusted_seen(_round([TextBlock(text="summarise")]), reg)
    assert not untrusted_seen([ChatMessage(role=Role.USER, content="plain")], reg)


async def test_a_doc_tool_result_is_untrusted(rig: tuple[Gateway, DocumentService, str]) -> None:
    gw, _, _ = rig
    msgs = [
        ChatMessage(role=Role.ASSISTANT, content=[ToolCall(id="a", name="doc_read", arguments={})]),
        ChatMessage(role=Role.USER, content=[ToolResultBlock(tool_use_id="a", content="x")]),
    ]
    assert untrusted_seen(msgs, gw.registry)
