# tests/test_r11_1_d_routes.py -- R11.1 Part D's routes under /v1/picture (plan D17), on the REAL
# app: `GET /v1/picture` says whether a picture can be looked at right now, without a model call;
# `POST /v1/picture/research` runs the tool THROUGH THE GATEWAY for the open conversation's
# picture and answers what the console shows: the words, and the sources with their links (which a
# model is never shown). Only two things are faked: Part B's `turn_pictures` (it returns nothing
# until B fills it) and the brain (the mock provider, told it can see, with a scripted look).
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r11_1_fakes_d import FakeSearchVendor, TurnPictures, picture, read_text

import jarvis.picture.part as part_mod
from jarvis.api import create_app
from jarvis.api.fix_look import RESEARCH_PER_MINUTE
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.picture.eyes import BLIND, NO_AI
from jarvis.picture.guard import NO_IDENTIFY
from jarvis.picture.part import OFF as PART_OFF
from jarvis.picture.research import NO_PICTURE, OFF
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.web.allowance import WebAllowance
from jarvis.web.service import WebService
from jarvis.web.tools import web_tools

UID = "owner"  # the id of local dev with no owners configured
NAME = "Lekha Examplekar"  # a made-up person
SID = "sess_0a1b2c3d4e5f"


@pytest.fixture
def seeing(monkeypatch: pytest.MonkeyPatch) -> MockProvider:
    monkeypatch.setattr(MockProvider, "vision", True)
    return MockProvider()


@pytest.fixture
def turn(monkeypatch: pytest.MonkeyPatch) -> TurnPictures:
    """What Part B's `turn_pictures` will answer: the part calls it late, by its module name."""
    fake = TurnPictures()

    async def turn_pictures(docs: object, uid: str, session_id: str) -> list[Any]:
        return await fake(uid, session_id)

    monkeypatch.setattr(part_mod, "turn_pictures", turn_pictures)
    return fake


@asynccontextmanager
async def running(
    s: Settings, provider: MockProvider | None = None
) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=provider or MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


def _look(**over: Any) -> str:
    base: dict[str, Any] = {
        "has_person": False,
        "scene": "A red packet of biscuits on a table.",
        "text": ["PARLE-G"],
        "subjects": [{"kind": "product", "name": "Parle-G biscuit packet"}],
        "named_in_text": "",
    }
    base.update(over)
    return json.dumps(base)


def _with_web(app: FastAPI) -> FakeSearchVendor:
    vendor = FakeSearchVendor()
    app.state.web = WebService(vendor, WebAllowance(MemoryDocs()))
    for tool in web_tools(app.state.web):
        app.state.gateway.registry.register(tool)
    return vendor


# ---- GET /v1/picture: can a picture be looked at right now? --------------------------------------
async def test_the_status_says_ready_and_whether_a_brain_here_can_see(settings: Settings) -> None:
    async with running(settings) as (_, client):
        r = await client.get("/v1/picture")

    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"part": "look", "ready": "ready", "can": False, "why": BLIND}


async def test_with_a_seeing_private_brain_the_status_says_it_can(
    settings: Settings, seeing: MockProvider
) -> None:
    async with running(settings, seeing) as (_, client):
        r = await client.get("/v1/picture")

    assert r.json() == {"part": "look", "ready": "ready", "can": True, "why": ""}
    assert seeing.calls == []  # asking costs nothing: no model was called


async def test_in_no_ai_mode_the_status_says_why(settings: Settings, seeing: MockProvider) -> None:
    s = settings.model_copy(update={"brain_mode": "none"})
    async with running(s, seeing) as (_, client):
        r = await client.get("/v1/picture")
        post = await client.post("/v1/picture/research", json={"session_id": SID})

    assert r.json()["can"] is False and r.json()["why"] == NO_AI
    assert post.json()["status"] == "no_picture" and seeing.calls == []


