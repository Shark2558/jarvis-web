# tests/test_persistence_api.py — slice 5: state survives a cold start (written test-first).
# Two app instances share one MemoryDocs: the second one is "JARVIS after scale-to-zero".
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from jarvis.api import create_app
from jarvis.config import SessionBackend, Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.storage import Storage, doc_storage
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.builtin import InMemoryWorld, builtin_tools
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry


def _gateway(storage: Storage, world: InMemoryWorld) -> Gateway:
    reg = ToolRegistry()
    for t in builtin_tools(world):
        reg.register(t)
    return Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(storage.approvals),
        audit=storage.audit,
    )


@pytest.fixture
def boot(
    settings: Settings, provider: MockProvider, world: InMemoryWorld
) -> Callable[[MemoryDocs], AsyncIterator[AsyncClient]]:
    @asynccontextmanager
    async def _boot(docs: MemoryDocs) -> AsyncIterator[AsyncClient]:
        storage = doc_storage(docs, prefix="jarvis_")
        app = create_app(
            settings,
            provider=provider,
            store=storage.sessions,
            gateway=_gateway(storage, world),
        )
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                yield c

    return _boot  # type: ignore[return-value]


async def test_conversation_survives_cold_start(boot, provider: MockProvider) -> None:  # type: ignore[no-untyped-def]
    docs = MemoryDocs()
    provider.script("Good morning, Sir.")
    async with boot(docs) as c1:
        r = await c1.post("/v1/chat", json={"message": "Hi Jarvis"})
        sid = r.json()["session_id"]
    provider.script("You said hi earlier, Sir.")
    async with boot(docs) as c2:  # new process, same database
        listed = (await c2.get("/v1/sessions")).json()
        assert [x["id"] for x in listed] == [sid] and listed[0]["title"] == "Hi Jarvis"
        t = (await c2.get(f"/v1/sessions/{sid}")).json()
        assert [x["content"] for x in t["turns"]] == ["Hi Jarvis", "Good morning, Sir."]
        r2 = await c2.post("/v1/chat", json={"message": "What did I say?", "session_id": sid})
        assert r2.status_code == 200 and r2.json()["turn_count"] == 4
        # the model saw the earlier exchange
        assert any("Hi Jarvis" in str(m.content) for m in provider.calls[-1].messages)


async def test_pending_approval_survives_cold_start(  # type: ignore[no-untyped-def]
    boot, provider: MockProvider, world: InMemoryWorld
) -> None:
    docs = MemoryDocs()
    provider.script_tool_calls(
        [ToolCall(id="s1", name="send_message", arguments={"to": "priya@x.com", "body": "3pm"})],
        "Awaiting your approval, Sir.",
    )
    async with boot(docs) as c1:
        body = (await c1.post("/v1/chat", json={"message": "tell priya 3pm"})).json()
        pid, sid = body["pending_approvals"][0]["id"], body["session_id"]
        assert body["pending_approvals"][0]["session_id"] == sid
    assert world.sent == []
    provider.script("Sent, Sir.")
    async with boot(docs) as c2:
        pending = (await c2.get("/v1/approvals")).json()
        assert [p["id"] for p in pending] == [pid] and pending[0]["session_id"] == sid
        r = await c2.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid})
        assert r.status_code == 200
        assert world.sent == [{"to": "priya@x.com", "body": "3pm"}]
        # single use, even across restarts
        again = await c2.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid})
        assert again.status_code == 404 and len(world.sent) == 1
        audit = (await c2.get("/v1/audit?limit=10")).json()
        assert audit["verified"] is True
        assert [e["outcome"] for e in audit["entries"]] == [
            "awaiting_confirmation",
            "executing",
            "executed",
        ]


async def test_decline_after_approve_is_rejected(  # type: ignore[no-untyped-def]
    boot, provider: MockProvider, world: InMemoryWorld
) -> None:
    docs = MemoryDocs()
    provider.script_tool_calls(
        [ToolCall(id="s2", name="send_message", arguments={"to": "a@x.com", "body": "b"})], "ok"
    )
    async with boot(docs) as c:
        body = (await c.post("/v1/chat", json={"message": "send"})).json()
        pid, sid = body["pending_approvals"][0]["id"], body["session_id"]
        provider.script("Sent.")
        assert (
            await c.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid})
        ).status_code == 200
        r = await c.post(f"/v1/approvals/{pid}/decline", json={"session_id": sid})
        assert r.status_code == 404
        outcomes = [e["outcome"] for e in (await c.get("/v1/audit")).json()["entries"]]
        assert "declined" not in outcomes


async def test_delete_conversation_is_permanent(boot, provider: MockProvider) -> None:  # type: ignore[no-untyped-def]
    docs = MemoryDocs()
    provider.script("Hello.")
    async with boot(docs) as c1:
        sid = (await c1.post("/v1/chat", json={"message": "hi"})).json()["session_id"]
        assert (await c1.delete(f"/v1/sessions/{sid}")).status_code == 204
    async with boot(docs) as c2:
        assert (await c2.get(f"/v1/sessions/{sid}")).status_code == 404
        assert (await c2.get("/v1/sessions")).json() == []


def test_firestore_backend_settings_parse() -> None:
    s = Settings(
        _env_file=None,
        session_backend="firestore",
        firestore_project="smooth-tesla-513320-v5",
    )
    assert s.session_backend is SessionBackend.FIRESTORE
    assert s.firestore_database == "(default)" and s.firestore_prefix == "jarvis_"
