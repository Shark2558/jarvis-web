# tests/test_r7_d_api.py -- R7 Part D's routes (docs/plans/r7-mobile.md D17-D21): `/v1/watch` and
# `/v1/sos` on the real app. Owner-only, `no-store`, writes need the CSRF header; the status keys
# I0 pinned (`part`, `ready`) stay; the SOS routes answer while the app is locked (D21) but the
# set-up (label, contacts, links) does not change while it is locked; the send keeps every place
# in the POST body and the reply only, never in an address or a stored document.
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from httpx import ASGITransport, AsyncClient
from r7_fakes_d import ASHA, LAT_E6, LON_E6, Clock, PinBot, needles, settings

from jarvis.api import create_app
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.mobile.ports import MobilePart

CSRF = {"X-Requested-With": "JARVIS"}
HEALTH = {
    "v": 1,
    "days": [
        {
            "date": "2026-11-12",
            "steps": {"count": 8123, "writer": "com.noisefit"},
            "heart": None,
            "sleep": [
                {
                    "start": "2026-11-11T23:50:00+05:30",
                    "end": "2026-11-12T06:30:00+05:30",
                    "writer": "android",
                    "stages": None,
                }
            ],
        }
    ],
}
PLACE = {"lat_e6": LAT_E6, "lon_e6": LON_E6, "accuracy_m": 20, "age_s": 3}