async def test_switched_off_in_settings_both_routes_say_so(
    settings: Settings, seeing: MockProvider
) -> None:
    s = settings.model_copy(update={"picture_research_enabled": False})
    async with running(s, seeing) as (app, client):
        r = await client.get("/v1/picture")
        post = await client.post("/v1/picture/research", json={"session_id": SID})
        registered = app.state.gateway.registry.get("picture_research")

    assert r.json() == {"part": "look", "ready": PART_OFF, "can": False, "why": OFF}
    assert post.status_code == 200 and post.json() == {"status": "off", "message": OFF}
    assert registered is None and seeing.calls == []


# ---- POST /v1/picture/research -------------------------------------------------------------------
async def test_with_no_picture_it_says_so(settings: Settings, seeing: MockProvider) -> None:
    async with running(settings, seeing) as (_, client):
        r = await client.post("/v1/picture/research", json={"session_id": SID})

    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"status": "no_picture", "message": NO_PICTURE}
    assert seeing.calls == []


async def test_a_thing_comes_back_with_its_words_and_its_sources_links(
    settings: Settings, seeing: MockProvider, turn: TurnPictures
) -> None:
    pic = picture("PARLE-G")
    turn.attach(SID, pic, uid=UID)
    seeing.script(_look())
    async with running(settings, seeing) as (app, client):
        vendor = _with_web(app)
        r = await client.post("/v1/picture/research", json={"session_id": SID})
        audit = (await app.state.gateway.audit.tail(10)).entries

    out = r.json()
    assert r.status_code == 200 and out["status"] == "done" and out["person"] is False
    assert out["scene"] == "A red packet of biscuits on a table." and out["text"] == ["PARLE-G"]
    assert out["subjects"] == [{"kind": "product", "name": "Parle-G biscuit packet"}]
    assert [(s["about"], s["domain"], s["url"]) for s in out["sources"]] == [
        ("Parle-G biscuit packet", "example.org", "https://www.example.org/a"),
        ("Parle-G biscuit packet", "example.com", "https://example.com/b"),
    ]
    assert out["message"].endswith("I found 2 sources for Parle-G biscuit packet.")
    assert out["offer"] is None and out["pictures"] == 1
    assert vendor.queries == ["Parle-G biscuit packet"]
    # it ran as a tool call through the gateway: the audit chain has it
    assert ("picture", "picture_research", "executed") in [
        (e.agent, e.tool, e.outcome) for e in audit
    ]
    assert turn.asked == [(UID, SID)]
    # the model was sent the picture itself, and nothing of the conversation
    (call,) = seeing.calls
    assert call.messages[0].content[1] == pic and call.tools is None


async def test_a_person_gets_the_fixed_sentence_and_eyes_that_name_get_nowhere(
    settings: Settings, seeing: MockProvider, turn: TurnPictures
) -> None:
    turn.attach(SID, picture(person=True), uid=UID)
    seeing.script(
        _look(
            has_person=True,
            scene=f"This is {NAME}. A person in a blue top stands by a wall.",
            text=[],
            subjects=[{"kind": "other", "name": NAME}, {"kind": "landmark", "name": NAME}],
            named_in_text=NAME,
        )
    )
    async with running(settings, seeing) as (app, client):
        vendor = _with_web(app)
        r = await client.post("/v1/picture/research", json={"session_id": SID})

    out = r.json()
    assert out["person"] is True and out["offer"] is None and out["sources"] == []
    assert out["message"] == f"A person in a blue top stands by a wall. {NO_IDENTIFY}"
    assert NAME not in r.text and "Examplekar" not in r.text
    assert vendor.queries == []


async def test_a_name_in_the_pictures_own_text_is_offered(
    settings: Settings, seeing: MockProvider, turn: TurnPictures
) -> None:
    pic = picture(f"MINISTER {NAME.upper()}", "OPENS THE HARBOUR BRIDGE", person=True)
    turn.attach(SID, pic, uid=UID)
    seeing.script(
        _look(
            has_person=True,
            scene="A person in a blue top stands under a banner.",
            text=read_text(pic),
            subjects=[],
            named_in_text=NAME,
        )
    )
    async with running(settings, seeing) as (_, client):
        r = await client.post("/v1/picture/research", json={"session_id": SID})

    out = r.json()
    assert out["offer"] == {"name": NAME} and out["person"] is True
    assert out["message"].endswith(f"Shall I look {NAME} up from public sources, Sir?")


