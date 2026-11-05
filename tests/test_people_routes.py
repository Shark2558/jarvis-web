# tests/test_people_routes.py
"""POST /v1/people/research, GET /v1/people/last, GET/POST /v1/settings/brain-mode."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.config import Settings
from jarvis.people.research import PeopleService
from jarvis.people.routes import RESEARCH_PER_MINUTE, install_people
from tests.test_people_research import FakeComposer, FakeSearcher


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.state.settings = settings
    app.state.people = PeopleService(FakeSearcher(), FakeComposer())
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: "owner"
    install_people(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        c.app = app  # type: ignore[attr-defined]
        yield c


async def test_research_returns_the_dossier_with_urls(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/people/research", json={"name": "Satya Nadella", "context": "Microsoft"}
    )

    body = r.json()
    assert r.status_code == 200
    assert body["profiles"] and body["profiles"][0]["url"].startswith("https://")
    assert body["summary"] and body["no_ai"] is False


async def test_research_in_no_ai_mode_has_links_and_no_summary(client: AsyncClient) -> None:
    client.app.state.settings.brain_mode = "none"  # type: ignore[attr-defined]

    body = (await client.post("/v1/people/research", json={"name": "Satya Nadella"})).json()

    assert body["summary"] is None and body["no_ai"] is True and body["profiles"]


async def test_private_request_is_422_out_of_scope(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/people/research", json={"name": "Ravi Kumar", "context": "his home address"}
    )

    assert r.status_code == 422
    assert r.json()["error"] == "out_of_scope"
    assert "public" in r.json()["detail"].lower()


async def test_search_failure_is_503(client: AsyncClient) -> None:
    client.app.state.people = PeopleService(FakeSearcher(fail=True))  # type: ignore[attr-defined]

    r = await client.post("/v1/people/research", json={"name": "Satya Nadella"})

    assert r.status_code == 503


async def test_unconfigured_service_is_503(client: AsyncClient) -> None:
    client.app.state.people = None  # type: ignore[attr-defined]

    assert (await client.post("/v1/people/research", json={"name": "A B"})).status_code == 503


async def test_extra_fields_and_missing_name_are_422(client: AsyncClient) -> None:
    assert (await client.post("/v1/people/research", json={})).status_code == 422
    assert (
        await client.post("/v1/people/research", json={"name": "A B", "photo": "x"})
    ).status_code == 422


async def test_last_dossier_is_session_only(client: AsyncClient) -> None:
    assert (await client.get("/v1/people/last")).json() == {"dossier": None}
    await client.post("/v1/people/research", json={"name": "Satya Nadella", "context": "Microsoft"})

    got = (await client.get("/v1/people/last")).json()

    assert got["dossier"]["name"] == "Satya Nadella"


async def test_research_is_rate_limited(client: AsyncClient) -> None:
    codes = [
        (await client.post("/v1/people/research", json={"name": "Satya Nadella"})).status_code
        for _ in range(RESEARCH_PER_MINUTE + 2)
    ]

    assert codes[-1] == 429


async def test_brain_mode_can_be_read_and_switched(client: AsyncClient) -> None:
    assert (await client.get("/v1/settings/brain-mode")).json()["mode"] == "ai"

    r = await client.post("/v1/settings/brain-mode", json={"mode": "none"})

    assert r.json()["mode"] == "none"
    assert client.app.state.settings.brain_mode == "none"  # type: ignore[attr-defined]
    assert "AI" in r.json()["meaning"]


async def test_brain_mode_rejects_unknown_values(client: AsyncClient) -> None:
    assert (await client.post("/v1/settings/brain-mode", json={"mode": "local"})).status_code == 422
