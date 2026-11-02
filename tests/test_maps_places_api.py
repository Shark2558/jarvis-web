# tests/test_maps_places_api.py — slice 12 D3: the owner's Home and Work (plain text ≤ 200
# characters, `maps_places/{uid}`) through GET / PUT /v1/maps/places, owner-only; the store fails
# closed on a damaged document; and GET /v1/quota (the Vitals lines) — counts only, ₹-free words.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.places.store import PLACE_LIMIT, MapsPlaces, PlacesRejected, PlacesUnreadable
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import Gateway

TOKEN = "t-maps-test"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


async def test_store_round_trip_and_clear() -> None:
    docs = MemoryDocs()
    s = MapsPlaces(docs)
    assert await s.get("u1") == (None, None)
    await s.put("u1", home="  12 Kowdiar Road \n Thiruvananthapuram ", work="Technopark")
    assert await s.get("u1") == ("12 Kowdiar Road Thiruvananthapuram", "Technopark")
    await s.put("u1", home=None, work="Technopark")
    assert await s.get("u1") == (None, "Technopark")
    assert await docs.get("jarvis_maps_places/u1") is not None
    assert await s.get("u2") == (None, None)


@pytest.mark.parametrize("value", ["x" * (PLACE_LIMIT + 1), "​​", "‮﻿"])
async def test_store_refuses_too_long_or_invisible_only_text(value: str) -> None:
    s = MapsPlaces(MemoryDocs())
    with pytest.raises(PlacesRejected):
        await s.put("u1", home=value, work=None)


@pytest.mark.parametrize("value", ["9845012345", "me@example.com", "PAN ABCDE1234F"])
async def test_store_refuses_private_numbers_and_addresses(value: str) -> None:
    s = MapsPlaces(MemoryDocs())
    with pytest.raises(PlacesRejected):
        await s.put("u1", home=None, work=value)


@pytest.mark.parametrize("doc", ["junk", {"home": 5}, {"home": "x" * 500}])
async def test_a_damaged_document_fails_closed(doc: object) -> None:
    docs = MemoryDocs()
    docs._data["jarvis_maps_places/u1"] = doc  # type: ignore[assignment]
    with pytest.raises(PlacesUnreadable):
        await MapsPlaces(docs).get("u1")


# ---- API ------------------------------------------------------------------------------------


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "env": "dev",
        "llm_backend": "mock",
        "session_backend": "memory",
        "api_token": SecretStr(TOKEN),
        "usd_inr_live": False,
        "google_api_key": SecretStr("AIza-test"),
    }
    base.update(over)
    return Settings(**base)


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    app = create_app(_settings(), provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def test_places_api_needs_the_owner(app_client: AsyncClient) -> None:
    assert (await app_client.get("/v1/maps/places")).status_code == 401
    r = await app_client.put("/v1/maps/places", json={"home": "x", "work": None})
    assert r.status_code == 401


async def test_places_api_round_trip(app_client: AsyncClient) -> None:
    r = await app_client.get("/v1/maps/places", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"configured": True, "home": None, "work": None}
    r = await app_client.put(
        "/v1/maps/places", headers=AUTH, json={"home": "Kowdiar", "work": "Technopark"}
    )
    assert r.status_code == 200 and r.json()["home"] == "Kowdiar"
    assert (await app_client.get("/v1/maps/places", headers=AUTH)).json()["work"] == "Technopark"
    r = await app_client.put("/v1/maps/places", headers=AUTH, json={"home": "", "work": None})
    assert r.json() == {"configured": True, "home": None, "work": None}


@pytest.mark.parametrize(
    "body",
    [{"home": "x" * 201, "work": None}, {"home": "9845012345"}, {"home": 5}, {"nope": "x"}],
)
async def test_places_api_refuses_bad_text_in_the_app_error_shape(
    app_client: AsyncClient, body: dict[str, Any]
) -> None:
    r = await app_client.put("/v1/maps/places", headers=AUTH, json=body)
    assert r.status_code == 422
    j = r.json()
    if "error" in j:
        assert j["error"] == "invalid_place" and isinstance(j["detail"], str)


async def test_quota_view_counts_without_rupees(app_client: AsyncClient) -> None:
    r = await app_client.get("/v1/quota", headers=AUTH)
    assert r.status_code == 200
    j = r.json()
    assert j["configured"] is True
    assert j["maps_search"]["limit"] == 31_500 and j["maps_search"]["used"] == 0
    assert j["youtube_search"]["limit"] == 90
    assert "₹" not in r.text and "$" not in r.text


async def test_without_a_key_the_quota_and_places_say_not_configured() -> None:
    app = create_app(
        _settings(google_api_key=None), provider=MockProvider(), store=InMemorySessionStore()
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/v1/quota", headers=AUTH)).json() == {"configured": False}
            got = (await c.get("/v1/maps/places", headers=AUTH)).json()
            assert got == {"configured": False, "home": None, "work": None}
            gw: Gateway = app.state.gateway
            names = {s.name for s in gw.registry.specs()}
            assert not any(n.startswith(("maps_", "youtube_")) for n in names)


async def test_with_a_key_the_maps_and_youtube_search_tools_are_registered(
    app_client: AsyncClient,
) -> None:
    app = app_client._transport.app  # type: ignore[attr-defined]
    names = {s.name for s in app.state.gateway.registry.specs()}
    assert {"maps_search", "maps_route", "youtube_search"} <= names
    # without the owner's Google link the playlist tools have nothing to read
    assert "youtube_my_playlists" not in names
