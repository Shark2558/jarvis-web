# tests/test_r7_b_api.py -- R7 Part B's routes on the real app (docs/plans/r7-mobile.md D12-D14):
# `GET /v1/vision` says which tasks this server can run (pose and objects "not installed" until
# their model files arrive); `/v1/vision/results` keeps, lists and deletes the results he pressed
# Keep on. A result outside its schema (an unknown field such as pixels, a label from no list,
# text over 2,000 characters) is dropped with plain words and nothing is stored; a big body is
# refused before it is read; changes are rate-limited; off and without a key it says so. The
# part is wired: its tool in the gateway, its sweep on the morning tick, its rows in Privacy.
from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r7_fakes_b import LABEL_TEXT, ROOT_KEY, quality_result, result, text_result

from jarvis.api import create_app
from jarvis.api.r7_wiring import mobile_daily_jobs
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.vision import assets

CSRF = {"X-Requested-With": "JARVIS"}
BASE = "/v1/vision/results"
KEY = SecretStr(base64.b64encode(ROOT_KEY).decode())


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


def sealed(settings: Settings, **over: Any) -> Settings:
    return settings.model_copy(update={"token_key": KEY, **over})


async def test_the_part_is_wired_with_its_tool_sweep_and_rows(settings: Settings) -> None:
    async with running(sealed(settings)) as (app, _):
        assert app.state.r7_parts["vision"].ready == "ready"
        assert "vision_results" in {s.name for s in app.state.gateway.registry.specs()}
        assert "vision_sweep" in {j.name for j in mobile_daily_jobs(app)}
        assert {"vision_results", "vision_device"} <= set(app.state.privacy.registry.ids())


async def test_the_status_says_which_tasks_are_installed(settings: Settings) -> None:
    async with running(sealed(settings)) as (_, client):
        r = await client.get("/v1/vision")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        got = r.json()
        assert got["part"] == "vision" and got["ready"] == "ready" and got["sealed"] is True
        assert got["release"] == assets.RELEASE and got["keep_days"] == 90
        assert got["tasks"]["pose"] == {"installed": False, "why": "not installed"}
        assert got["tasks"]["objects"] == {"installed": False, "why": "not installed"}
        for task in ("text", "code", "quality"):
            assert got["tasks"][task] == {"installed": True, "why": ""}, task


async def test_keep_list_and_delete_a_result(settings: Settings) -> None:
    async with running(sealed(settings)) as (_, client):
        r = await client.post(BASE, json=text_result(), headers=CSRF)
        assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
        kept = r.json()["kept"]
        assert kept["id"].startswith("vr_") and kept["data"]["text"] == LABEL_TEXT
        listed = (await client.get(BASE, params={"days": 7})).json()
        assert listed["sealed"] is True and [k["id"] for k in listed["results"]] == [kept["id"]]
        gone = await client.delete(f"{BASE}/{kept['id']}", headers=CSRF)
        assert gone.status_code == 200 and gone.json() == {"deleted": True}
        again = await client.delete(f"{BASE}/{kept['id']}", headers=CSRF)
        assert again.status_code == 404 and again.json()["error"] == "not_found"
        assert (await client.get(BASE)).json()["results"] == []


async def test_a_result_outside_its_schema_is_dropped_in_plain_words(settings: Settings) -> None:
    bad: list[Any] = [
        {**text_result(), "pixels": "iVBORw0KGgoAAAANSUhEUg=="},
        text_result("x" * 2001),
        result(
            "objects",
            {
                "objects": [
                    {
                        "label": "person_named_x",
                        "score": 0.9,
                        "box": {"x": 0, "y": 0, "w": 1, "h": 1},
                    }
                ]
            },
        ),  # fmt: skip
        result("quality", {"light": -1, "sharp": 0.5}),
        [text_result()],
        "not json at all",
    ]
    async with running(sealed(settings)) as (_, client):
        for body in bad:
            if isinstance(body, str):
                r = await client.post(
                    BASE, content=body, headers={**CSRF, "Content-Type": "application/json"}
                )
            else:
                r = await client.post(BASE, json=body, headers=CSRF)
            assert r.status_code == 422, body
            assert r.json() == {
                "error": "dropped",
                "detail": "That result doesn't fit its task, so it was dropped.",
            }
        assert (await client.get(BASE)).json()["results"] == []


async def test_a_big_body_is_refused_before_it_is_read(settings: Settings) -> None:
    async with running(sealed(settings)) as (_, client):
        huge = b'{"task":"text","data":{"text":"' + b"x" * 70_000 + b'"}}'
        r = await client.post(
            BASE, content=huge, headers={**CSRF, "Content-Type": "application/json"}
        )
        assert r.status_code == 413 and r.json()["error"] == "too_large"


async def test_changes_are_rate_limited(settings: Settings) -> None:
    async with running(sealed(settings)) as (app, client):
        limiter = app.state.r7_parts["vision"].services["vision"].limit
        limiter.capacity = 1.0
        limiter._buckets.clear()
        limiter.refill_per_s = 1e-9  # no refill inside the test
        first = await client.post(BASE, json=quality_result(), headers=CSRF)
        second = await client.post(BASE, json=quality_result(), headers=CSRF)
        assert first.status_code == 201 and second.status_code == 429
        assert second.json()["error"] == "rate_limited"


async def test_without_a_token_key_nothing_is_kept_and_it_says_why(settings: Settings) -> None:
    async with running(settings) as (_, client):
        listed = await client.get(BASE)
        assert listed.status_code == 200
        assert listed.json()["sealed"] is False and listed.json()["results"] == []
        assert "token key" in listed.json()["detail"]
        r = await client.post(BASE, json=text_result(), headers=CSRF)
        assert r.status_code == 409 and r.json()["error"] == "not_sealed"
        status = (await client.get("/v1/vision")).json()
        assert status["sealed"] is False and status["tasks"]["text"]["installed"] is True


async def test_off_in_settings_the_routes_say_so(settings: Settings) -> None:
    async with running(sealed(settings, vision_enabled=False)) as (_, client):
        r = await client.get(BASE)
        assert r.status_code == 404 and r.json()["error"] == "vision_off"
        assert (await client.post(BASE, json=text_result(), headers=CSRF)).status_code == 404
        assert (await client.get("/v1/vision")).json()["ready"].startswith("off")


async def test_a_bad_id_or_days_is_refused(settings: Settings) -> None:
    async with running(sealed(settings)) as (_, client):
        assert (await client.delete(f"{BASE}/../../x", headers=CSRF)).status_code == 404
        assert (await client.delete(f"{BASE}/vr_ZZ", headers=CSRF)).status_code == 404
        assert (await client.get(BASE, params={"days": 0})).status_code == 422
        assert (await client.get(BASE, params={"days": 366})).status_code == 422
