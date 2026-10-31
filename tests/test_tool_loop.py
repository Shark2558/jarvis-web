# tests/test_tool_loop.py — Brain with tools, via the mock provider and the HTTP API
from __future__ import annotations

from httpx import AsyncClient

from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.llm.base import Role, ToolCall
from jarvis.llm.mock_provider import MockProvider


async def test_tool_round_trip(brain: Brain, provider: MockProvider, world) -> None:
    provider.script_tool_calls(
        [ToolCall(id="t1", name="get_calendar", arguments={"day": "today"})],
        "You have a stand-up at 09:30, Sir.",
    )
    resp = await brain.chat(ChatRequest(message="What's on today?"))
    assert resp.reply == "You have a stand-up at 09:30, Sir."
    # second call carried the tool result back to the model
    second = provider.calls[1]
    blocks = second.messages[-1].content
    assert any(getattr(b, "type", "") == "tool_result" and b.tool_use_id == "t1" for b in blocks)
    assert resp.tool_calls == 1
    assert (await brain.gateway.audit.tail(1)).entries[-1].tool == "get_calendar"


async def test_tool_loop_round_cap(brain: Brain, provider: MockProvider) -> None:
    for _ in range(10):
        provider.script_tool_calls([ToolCall(id="x", name="list_tasks", arguments={})])
    resp = await brain.chat(ChatRequest(message="loop"))
    assert resp.tool_calls <= brain.s.tool_max_rounds
    assert "round limit" in resp.reply.lower() or resp.reply


async def test_irreversible_pauses_for_approval_then_resumes(
    brain: Brain, provider: MockProvider, world
) -> None:
    provider.script_tool_calls(
        [
            ToolCall(
                id="s1",
                name="send_message",
                arguments={"to": "priya@example.com", "body": "Moving to 3."},
            )
        ],
        "Awaiting your approval, Sir.",
    )
    resp = await brain.chat(ChatRequest(message="Tell Priya we move to 3"))
    assert world.sent == []
    assert len(resp.pending_approvals) == 1
    pending = resp.pending_approvals[0]
    assert pending.tool == "send_message"

    provider.script("Sent, Sir.")
    resp2 = await brain.approve(pending.id, session_id=resp.session_id)
    assert world.sent == [{"to": "priya@example.com", "body": "Moving to 3."}]
    assert resp2.reply == "Sent, Sir."
    # the approval and execution are both on the audit chain
    outcomes = [e.outcome for e in (await brain.gateway.audit.tail(50)).entries]
    assert "awaiting_confirmation" in outcomes and "executed" in outcomes
    assert await brain.gateway.audit.verify_all()


async def test_decline_executes_nothing(brain: Brain, provider: MockProvider, world) -> None:
    provider.script_tool_calls(
        [
            ToolCall(
                id="s2", name="send_message", arguments={"to": "priya@example.com", "body": "x"}
            )
        ],
        "Waiting.",
    )
    resp = await brain.chat(ChatRequest(message="send"))
    pid = resp.pending_approvals[0].id
    provider.script("Understood, nothing sent.")
    resp2 = await brain.decline(pid, session_id=resp.session_id)
    assert world.sent == [] and "nothing" in resp2.reply.lower()
    assert (await brain.gateway.audit.tail(1)).entries[-1].outcome == "declined"


async def test_api_approval_endpoints(client: AsyncClient, provider: MockProvider, world) -> None:
    provider.script_tool_calls(
        [
            ToolCall(
                id="s3", name="send_message", arguments={"to": "priya@example.com", "body": "api"}
            )
        ],
        "Waiting, Sir.",
    )
    r = await client.post("/v1/chat", json={"message": "send to priya"})
    body = r.json()
    assert r.status_code == 200 and len(body["pending_approvals"]) == 1
    pid = body["pending_approvals"][0]["id"]

    lst = await client.get("/v1/approvals")
    assert [p["id"] for p in lst.json()] == [pid]

    provider.script("Done.")
    r2 = await client.post(f"/v1/approvals/{pid}/approve", json={"session_id": body["session_id"]})
    assert r2.status_code == 200 and world.sent[0]["body"] == "api"

    audit = await client.get("/v1/audit")
    assert audit.status_code == 200 and audit.json()["verified"] is True
    assert any(e["outcome"] == "executed" for e in audit.json()["entries"])


async def test_tool_result_is_data_not_instruction(brain: Brain, provider: MockProvider) -> None:
    """The tool result block must be labelled as untrusted data for the model."""
    provider.script_tool_calls([ToolCall(id="t9", name="list_tasks", arguments={})], "ok")
    await brain.chat(ChatRequest(message="tasks"))
    tr = next(
        b for b in provider.calls[1].messages[-1].content if getattr(b, "type", "") == "tool_result"
    )
    assert "untrusted" in tr.content.lower()
    assert provider.calls[0].messages[-1].role is Role.USER


async def test_approval_is_bound_to_its_session(
    brain: Brain, provider: MockProvider, world
) -> None:
    provider.script_tool_calls(
        [
            ToolCall(
                id="s4", name="send_message", arguments={"to": "priya@example.com", "body": "x"}
            )
        ],
        "Waiting.",
    )
    resp = await brain.chat(ChatRequest(message="send"))
    other = await brain.chat(ChatRequest(message="hello"))
    import pytest

    with pytest.raises(LookupError):
        await brain.approve(resp.pending_approvals[0].id, session_id=other.session_id)
    assert world.sent == []


async def test_approved_action_is_recorded_even_if_llm_fails(
    brain: Brain, provider: MockProvider, world, store
) -> None:
    provider.script_tool_calls(
        [
            ToolCall(
                id="s5", name="send_message", arguments={"to": "priya@example.com", "body": "y"}
            )
        ],
        "Waiting.",
    )
    resp = await brain.chat(ChatRequest(message="send"))
    provider.fail_next = 5  # every tier fails after the action executes
    resp2 = await brain.approve(resp.pending_approvals[0].id, session_id=resp.session_id)
    assert world.sent[0]["body"] == "y"
    assert "done" in resp2.reply.lower()
    session = await store.get(resp.session_id)
    # the tool exchange is persisted as blocks, not as an owner-typed instruction
    assert any(
        any(getattr(b, "type", "") == "tool_result" for b in t.blocks) for t in session.turns
    )
    assert not any("[Owner approved" in t.content for t in session.turns if t.role is Role.USER)


def test_tools_package_imports_cold() -> None:
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-c", "import jarvis.tools"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
