# tests/test_r11_b_api.py -- R11 Part B's routes under /v1/helpers/house
# (docs/plans/r11-free-helpers.md D2, D19). Written before api/helpers_house.py: owner-only (the
# router's `require_auth`), `no-store`, every change rate-limited per owner and answered with the
# whole Home view; plain-word 422s; his place refused (409 off) without a keyring; 404
# helpers_off when the part isn't there.
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r11_fakes import UID
from r11_fakes_b import PLACE, house_ctx, sachet_fetcher

from jarvis.api import helpers_house
from jarvis.api.auth import require_auth
from jarvis.api.helpers import change_limiter
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.helpers.house import part as house_part

BASE = helpers_house.PREFIX


def _app(*, parts: dict[str, Any] | None = None, **over: Any) -> FastAPI:
    hc, *_ = house_ctx(**over)
    app = FastAPI()
    app.include_router(helpers_house.router)
    app.state.r11_parts = (
        parts if parts is not None else {"house": house_part.build(hc, fetcher=sachet_fetcher())}
    )
    app.state.helpers_limit = change_limiter()
    app.state.helpers_off = None
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_the_view_and_its_headers() -> None:
    async with _client(_app()) as c:
        r = await c.get(BASE)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["chores"] == [] and body["outside"]["available"] is True
    assert "Kerala" in body["outside"]["states"]


async def test_chores_add_done_and_remove() -> None:
    async with _client(_app()) as c:
        r = await c.post(
            f"{BASE}/chores",
            json={"label": "Dishes", "freq": "weekly", "days": ["mon", "thu"], "at": "21:00",
                  "members": ["Partner", "Me"]},
        )  # fmt: skip
        assert r.status_code == 200, r.text
        (chore,) = r.json()["chores"]
        assert chore["how_often"] == "on Mon, Thu"
        r = await c.post(f"{BASE}/chores/{chore['id']}/done")
        assert r.json()["chores"][0]["done_today"] is True
        r = await c.delete(f"{BASE}/chores/{chore['id']}")
        assert r.json()["chores"] == []
        bad = await c.post(f"{BASE}/chores", json={"label": "", "freq": "daily"})
        assert bad.status_code == 422 and bad.json()["error"] == "invalid"
        twin = await c.post(f"{BASE}/chores", json={"label": "Mop", "freq": "daily"})
        twin = await c.post(f"{BASE}/chores", json={"label": "mop", "freq": "daily"})
        assert twin.status_code == 422 and "already" in twin.json()["detail"]
        gone = await c.post(f"{BASE}/chores/ffffffff/done")
        assert gone.status_code == 422


async def test_upkeep_add_done_remove() -> None:
    async with _client(_app()) as c:
        r = await c.post(
            f"{BASE}/upkeep",
            json={"label": "AC service", "every": 6, "unit": "months", "last_done": "2026-05-10"},
        )
        assert r.status_code == 200, r.text
        (item,) = r.json()["upkeep"]
        assert item["due"] == "2026-11-10" and item["state"] == "due"
        assert "AC service" not in [s["label"] for s in r.json()["starters"]]
        r = await c.post(f"{BASE}/upkeep/{item['id']}/done")
        assert r.json()["upkeep"][0]["state"] == "ok"
        r = await c.delete(f"{BASE}/upkeep/{item['id']}")
        assert r.json()["upkeep"] == []
        bad = await c.post(f"{BASE}/upkeep", json={"label": "x", "every": 9999, "unit": "months"})
        assert bad.status_code == 422


async def test_his_place_set_and_cleared_and_breach_watch() -> None:
    async with _client(_app()) as c:
        r = await c.put(f"{BASE}/place", json={**PLACE, "thresholds": {"rain_hour_mm": 20}})
        assert r.status_code == 200, r.text
        out = r.json()["outside"]
        assert out["place"]["district"] == "Ernakulam" and out["feed"] == "kerala"
        assert out["thresholds"]["rain_hour_mm"] == 20 and out["point_known"] is True
        r = await c.put(f"{BASE}/breach", json={"on": True})
        assert r.json()["outside"]["breach"]["on"] is True
        bad = await c.put(f"{BASE}/place", json={"district": "<script>", "state": "Kerala"})
        assert bad.status_code == 422
        bad = await c.put(f"{BASE}/place", json={"district": "Ernakulam", "state": "Atlantis"})
        assert bad.status_code == 422
        r = await c.delete(f"{BASE}/place")
        assert r.json()["outside"]["place"] is None


async def test_no_keyring_refuses_his_place_but_chores_still_work() -> None:
    async with _client(_app(keyring_on=False)) as c:
        r = await c.put(f"{BASE}/place", json=PLACE)
        assert r.status_code == 409 and r.json()["error"] == "off"
        assert "token key" in r.json()["detail"]
        assert (await c.post(f"{BASE}/chores", json={"label": "Mop", "freq": "daily"})).is_success


async def test_off_and_rate_limited() -> None:
    async with _client(_app(parts={})) as c:
        r = await c.get(BASE)
        assert r.status_code == 404 and r.json()["error"] == "helpers_off"
    app = _app()
    app.state.helpers_limit = RateLimiter(1)
    async with _client(app) as c:
        assert (await c.put(f"{BASE}/breach", json={"on": True})).status_code == 200
        r = await c.put(f"{BASE}/breach", json={"on": False})
        assert r.status_code == 429


@pytest.mark.parametrize("body", [{"on": "yes"}, {"on": True, "extra": 1}])
async def test_bodies_are_strict(body: dict[str, Any]) -> None:
    async with _client(_app()) as c:
        assert (await c.put(f"{BASE}/breach", json=body)).status_code == 422
