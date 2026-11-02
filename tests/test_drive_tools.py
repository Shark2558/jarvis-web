# tests/test_drive_tools.py — slice 12 D1/D10: drive_folders / drive_list / drive_search /
# drive_read are R1 tools behind the gateway: arguments checked first, output fenced, untrusted
# (the round is tainted, so a write after them becomes a card), never vouched for, ≤ 6 per owner
# message; registered only when Drive is configured, and never offered to a training brain.
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from drive_fakes import FakeDrive, StaticTokens

import jarvis.drive.tools as tools_mod
from jarvis.config import get_settings
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.drive.client import DriveClient
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.drive.tools import DRIVE_TOOL_DEADLINE_S, DRIVE_TOOLS, MAX_DRIVE_CALLS, drive_tools
from jarvis.llm.base import ToolCall, ToolResultBlock
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.budget import turn_budget
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.setup import build_gateway
from jarvis.tools.taint import result_trusted

OWNER = "akash@example.com"
UID = "u_owner"
SCOPE = f"{UID}:s1"


class Tokens(StaticTokens):
    async def email(self) -> str:
        return "jarvis-run@proj-123.iam.gserviceaccount.com"


async def _rig() -> tuple[Gateway, DriveService, FakeDrive]:
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER)
    d.file("doc1", "Steering notes", "root1", "Budget is four crore.")
    d.folder("root2", "Personal", shared_by=OWNER)
    d.file("p1", "Diary", "root2", "private words")
    files = DocumentService(AttachmentStore(MemoryDocs()))
    svc = DriveService(
        DriveClient(Tokens(), http=d.client()), RootsStore(MemoryDocs()), extract=files.extract
    )
    await svc.set_use(UID, OWNER, "root1", True)
    reg = ToolRegistry()
    for t in drive_tools(svc):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    return gw, svc, d


def _out(result: object) -> dict:  # type: ignore[type-arg]
    return json.loads(json.dumps(result, default=str))


async def test_four_read_only_untrusted_tools_that_never_vouch() -> None:
    gw, _, _ = await _rig()
    assert {s.name for s in gw.registry.specs()} == set(DRIVE_TOOLS)
    for name in DRIVE_TOOLS:
        tool = gw.registry.get(name)
        assert tool is not None and tool.risk is ActionRisk.READ_ONLY
        assert tool.trusted_output is False and tool.may_vouch is False
        assert tool.agent == "drive" and name.startswith("drive_")


async def test_drive_read_runs_fenced_and_audited() -> None:
    gw, _, _ = await _rig()
    gr = await gw.execute(
        ToolCall(id="c1", name="drive_read", arguments={"file": "doc1"}), scope=SCOPE
    )
    assert gr.outcome is GatewayOutcome.EXECUTED
    out = _out(gr.result)
    assert out["text"].startswith(FENCE_PREFIX) and "Budget is four crore." in out["text"]
    assert FENCE_PREFIX in out["name"]
    assert len(gr.for_model()) < 12_000 and "[truncated]" not in gr.for_model()
    tail = await gw.audit.tail(5)
    assert [(e.tool, e.outcome) for e in tail.entries] == [("drive_read", "executed")]


async def test_a_drive_result_taints_the_round() -> None:
    gw, _, _ = await _rig()
    gr = await gw.execute(ToolCall(id="c1", name="drive_folders", arguments={}), scope=SCOPE)
    block: ToolResultBlock = gr.block("c1")
    assert block.trusted is False
    assert result_trusted(block, gw.registry.get("drive_folders")) is False


async def test_outside_the_chosen_folders_is_a_plain_refusal() -> None:
    gw, _, d = await _rig()
    gr = await gw.execute(
        ToolCall(id="c", name="drive_read", arguments={"file": "p1"}), scope=SCOPE
    )
    assert gr.outcome is GatewayOutcome.ERROR
    assert "Not in your chosen folders" in gr.for_model() and "private words" not in gr.for_model()
    assert not [r for r in d.requests if "/p1/export" in r.url.path]


