# tests/test_vitals_api.py -- R4: the Vitals console's routes (owner-only; auth is the app's).
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from vitals_fakes import UID, Rig, key

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.vitals.api import router


@pytest.fixture
async def rig_client() -> AsyncIterator[tuple[Rig, AsyncClient]]:
    rig = Rig()
    app = FastAPI()
    app.include_router(router)
    app.state.vitals = rig.svc
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield rig, c


async def test_get_returns_the_board(rig_client) -> None:  # type: ignore[no-untyped-def]
    rig, c = rig_client
    await rig.svc.set_key(UID, key("brain", limit=10, used=9))

    r = await c.get("/v1/vitals")

    body = r.json()
    assert r.status_code == 200 and body["overall"] == "amber"
    assert {i["id"] for i in body["items"]} == {"ai_spend", "brain"}
    assert body["spend"]["text"].startswith("₹")


async def test_get_carries_the_version_and_build_date_for_the_about_line(  # type: ignore[no-untyped-def]
    rig_client, monkeypatch
) -> None:
    """R6.1 D4: the owner-only board answer gains two read-only fields (no new route)."""
    from jarvis import about

    rig, c = rig_client
    monkeypatch.setenv(about.BUILD_DATE_ENV, "2026-11-10T20:00:00Z")  # 01:30 on 11 Nov in India
    about.fields.cache_clear()
    try:
        body = (await c.get("/v1/vitals")).json()
    finally:
        about.fields.cache_clear()

    assert body["version"] == "v6.1.0" and body["build_date"] == "11 Nov 2026"
    assert {"overall", "items", "spend", "manual_unavailable", "manual_note"} <= body.keys()


async def test_without_a_build_stamp_the_date_is_unknown(rig_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from jarvis import about

    _, c = rig_client
    monkeypatch.delenv(about.BUILD_DATE_ENV, raising=False)
    monkeypatch.setattr(about, "PACKAGED_STAMP", None)
    about.fields.cache_clear()
    try:
        body = (await c.get("/v1/vitals")).json()
    finally:
        about.fields.cache_clear()

    assert body["build_date"] == "unknown" and body["version"] == "v6.1.0"


async def test_put_adds_a_manual_key_and_rejects_bad_ones(rig_client) -> None:  # type: ignore[no-untyped-def]
    rig, c = rig_client

    ok = await c.put("/v1/vitals/keys", json={"id": "k", "label": "K", "kind": "key", "limit": 5})
    bad = await c.put("/v1/vitals/keys", json={"id": "k", "label": "K", "kind": "nope"})
    reserved = await c.put("/v1/vitals/keys", json={"id": "ai_spend", "label": "K", "kind": "key"})

    assert ok.status_code == 200 and bad.status_code == 422 and reserved.status_code == 422
    assert [p.id for p in await rig.store.list_manual(UID)] == ["k"]


async def test_delete_removes_and_404s_when_absent(rig_client) -> None:  # type: ignore[no-untyped-def]
    rig, c = rig_client
    await rig.svc.set_key(UID, key("k"))

    assert (await c.delete("/v1/vitals/keys/k")).status_code == 200
    assert (await c.delete("/v1/vitals/keys/k")).status_code == 404


async def test_not_wired_is_a_503(rig_client) -> None:  # type: ignore[no-untyped-def]
    _, c = rig_client
    c._transport.app.state.vitals = None  # type: ignore[attr-defined]

    assert (await c.get("/v1/vitals")).status_code == 503


async def test_manual_storage_trouble_still_answers_the_board(rig_client) -> None:  # type: ignore[no-untyped-def]
    """R5.1 D2 (was a whole-board 503): the automatic items come back with a plain note."""
    rig, c = rig_client

    async def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        from jarvis.vitals.store import VitalsUnavailable

        raise VitalsUnavailable("try later")

    rig.store.list_manual = boom  # type: ignore[method-assign]

    r = await c.get("/v1/vitals")

    body = r.json()
    assert r.status_code == 200 and body["manual_unavailable"] is True
    assert [i["id"] for i in body["items"]] == ["ai_spend"] and "try later" not in r.text