@asynccontextmanager
async def running(**over: Any) -> AsyncIterator[tuple[Any, AsyncClient]]:
    app = create_app(settings(**over), provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        app.state.helpers_now = Clock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


def _lock(app: Any, locked: bool) -> None:
    async def check(scope: Any) -> bool:
        return locked

    parts = dict(app.state.r7_parts)
    parts["phone"] = MobilePart("phone", services={"app_lock": check})
    app.state.r7_parts = parts


async def test_the_status_keys_stay_and_the_views_are_no_store() -> None:
    async with running() as (_, c):
        for path in ("/v1/watch", "/v1/sos"):
            r = await c.get(path)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
            assert r.json()["part"] == "body" and r.json()["ready"] == "ready"
        assert (await c.get("/v1/sos")).json()["contacts"] == []
        assert (await c.get("/v1/watch")).json()["last_synced"] is None


async def test_the_watch_view_and_a_typed_night() -> None:
    async with running() as (app, c):
        await (
            app.state.r7_parts["body"]
            .services["watch"]
            .intake("owner", json.dumps(HEALTH).encode())
        )
        v = (await c.get("/v1/watch")).json()
        assert v["last_night"]["source"] == "phone" and v["today"]["steps"]["count"] == 8123
        bad = await c.post("/v1/watch/sleep", json={"start": "noon", "end": "06:00"}, headers=CSRF)
        assert bad.status_code == 422 and "Sir" in bad.json()["detail"]
        ok = await c.post("/v1/watch/sleep", json={"start": "23:30", "end": "06:00"}, headers=CSRF)
        assert ok.status_code == 200 and ok.json()["night"]["source"] == "typed"
        assert ok.json()["message"].startswith("Noted, Sir")


async def test_watch_without_a_token_key_says_why() -> None:
    async with running(token_key=None) as (_, c):
        v = (await c.get("/v1/watch")).json()
        assert v["sealed"] is False and "token key" in v["note"]
        r = await c.post("/v1/watch/sleep", json={"start": "23:30", "end": "06:00"}, headers=CSRF)
        assert r.status_code == 503 and "token key" in r.json()["detail"]


async def test_the_sos_setup_through_the_routes() -> None:
    async with running() as (app, c):
        assert (
            await c.put("/v1/sos/label", json={"label": "Kiran Example"}, headers=CSRF)
        ).status_code == 200
        r = await c.post(
            "/v1/sos/contacts", json={"label": ASHA[0], "phone": ASHA[1]}, headers=CSRF
        )
        assert r.status_code == 200
        cid = r.json()["contact"]["id"]
        v = (await c.get("/v1/sos")).json()
        assert v["label"] == "Kiran Example" and v["contacts"][0]["phone_hint"] == "••01"
        assert ASHA[1] not in json.dumps(v)  # the full number only on the sheet
        sheet = (await c.get("/v1/sos/sheet")).json()
        assert sheet["numbers"] == [ASHA[1]] and sheet["emergency"] == "112"
        link = await c.post(f"/v1/sos/contacts/{cid}/link", headers=CSRF)
        assert link.status_code == 503 and "Telegram" in link.json()["detail"]  # no bot here
        bad = await c.post("/v1/sos/contacts", json={"label": " ", "phone": None}, headers=CSRF)
        assert bad.status_code == 422
        gone = await c.delete(f"/v1/sos/contacts/{cid}", headers=CSRF)
        assert gone.status_code == 200 and (await c.get("/v1/sos")).json()["contacts"] == []
        assert (await c.delete("/v1/sos/contacts/c_0000000000", headers=CSRF)).status_code == 404


async def test_a_join_link_with_a_bot() -> None:
    async with running() as (app, c):
        client = PinBot().client()

        class Tg:
            pass

        tg = Tg()
        tg.client = client  # type: ignore[attr-defined]
        tg.sos = None  # type: ignore[attr-defined]
        app.state.telegram = tg
        r = await c.post("/v1/sos/contacts", json={"label": ASHA[0]}, headers=CSRF)
        cid = r.json()["contact"]["id"]
        link = await c.post(f"/v1/sos/contacts/{cid}/link", headers=CSRF)
        assert link.status_code == 200 and link.headers["cache-control"] == "no-store"
        assert link.json()["link"].startswith("https://t.me/jarvis_test_bot?start=sos-")


async def test_the_send_keeps_the_place_in_the_body_only() -> None:
    async with running() as (app, c):
        await c.post("/v1/sos/contacts", json={"label": ASHA[0], "phone": ASHA[1]}, headers=CSRF)
        r = await c.post("/v1/sos/send", json={"kind": "test", "location": PLACE}, headers=CSRF)
        body = r.json()
        assert r.status_code == 200 and body["outcome"] == "none_joined" and body["sent"] is False
        assert body["sms"]["numbers"] == [ASHA[1]] and "maps.google.com" in body["sms"]["text"]
        assert str(r.request.url) == "http://test/v1/sos/send"  # nothing in the address
        docs = app.state.r7_parts["body"].services["sos"].store._docs
        stored = json.dumps(docs._data, default=str)
        assert not [n for n in needles() if n in stored]
        for bad in ({"kind": "panic"}, {"kind": "real", "location": {**PLACE, "lat_e6": 9e9}}):
            assert (await c.post("/v1/sos/send", json=bad, headers=CSRF)).status_code == 422


async def test_while_locked_sos_still_works_and_the_setup_does_not_change() -> None:
    async with running() as (app, c):
        await c.post("/v1/sos/contacts", json={"label": ASHA[0], "phone": ASHA[1]}, headers=CSRF)
        _lock(app, True)
        v = (await c.get("/v1/sos")).json()
        assert v["locked"] is True and "contacts" not in v  # no names while locked
        assert (await c.get("/v1/sos/sheet")).json()["numbers"] == [ASHA[1]]  # SOS must work
        sent = await c.post("/v1/sos/send", json={"kind": "real", "location": None}, headers=CSRF)
        assert sent.status_code == 200 and sent.json()["call"]["emergency"] == "112"
        for method, path, body in (
            ("PUT", "/v1/sos/label", {"label": "Someone Else"}),
            ("POST", "/v1/sos/contacts", {"label": "Stranger Example"}),
            ("DELETE", "/v1/sos/contacts/c_0000000000", None),
        ):
            r = await c.request(method, path, json=body, headers=CSRF)
            assert r.status_code == 423 and r.json()["error"] == "device_locked", path
        _lock(app, False)
        assert (await c.get("/v1/sos")).json()["contacts"][0]["label"] == ASHA[0]


async def test_sos_off_on_this_server_says_so() -> None:
    async with running(sos_enabled=False) as (_, c):
        r = await c.post("/v1/sos/send", json={"kind": "real", "location": None}, headers=CSRF)
        assert r.status_code == 200 and r.json()["outcome"] == "unavailable"
        assert "switched off" in r.json()["words"] and r.json()["call"]["emergency"] == "112"


async def test_every_route_is_owner_only() -> None:
    from pydantic import SecretStr

    async with running(api_token=SecretStr("a-test-token-not-a-secret")) as (_, c):
        for method, path in (
            ("GET", "/v1/watch"),
            ("POST", "/v1/watch/sleep"),
            ("GET", "/v1/sos"),
            ("GET", "/v1/sos/sheet"),
            ("PUT", "/v1/sos/label"),
            ("POST", "/v1/sos/contacts"),
            ("POST", "/v1/sos/contacts/c_0000000000/link"),
            ("DELETE", "/v1/sos/contacts/c_0000000000"),
            ("POST", "/v1/sos/send"),
        ):
            r = await c.request(method, path, json={}, headers=CSRF)
            assert r.status_code == 401, path
