# tests/test_r11_1_i1_pictures.py -- R11.1 I1: Part B's attached pictures joined to Part D's
# picture research and turn guard, on the REAL app (INTEGRATION-B 3.2; INTEGRATION-D GATES A, B,
# C). The document service carries the owner's limits and the conversations from the start; a
# picture turn stays a picture turn on every tool round and after a restart (the guard fails
# closed: "could not read" counts as a picture turn); attach -> send -> POST /v1/picture/research
# is "done"; on a picture turn the main brain's research_person and web_search never take a name
# the owner did not type. Only the model (the mock, told it can see) and the web-search vendor are
# faked. Everybody named is made up.
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r11_1_fakes_b import make_png
from r11_1_fakes_d import FakeSearchVendor

import jarvis.api.app as app_mod
import jarvis.api.feature_wiring as feature_wiring
from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.documents.pictures import TurnPictures, turn_pictures
from jarvis.documents.service import DocumentService, policy_from
from jarvis.documents.store import AttachmentStore
from jarvis.llm.base import ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.picture.guard import NO_IDENTIFY
from jarvis.picture.turnguard import WEB_REFUSED, DocumentTurns
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry
from jarvis.tools.context import require_tool_context
from jarvis.tools.taint import context_trust
from jarvis.web.allowance import WebAllowance
from jarvis.web.service import WebService

ROOT = Path(__file__).resolve().parents[1]
UID = "owner"  # local dev with no owners configured
FACE = "Meenu Examplewala"  # a made-up person a model "recognised" from a face
CSRF = {"X-Requested-With": "JARVIS"}


class Seeing(MockProvider):
    vision = True


def _look() -> str:
    return json.dumps(
        {
            "has_person": False,
            "scene": "A red packet of biscuits on a table.",
            "text": ["PARLE-G"],
            "subjects": [{"kind": "product", "name": "Parle-G biscuit packet"}],
            "named_in_text": "",
        }
    )


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> FakeSearchVendor:
    """The app's web search on a recording vendor: web_search and people research are wired."""
    fake = FakeSearchVendor()
    monkeypatch.setattr(
        feature_wiring,
        "build_web_service",
        lambda s, docs: WebService(fake, WebAllowance(MemoryDocs())),
    )
    return fake


@pytest.fixture
def shared(monkeypatch: pytest.MonkeyPatch) -> tuple[MemoryDocs, InMemorySessionStore]:
    """One document store and one conversation store that outlive an app: a restart."""
    docs, store = MemoryDocs(), InMemorySessionStore()
    monkeypatch.setattr(app_mod, "app_docs", lambda built: docs)
    return docs, store


@asynccontextmanager
async def running(
    s: Settings, provider: MockProvider, store: InMemorySessionStore
) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=provider, store=store)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


