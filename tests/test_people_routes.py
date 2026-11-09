# tests/test_people_routes.py
"""POST /v1/people/research, GET /v1/people/last, GET/POST /v1/settings/brain-mode."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from research_fakes import PRIVATE_HITS, FakeModel, FakeSearcher

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.config import Settings
from jarvis.offline.mode import BrainMode
from jarvis.people.guard import UNVERIFIED_REFUSAL
from jarvis.people.research import RATE_BURST, PeopleService
from jarvis.people.routes import install_people
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.state.settings = settings
    app.state.audit = AuditLog()
    app.state.brain_mode = BrainMode(settings, MemoryDocs(), audit=app.state.audit)
    mode = app.state.brain_mode
    app.state.people = PeopleService(FakeSearcher(), FakeModel(), mode=mode.load)
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
    assert body["summary"] and body["no_ai"] is False and body["cost_usd"] > 0


async def test_research_in_no_ai_mode_has_links_and_no_summary(client: AsyncClient) -> None:
    await client.post("/v1/settings/brain-mode", json={"mode": "none"})

    body = (await client.post("/v1/people/research", json={"name": "Satya Nadella"})).json()

    assert body["summary"] is None and body["no_ai"] is True and body["profiles"]


async def test_private_phrasing_is_422_out_of_scope(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/people/research", json={"name": "Ravi Kumar", "context": "his home address"}
    )

    assert r.status_code == 422
    assert r.json()["error"] == "out_of_scope"
    assert "public" in r.json()["detail"].lower()


async def test_a_bare_private_name_is_422_with_the_fixed_line_and_no_links(
    client: AsyncClient,
) -> None:
    client.app.state.people = PeopleService(  # type: ignore[attr-defined]
        FakeSearcher(PRIVATE_HITS), FakeModel(label="public_figure")
    )

    r = await client.post("/v1/people/research", json={"name": "Priya Nair"})

    assert r.status_code == 422
    assert r.json() == {"error": "out_of_scope", "detail": UNVERIFIED_REFUSAL}
    assert (await client.get("/v1/people/last")).json() == {"dossier": None}


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


async def test_last_dossier_is_the_owners_own(client: AsyncClient) -> None:
    assert (await client.get("/v1/people/last")).json() == {"dossier": None}
    await client.post("/v1/people/research", json={"name": "Satya Nadella", "context": "Microsoft"})

    got = (await client.get("/v1/people/last")).json()

    assert got["dossier"]["name"] == "Satya Nadella"


async def test_research_is_rate_limited_by_the_service_with_a_burst_of_two(
    client: AsyncClient,
) -> None:
    codes = [
        (await client.post("/v1/people/research", json={"name": "Satya Nadella"})).status_code
        for _ in range(RATE_BURST + 1)
    ]

    assert codes == [200, 200, 429]


async def test_brain_mode_can_be_read_and_switched_and_is_persisted(client: AsyncClient) -> None:
    assert (await client.get("/v1/settings/brain-mode")).json()["mode"] == "ai"

    r = await client.post("/v1/settings/brain-mode", json={"mode": "none"})

    assert r.json()["mode"] == "none" and "AI" in r.json()["meaning"]
    reborn = BrainMode(client.app.state.settings, client.app.state.brain_mode._docs)  # type: ignore[attr-defined]
    assert await reborn.load("owner") == "none"  # a fresh process reads the stored value
    assert (await client.get("/v1/settings/brain-mode")).json()["mode"] == "none"


async def test_every_flip_is_audited(client: AsyncClient) -> None:
    await client.post("/v1/settings/brain-mode", json={"mode": "none"})
    await client.post("/v1/settings/brain-mode", json={"mode": "ai"})

    tail = await client.app.state.audit.tail(5)  # type: ignore[attr-defined]

    assert [e.tool for e in tail.entries] == ["brain_mode_set"] * 2


async def test_brain_mode_rejects_unknown_values(client: AsyncClient) -> None:
    assert (await client.post("/v1/settings/brain-mode", json={"mode": "local"})).status_code == 422


async def test_brain_mode_routes_use_the_owner_identity() -> None:
    from jarvis.people.routes import router

    paths = {(r.path, tuple(sorted(r.methods or ()))) for r in router.routes}  # type: ignore[attr-defined]
    for route in router.routes:
        if route.path == "/v1/settings/brain-mode":  # type: ignore[attr-defined]
            deps = {d.call for d in route.dependant.dependencies}  # type: ignore[attr-defined]
            assert current_user in deps
    assert paths
