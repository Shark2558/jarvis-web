# tests/test_approval_conflict.py — slice 10 review M1 + L5: a conversation that changed in another
# window never loses the record of an approved / declined action, and the 409 says truthfully
# whether the owner's message was kept.
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest, Session, Turn
from jarvis.llm.base import Role, ToolCall, ToolResultBlock
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.base import MessageNotSaved, SessionConflict
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools.builtin import InMemoryWorld
from jarvis.tools.gateway import Gateway

PHONE = "from the phone"


class RacingStore(InMemorySessionStore):
    """Refuses saves like DocSessionStore when another window wrote first. `refuse` saves fail
    after `allow` more succeed; before the first refusal the other window adds a message."""

    def __init__(self) -> None:
        super().__init__(ttl_s=3600)
        self.allow = 0
        self.refuse = 0
        self.saves = 0

    async def save(self, session: Session) -> None:
        self.saves += 1
        if self.refuse and self.allow <= 0:
            self.refuse -= 1
            stored = await self.get(session.id)
            if stored is not None and not any(t.content == PHONE for t in stored.turns):
                stored.append(Turn(role=Role.USER, content=PHONE))
                await super().save(stored)
            raise SessionConflict("changed in another window")
        self.allow -= 1
        await super().save(session)


def _brain(settings: Settings, provider: MockProvider, store: RacingStore, gw: Gateway) -> Brain:
    tiers = {
        ModelTier.FAST: settings.model_fast,
        ModelTier.BALANCED: settings.model_balanced,
        ModelTier.STRONG: settings.model_strong,
    }
    return Brain(router=ModelRouter(provider, tiers), store=store, settings=settings, gateway=gw)


async def _proposal(brain: Brain, provider: MockProvider) -> tuple[str, str]:
    args = {"to": "priya@example.com", "body": "3pm"}
    provider.script_tool_calls(
        [ToolCall(id="s1", name="send_message", arguments=args)], "Awaiting your approval, Sir."
    )
    resp = await brain.chat(ChatRequest(message="Tell Priya 3pm"))
    return resp.pending_approvals[0].id, resp.session_id


def _decided(b: object) -> bool:
    if isinstance(b, ToolCall):
        return b.id.startswith("approve_")
    return isinstance(b, ToolResultBlock) and b.tool_use_id.startswith("approve_")


def _exchange(s: Session) -> tuple[list[Turn], list[Turn]]:
    """The decided action's tool_use turns and tool_result turns."""
    turns = [t for t in s.turns if any(_decided(b) for b in t.blocks)]
    uses = [t for t in turns if t.role is Role.ASSISTANT]
    return uses, [t for t in turns if t.role is Role.USER]


@pytest.mark.parametrize("approved", [True, False])
@pytest.mark.parametrize("allow", [0, 1])  # the exchange's save, or the narration's, is refused
async def test_a_decision_is_recorded_on_the_newer_conversation(
    settings: Settings,
    provider: MockProvider,
    gateway: Gateway,
    world: InMemoryWorld,
    approved: bool,
    allow: int,
) -> None:
    store = RacingStore()
    brain = _brain(settings, provider, store, gateway)
    pid, sid = await _proposal(brain, provider)
    store.allow, store.refuse = allow, 1
    provider.script("Sent, Sir." if approved else "Understood, nothing sent.")
    decide = brain.approve if approved else brain.decline
    resp = await decide(pid, session_id=sid)
    assert world.sent == ([{"to": "priya@example.com", "body": "3pm"}] if approved else [])
    assert "could not record" not in resp.reply  # it was recorded
    s = await store.get(sid)
    assert s is not None
    contents = [t.content for t in s.turns]
    assert PHONE in contents  # the other window's message survived
    uses, results = _exchange(s)
    assert len(uses) == 1 and len(results) == 1  # the exchange is stored exactly once
    assert s.turns[-1].content == resp.reply and s.turns[-1].tool_derived
    assert s.turns.index(uses[0]) < s.turns.index(results[0]) < len(s.turns) - 1


@pytest.mark.parametrize("approved", [True, False])
async def test_a_decision_that_cannot_be_recorded_says_so(
    settings: Settings,
    provider: MockProvider,
    gateway: Gateway,
    world: InMemoryWorld,
    approved: bool,
) -> None:
    store = RacingStore()
    brain = _brain(settings, provider, store, gateway)
    pid, sid = await _proposal(brain, provider)
    store.refuse = 99  # every save from now on loses the race
    provider.script("Sent, Sir." if approved else "Understood, nothing sent.")
    decide = brain.approve if approved else brain.decline
    resp = await decide(pid, session_id=sid)  # never an error: the decision already took effect
    assert world.sent == ([{"to": "priya@example.com", "body": "3pm"}] if approved else [])
    assert "could not record" in resp.reply
    assert ("It was done" if approved else "Nothing was done") in resp.reply
    s = await store.get(sid)
    assert s is not None and _exchange(s) == ([], [])


# ---- L5: the 409 tells the truth about the owner's message -------------------------------------


@pytest.fixture
async def racing_app(
    settings: Settings, provider: MockProvider
) -> tuple[AsyncClient, RacingStore, MockProvider]:
    store = RacingStore()
    app = create_app(settings, provider=provider, store=store)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c, store, provider  # type: ignore[misc]


async def test_a_conflict_before_the_message_is_stored_says_send_it_again(racing_app) -> None:  # type: ignore[no-untyped-def]
    client, store, provider = racing_app
    sid = (await client.post("/v1/chat", json={"message": "hi"})).json()["session_id"]
    calls = len(provider.calls)
    store.refuse = 1  # the owner's message itself loses the race
    r = await client.post("/v1/chat", json={"message": "again", "session_id": sid})
    assert r.status_code == 409 and r.json()["error"] == "session_conflict"
    detail = r.json()["detail"]
    assert "not saved" in detail and "send it again" in detail
    assert len(provider.calls) == calls  # nothing was asked of the model, nothing spent
    s = await store.get(sid)
    assert s is not None and "again" not in [t.content for t in s.turns]


async def test_a_conflict_after_the_message_is_stored_says_it_was_kept(racing_app) -> None:  # type: ignore[no-untyped-def]
    client, store, _ = racing_app
    sid = (await client.post("/v1/chat", json={"message": "hi"})).json()["session_id"]
    store.allow, store.refuse = 1, 1  # the message is stored; the reply loses the race
    r = await client.post("/v1/chat", json={"message": "again", "session_id": sid})
    assert r.status_code == 409 and r.json()["error"] == "session_conflict"
    detail = r.json()["detail"]
    assert "message was kept" in detail and "send it again" not in detail
    s = await store.get(sid)
    assert s is not None and [t.content for t in s.turns].count("again") == 1


async def test_the_stream_final_event_carries_the_same_truthful_detail(racing_app) -> None:  # type: ignore[no-untyped-def]
    client, store, _ = racing_app
    sid = (await client.post("/v1/chat", json={"message": "hi"})).json()["session_id"]
    store.allow, store.refuse = 1, 1
    async with client.stream(
        "POST", "/v1/chat/stream", json={"message": "go", "session_id": sid}
    ) as r:
        body = "".join([chunk async for chunk in r.aiter_text()])
    final = json.loads(body.rsplit("\x1e", 1)[1])
    assert final["error"] == "session_conflict" and "message was kept" in final["detail"]


def test_message_not_saved_is_a_session_conflict() -> None:
    assert issubclass(MessageNotSaved, SessionConflict)