async def test_another_owners_or_conversations_picture_is_not_used(
    settings: Settings, seeing: MockProvider, turn: TurnPictures
) -> None:
    turn.attach(SID, picture("PARLE-G"), uid="u_someone_else")
    turn.attach("sess_other", picture("PARLE-G"), uid=UID)
    async with running(settings, seeing) as (_, client):
        r = await client.post("/v1/picture/research", json={"session_id": SID})

    assert r.json()["status"] == "no_picture" and seeing.calls == []
    assert turn.asked == [(UID, SID)]  # the owner's id comes from the sign-in, never the body


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"session_id": ""},
        {"session_id": "../../etc"},
        {"session_id": "x" * 65},
        {"session_id": SID, "picture": 0},
        {"session_id": SID, "picture": 5},
        {"session_id": SID, "picture": "1"},
        {"session_id": SID, "user_id": "u_someone_else"},
        {"session_id": SID, "question": "who is this?"},
    ],
)
async def test_a_malformed_request_is_refused_and_nothing_runs(
    settings: Settings, seeing: MockProvider, turn: TurnPictures, body: dict[str, Any]
) -> None:
    async with running(settings, seeing) as (_, client):
        r = await client.post("/v1/picture/research", json=body)

    assert r.status_code == 422 and turn.asked == [] and seeing.calls == []


@pytest.mark.parametrize(
    ("effect", "status", "words"),
    [
        (Effect.DENY, "denied", "set to 'Never' in Permissions"),
        (Effect.ASK, "waiting", "waiting in Approvals"),
    ],
)
async def test_the_owners_pictures_row_decides(
    settings: Settings,
    seeing: MockProvider,
    turn: TurnPictures,
    effect: Effect,
    status: str,
    words: str,
) -> None:
    turn.attach(SID, picture("PARLE-G"), uid=UID)
    async with running(settings, seeing) as (app, client):
        app.state.gateway.policy = Policy([PolicyRule(tool_pattern="picture_*", effect=effect)])
        r = await client.post("/v1/picture/research", json={"session_id": SID})

    assert r.status_code == 200 and r.json()["status"] == status and words in r.json()["message"]
    assert seeing.calls == [] and turn.asked == []


async def test_too_many_requests_are_refused_in_plain_words(
    settings: Settings, seeing: MockProvider
) -> None:
    async with running(settings, seeing) as (_, client):
        codes = [
            (await client.post("/v1/picture/research", json={"session_id": SID})).status_code
            for _ in range(RESEARCH_PER_MINUTE + 1)
        ]
        last = await client.post("/v1/picture/research", json={"session_id": SID})

    assert codes == [200] * RESEARCH_PER_MINUTE + [429]
    assert last.json() == {"error": "rate_limited", "detail": "Too many pictures; wait a moment."}


async def test_with_the_tools_switched_off_it_says_so(
    settings: Settings, seeing: MockProvider
) -> None:
    s = settings.model_copy(update={"tools_enabled": False})
    async with running(s, seeing) as (_, client):
        r = await client.post("/v1/picture/research", json={"session_id": SID})

    assert r.status_code == 503
    assert r.json() == {"error": "unavailable", "detail": "Tools are switched off on this server."}


async def test_both_routes_need_the_owners_sign_in(settings: Settings) -> None:
    s = settings.model_copy(
        update={"auth_mode": AuthMode.TOKEN, "api_token": SecretStr("a-test-token-not-a-secret")}
    )
    async with running(s) as (_, client):
        get = await client.get("/v1/picture")
        post = await client.post("/v1/picture/research", json={"session_id": SID})
        ok = await client.get(
            "/v1/picture", headers={"Authorization": "Bearer a-test-token-not-a-secret"}
        )

    assert (get.status_code, post.status_code, ok.status_code) == (401, 401, 200)