async def test_list_search_and_folders_through_the_gateway() -> None:
    gw, _, _ = await _rig()
    for name, args in (
        ("drive_folders", {}),
        ("drive_list", {"folder": "root1"}),
        ("drive_search", {"query": "budget"}),
    ):
        gr = await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)
        assert gr.outcome is GatewayOutcome.EXECUTED, (name, gr.for_model())
    found = _out(gr.result)
    assert [r["id"] for r in found["results"]] == ["doc1"]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("drive_read", {}),
        ("drive_read", {"file": "../etc/passwd"}),
        ("drive_read", {"file": "doc1", "part": 0}),
        ("drive_read", {"file": "doc1", "part": "2"}),
        ("drive_read", {"file": "doc1", "part": True}),
        ("drive_list", {"folder": "a b"}),
        ("drive_list", {"folder": "root1", "page": 5}),
        ("drive_list", {"folder": "root1", "page": "x" * 3000}),
        ("drive_search", {"query": ""}),
        ("drive_search", {"query": "   "}),
        ("drive_search", {"query": "x" * 201}),
        ("drive_search", {"query": 7}),
        ("drive_folders", {"extra": 1}),
    ],
)
async def test_arguments_are_checked_before_anything_runs(name: str, args: dict) -> None:  # type: ignore[type-arg]
    gw, _, d = await _rig()
    before = len(d.requests)
    gr = await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)
    assert gr.outcome is GatewayOutcome.ERROR
    assert len(d.requests) == before


async def test_at_most_six_drive_calls_per_owner_message() -> None:
    gw, _, _ = await _rig()
    with turn_budget():
        outcomes = [
            (
                await gw.execute(
                    ToolCall(id=f"c{i}", name="drive_folders", arguments={}), scope=SCOPE
                )
            ).outcome
            for i in range(MAX_DRIVE_CALLS + 1)
        ]
    assert outcomes[:MAX_DRIVE_CALLS] == [GatewayOutcome.EXECUTED] * MAX_DRIVE_CALLS
    assert outcomes[-1] is GatewayOutcome.ERROR
    with turn_budget():  # a new owner message starts again
        gr = await gw.execute(ToolCall(id="n", name="drive_folders", arguments={}), scope=SCOPE)
        assert gr.outcome is GatewayOutcome.EXECUTED


async def test_the_cap_message_is_plain() -> None:
    gw, _, _ = await _rig()
    with turn_budget():
        for i in range(MAX_DRIVE_CALLS):
            await gw.execute(ToolCall(id=f"c{i}", name="drive_folders", arguments={}), scope=SCOPE)
        gr = await gw.execute(ToolCall(id="x", name="drive_folders", arguments={}), scope=SCOPE)
    assert "Drive limit" in gr.for_model()


async def test_no_owner_context_runs_nothing() -> None:
    gw, _, d = await _rig()
    before = len(d.requests)
    gr = await gw.execute(ToolCall(id="c", name="drive_read", arguments={"file": "doc1"}))
    assert gr.outcome is GatewayOutcome.ERROR and len(d.requests) == before


def test_every_drive_call_has_an_overall_deadline() -> None:
    assert DRIVE_TOOL_DEADLINE_S == 45


@pytest.mark.parametrize(
    ("name", "args", "method"),
    [
        ("drive_folders", {}, "folders"),
        ("drive_list", {"folder": "root1"}, "list_folder"),
        ("drive_search", {"query": "budget"}, "search"),
        ("drive_read", {"file": "doc1"}, "read"),
    ],
)
async def test_a_drive_call_past_its_deadline_says_so_plainly(
    name: str, args: dict[str, Any], method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    gw, svc, _ = await _rig()

    async def hang(*_: Any, **__: Any) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr(svc, method, hang)
    monkeypatch.setattr(tools_mod, "DRIVE_TOOL_DEADLINE_S", 0.05)
    gr = await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)
    assert gr.outcome is GatewayOutcome.ERROR
    assert "Drive took too long" in gr.for_model()


async def test_drive_read_says_sheets_give_their_first_sheet() -> None:
    gw, _, _ = await _rig()
    tool = gw.registry.get("drive_read")
    assert tool is not None and "first sheet" in tool.description


async def test_registered_only_when_drive_is_configured() -> None:
    _, svc, _ = await _rig()
    s = get_settings()
    without = build_gateway(s)
    assert not [n for n in (x.name for x in without.registry.specs()) if n.startswith("drive_")]
    with_drive = build_gateway(s, drive=svc)
    assert {
        n for n in (x.name for x in with_drive.registry.specs()) if n.startswith("drive_")
    } == set(DRIVE_TOOLS)
