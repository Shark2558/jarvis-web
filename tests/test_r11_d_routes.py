# tests/test_r11_d_routes.py -- R11 Part D (plan D2, D19): the Kitchen tab's routes under
# /v1/helpers/kitchen: owner-only, no-store, rate-limited; the blocks button only ever makes an
# approval card through the gateway.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from google_fakes import FakeGoogle
from httpx import ASGITransport, AsyncClient
from r11_fakes import UID
from r11_fakes_d import Rules, connector, kctx

from jarvis.api.auth import require_auth
from jarvis.api.helpers import change_limiter
from jarvis.api.helpers_kitchen import PREFIX, router
from jarvis.api.identity import current_user
from jarvis.core.guardrails import ConfirmationGate
from jarvis.helpers.kitchen import part as kitchen_part
from jarvis.helpers.ports import HelperPart
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

CAL = "https://www.googleapis.com/calendar/v3"


@pytest.fixture
async def rig() -> AsyncIterator[tuple[AsyncClient, FastAPI, FakeGoogle]]:
    fake = FakeGoogle()
    conn = await connector(fake.client())
    c, _, _, _ = kctx(google=conn, rules=Rules())
    built = kitchen_part.build(c)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    reg = ToolRegistry()
    for t in built.tools:
        reg.register(t)
    app.state.r11_parts = {"kitchen": built}
    app.state.helpers_limit = change_limiter()
    app.state.gateway = Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app, fake


async def test_the_view_is_no_store_and_starts_empty(rig: Any) -> None:
    client, _, _ = rig
    r = await client.get(PREFIX)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    v = r.json()
    assert v["sealed"] is True and v["pantry"] == [] and v["prefs"]["diet"] == "veg"
    assert v["nutrition"]["installed"] is True and v["spend"]["on"] is False  # I1: USDA installed
    assert v["nutrition"]["label"] == (
        "US reference values (USDA FoodData Central); Indian varieties and home recipes can differ."
    )
    assert v["nutrition"]["credit"].startswith("Nutrient values: USDA FoodData Central")
    assert "attribution" not in v["nutrition"]  # the tab draws label + credit (review L5)
    assert v["calendar"] is True and v["blocks"]["cooking_at"] == "19:00"


async def test_pantry_prefs_and_receipts_change_through_the_routes(rig: Any) -> None:
    client, _, _ = rig
    r = await client.post(f"{PREFIX}/pantry", json={"add": ["rice", "Toor dal"]})
    assert r.status_code == 200 and r.json()["pantry"] == ["rice", "Toor dal"]
    r = await client.post(f"{PREFIX}/pantry", json={"remove": ["rice"]})
    assert r.json()["pantry"] == ["Toor dal"]
    r = await client.put(
        f"{PREFIX}/prefs",
        json={"diet": "egg", "spice": 2, "oil": 0, "cuisines": ["Kerala"], "note": "less salt"},
    )
    assert r.status_code == 200 and r.json()["prefs"]["diet"] == "egg"
    r = await client.put(f"{PREFIX}/spend", json={"on": True})
    assert r.status_code == 200 and r.json()["spend"]["on"] is True


async def test_bad_input_is_422_in_plain_words(rig: Any) -> None:
    client, _, _ = rig
    r = await client.put(f"{PREFIX}/prefs", json={"diet": "carnivore"})
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/pantry", json={"add": ["4111111111111111"]})
    assert r.status_code == 422 and r.json()["error"] == "invalid"
    r = await client.put(f"{PREFIX}/blocks", json={"cooking_at": "7pm"})
    assert r.status_code == 422


async def test_the_blocks_button_makes_a_card_and_never_writes_the_calendar(rig: Any) -> None:
    client, _, fake = rig
    r = await client.put(
        f"{PREFIX}/blocks",
        json={
            "cooking_at": "19:30",
            "cooking_minutes": 40,
            "washing_at": "21:00",
            "washing_minutes": 15,
            "days": ["mon", "wed"],
        },
    )
    assert r.status_code == 200 and r.json()["blocks"]["days"] == ["mon", "wed"]
    r = await client.post(f"{PREFIX}/blocks/propose")
    assert r.status_code == 200 and r.json()["pending"] is True
    assert "Cooking 19:30-20:10" in r.json()["message"]
    assert fake.sent("POST", "/events") == []


async def test_a_saved_recipe_can_be_removed(rig: Any) -> None:
    client, app, _ = rig
    svc = app.state.r11_parts["kitchen"].services["kitchen"]
    await svc.save_recipe(
        UID,
        {
            "title": "Avial",
            "diet": "veg",
            "minutes": 40,
            "ingredients": "100 g carrot",
            "steps": "Cook.",
        },
    )
    rid = (await client.get(PREFIX)).json()["recipes"][0]["id"]
    assert (await client.delete(f"{PREFIX}/recipes/{rid}")).json()["recipes"] == []
    assert (await client.delete(f"{PREFIX}/recipes/nosuch01")).status_code == 404


async def test_the_part_off_is_404_and_too_many_changes_are_429(rig: Any) -> None:
    client, app, _ = rig
    for _ in range(30):
        await client.post(f"{PREFIX}/pantry", json={"add": ["rice"]})
    assert (await client.post(f"{PREFIX}/pantry", json={"add": ["dal"]})).status_code == 429
    app.state.r11_parts = {"kitchen": HelperPart(name="kitchen", ready="setup failed")}
    r = await client.get(PREFIX)
    assert r.status_code == 404 and r.json()["error"] == "helpers_off"