async def _attach(c: AsyncClient) -> str:
    r = await c.post(
        "/v1/attachments",
        content=make_png(64, 48),
        headers={"X-Jarvis-Filename": "packet.png", "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["pictures"] == 1
    return str(r.json()["id"])


# ---- INTEGRATION-B 3.2: the service is built with the owner's limits and the conversations ---
async def test_the_document_service_has_his_limits_and_the_conversations_from_the_start(
    settings: Settings,
) -> None:
    s = settings.model_copy(update={"attach_max_files": 3, "attach_picture_max_kb": 500})
    store = InMemorySessionStore()
    async with running(s, MockProvider(), store) as (app, _):
        docs: DocumentService = app.state.documents
        assert docs.policy == policy_from(s)  # before any request reached a route
        assert docs.sessions is app.state.store is store


def test_no_route_sets_the_document_policy_any_more() -> None:
    text = (ROOT / "src" / "jarvis" / "api" / "documents.py").read_text(encoding="utf-8")
    assert "svc.policy =" not in text and ".policy = policy_from" not in text


# ---- GATE C: a picture turn stays one on every tool round, and "could not read" is one too ----
async def test_a_picture_turn_stays_a_picture_turn_on_every_tool_round(settings: Settings) -> None:
    """The Brain stores each round's tool results as a user turn; the latest OWNER turn is still
    the one that carried the picture, so the guard's port never says "no" while the brain sees
    one (the picture stays in the window for every round)."""
    seeing = Seeing()
    spec = BrainSpec(id="s", label="s", provider=seeing, tiers={t: "m" for t in ModelTier})
    store = InMemorySessionStore()
    docs = DocumentService(AttachmentStore(MemoryDocs()), sessions=store)
    seen: list[tuple[int, bool]] = []

    async def probe(_a: dict[str, Any]) -> dict[str, Any]:
        ctx = require_tool_context()
        got = await turn_pictures(docs, ctx.user_id, ctx.session_id)
        seen.append((len(got), got.unreadable))
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(
        Tool("probe", "p", {"type": "object", "properties": {}}, ActionRisk.READ_ONLY, probe)
    )
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    brain = Brain(
        brains=BrainRegistry([spec], default_id="s"),
        store=store,
        settings=settings,
        gateway=gw,
        documents=docs,
    )
    aid = (await docs.upload(UID, "packet.png", make_png())).id
    seeing.script_tool_calls([ToolCall(id="c1", name="probe", arguments={})])
    seeing.script_tool_calls([ToolCall(id="c2", name="probe", arguments={})], "Done, Sir.")
    out = await brain.chat(ChatRequest(message="What is this?", attachments=[aid]))

    assert seen == [(1, False), (1, False)]
    after = await turn_pictures(docs, UID, out.session_id)
    assert len(after) == 1 and not after.unreadable  # the console's press, after the reply
    seeing.script("You're welcome, Sir.")
    await brain.chat(ChatRequest(message="Thanks", session_id=out.session_id))
    assert await turn_pictures(docs, UID, out.session_id) == []  # a newer message: no picture


class _Docs:
    """A document service whose pictures could not be read just now."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer


async def test_pictures_that_could_not_be_read_count_as_a_picture_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.picture.turnguard as tg

    async def unreadable(docs: Any, uid: str, sid: str, **kw: Any) -> TurnPictures:
        return TurnPictures(unreadable=True)

    monkeypatch.setattr(tg, "turn_pictures", unreadable)
    assert await DocumentTurns(lambda: _Docs(None)).carried(UID, "s1") == "unknown"


async def test_without_any_conversation_store_the_port_cannot_tell_and_fails_closed() -> None:
    docs = DocumentService(AttachmentStore(MemoryDocs()))  # no sessions of its own
    assert await DocumentTurns(lambda: docs).carried(UID, "s1") == "unknown"
    store = InMemorySessionStore()
    port = DocumentTurns(lambda: docs, sessions=lambda: store)  # the app's store, read late
    assert await port.carried(UID, "s1") == "no"  # a missing conversation carried nothing


# ---- the joined flow on the real app ----------------------------------------------------------
async def test_attach_send_and_research_the_picture_then_again_after_a_restart(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    vendor: FakeSearchVendor,
    shared: tuple[MemoryDocs, InMemorySessionStore],
) -> None:
    monkeypatch.setattr(MockProvider, "vision", True)
    _, store = shared
    first = MockProvider()
    async with running(settings, first, store) as (_, c):
        aid = await _attach(c)
        first.script("A packet of biscuits, Sir.")
        chat = await c.post("/v1/chat", json={"message": "What is this?", "attachments": [aid]})
        assert chat.status_code == 200, chat.text
        sid = chat.json()["session_id"]
        shown = [m for call in first.calls for m in call.messages if isinstance(m.content, list)]
        assert any(getattr(b, "type", "") == "image" for m in shown for b in m.content)
        first.script(_look())
        r = await c.post("/v1/picture/research", json={"session_id": sid}, headers=CSRF)
        assert r.status_code == 200 and r.json()["status"] == "done", r.text
        assert vendor.queries == ["Parle-G biscuit packet"]

    restarted = MockProvider()
    async with running(settings, restarted, store) as (app, c):
        got = await turn_pictures(app.state.documents, UID, sid)
        assert len(got) == 1 and not got.unreadable  # the durable turn, read again
        assert got[0].media_type == "image/png" and got[0].data[:8] == b"\x89PNG\r\n\x1a\n"
        restarted.script(_look())
        r = await c.post("/v1/picture/research", json={"session_id": sid}, headers=CSRF)
        assert r.status_code == 200 and r.json()["status"] == "done", r.text


# ---- GATES A and B: the main brain's own calls on a picture turn ------------------------------
async def test_on_a_picture_turn_the_main_brain_never_researches_or_searches_a_face_s_name(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    vendor: FakeSearchVendor,
    shared: tuple[MemoryDocs, InMemorySessionStore],
) -> None:
    monkeypatch.setattr(MockProvider, "vision", True)
    _, store = shared
    brain = MockProvider()
    async with running(settings, brain, store) as (app, c):
        names = {spec.name for spec in app.state.gateway.registry.specs()}
        assert {"research_person", "web_search"} <= names
        aid = await _attach(c)
        brain.script_tool_calls(
            [
                ToolCall(id="c1", name="research_person", arguments={"name": FACE}),
                ToolCall(id="c2", name="web_search", arguments={"query": f"{FACE} biography"}),
            ]
        )
        brain.script_tool_calls(  # a second round: the picture is still in the window
            [ToolCall(id="c3", name="web_search", arguments={"query": f"{FACE} family"})],
            "I don't identify people from pictures, Sir.",
        )
        chat = await c.post("/v1/chat", json={"message": "Who is this?", "attachments": [aid]})
        assert chat.status_code == 200, chat.text
        sid = chat.json()["session_id"]
        session = await store.get(sid)
        assert session is not None
        results = [
            b for t in session.turns for b in t.blocks if getattr(b, "type", "") == "tool_result"
        ]
        words = " ".join(str(b.content) for b in results)

    assert vendor.queries == []  # nothing about the person was ever sent to the vendor
    assert len(results) == 3 and NO_IDENTIFY in words and WEB_REFUSED in words
    assert FACE not in words

    async with running(settings, MockProvider(), store) as (app, _):  # after a restart
        with context_trust(untrusted=True, owner_text="Who is this?"):
            res = await app.state.gateway.execute(
                ToolCall(id="c9", name="research_person", arguments={"name": FACE}),
                scope=f"{UID}:{sid}",
            )
    assert NO_IDENTIFY in (res.error or "") and vendor.queries == []


async def test_without_a_picture_the_same_calls_are_unchanged(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    vendor: FakeSearchVendor,
    shared: tuple[MemoryDocs, InMemorySessionStore],
) -> None:
    _, store = shared
    brain = MockProvider()
    async with running(settings, brain, store) as (_, c):
        brain.script_tool_calls(
            [ToolCall(id="c1", name="web_search", arguments={"query": f"{FACE} biography"})],
            "Here is what I found, Sir.",
        )
        chat = await c.post("/v1/chat", json={"message": "Search the web for a biography."})
        assert chat.status_code == 200, chat.text

    assert vendor.queries == [f"{FACE} biography"]


async def test_pictures_that_could_not_be_read_are_said_not_called_missing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Part B's contract: `unreadable` means "say you couldn't look", never "no picture"."""
    import jarvis.picture.part as part_mod
    from jarvis.picture.research import NO_PICTURE, PICTURES_UNREADABLE

    async def unreadable(docs: Any, uid: str, sid: str, **kw: Any) -> TurnPictures:
        return TurnPictures(unreadable=True)

    monkeypatch.setattr(MockProvider, "vision", True)
    monkeypatch.setattr(part_mod, "turn_pictures", unreadable)
    seeing = MockProvider()
    async with running(settings, seeing, InMemorySessionStore()) as (_, c):
        r = await c.post("/v1/picture/research", json={"session_id": "sess_1"}, headers=CSRF)

    assert r.json() == {"status": "unreadable", "message": PICTURES_UNREADABLE}
    assert PICTURES_UNREADABLE != NO_PICTURE and seeing.calls == []


# ---- INTEGRATION-D 4.D: the "Look up" card is a reply card of its own ------------------------
def test_the_look_up_card_is_a_reply_card_kind_and_the_console_draws_it() -> None:
    import typing

    from jarvis.core.models import ChatResponse
    from jarvis.people.offer import kind_known
    from jarvis.people.offer_card import PeopleOfferCard
    from jarvis.tools import reply_cards

    assert PeopleOfferCard in typing.get_args(reply_cards.AnyCard) and kind_known()
    card = PeopleOfferCard(name="Lekha Examplekar", caption="MINISTER LEKHA", words="Offer.")
    resp = ChatResponse.model_validate(
        {
            "session_id": "s",
            "reply": "r",
            "trace_id": "t",
            "model": "m",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "cost_usd": 0.0,
            "latency_ms": 1,
            "turn_count": 1,
            "cards": [card.model_dump()],
        }
    )
    assert resp.cards == [card]  # the response's discriminated union takes it
    media = (ROOT / "src/jarvis/api/static/console-media.js").read_text(encoding="utf-8")
    assert "'people_offer'" in media and "window.JarvisPeople.offerCard(c)" in media
