# tests/test_kb_api.py -- R2 C: /v1/notes over HTTP: owner-only, shapes, error codes, export/import.
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from kb_fakes import Rig, build_rig, scan
from pydantic import SecretStr
from starlette.middleware.sessions import SessionMiddleware

from jarvis.api.notes import install_notes
from jarvis.config import Settings
from jarvis.kb.models import IMPORT_MAX_BYTES

BEARER = {"Authorization": "Bearer cli-token"}
VIEW_KEYS = {
    "id",
    "kind",
    "title",
    "text",
    "tags",
    "origin",
    "created_at",
    "updated_at",
    "url",
    "host",
    "owner_note",
    "page",
    "trusted",
    "snippet",
}


def make_app(settings: Settings, rig: Rig | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="x" * 32)
    app.state.settings = settings
    app.state.notes = rig.svc if rig is not None else None
    install_notes(app)
    return app


@pytest.fixture
def s(settings: Settings) -> Settings:
    return settings.model_copy(update={"api_token": SecretStr("cli-token")})


@pytest.fixture
async def rig() -> Rig:
    return build_rig()


@pytest.fixture
async def c(s: Settings, rig: Rig) -> AsyncIterator[AsyncClient]:
    app = make_app(s, rig)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.headers.update(BEARER)
        yield client


async def post(c: AsyncClient, **body: Any) -> dict[str, Any]:
    r = await c.post("/v1/notes", json=body)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_requires_sign_in(s: Settings, rig: Rig) -> None:
    app = make_app(s, rig)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        assert (await anon.get("/v1/notes")).status_code == 401
        assert (await anon.post("/v1/notes", json={"kind": "note", "text": "x"})).status_code == 401


async def test_add_list_search_patch_delete_round_trip(c: AsyncClient, rig: Rig) -> None:
    n = await post(c, kind="note", text="The plumber is Ravi, comes on Tuesdays.", tags=["Home"])
    assert set(n) == VIEW_KEYS and n["origin"] == "typed" and n["trusted"] is True
    assert n["tags"] == ["home"]
    page = (await c.get("/v1/notes")).json()
    assert page["total"] == 1 and page["available"] is True and page["counts"]["note"] == 1
    hit = (await c.get("/v1/notes", params={"q": "who is the plumber"})).json()
    assert [x["id"] for x in hit["items"]] == [n["id"]] and "plumber" in hit["items"][0]["snippet"]
    patched = (
        await c.patch(f"/v1/notes/{n['id']}", json={"text": "Plumber is Suresh now."})
    ).json()
    assert patched["text"] == "Plumber is Suresh now."
    d = await c.delete(f"/v1/notes/{n['id']}")
    assert (
        d.status_code == 200
        and d.json()["kind"] == "note"
        and d.json()["undo_id"].startswith("del_")
    )
    assert (await c.get("/v1/notes")).json()["total"] == 0
    restored = await rig.undo.restore("owner", d.json()["undo_id"])
    assert restored.new_id == n["id"]


async def test_a_memo_is_stored_as_reviewed_and_a_link_keeps_its_host(c: AsyncClient) -> None:
    memo = await post(c, kind="memo", text="Remember to call the bank tomorrow")
    assert memo["origin"] == "memo" and memo["trusted"] is True
    link = await post(c, kind="link", url="https://www.bücher.example/x", owner_note="good")
    assert link["host"] == "xn--bcher-kva.example" and link["page"] is None
    only = (await c.get("/v1/notes", params={"kind": "link"})).json()
    assert [x["id"] for x in only["items"]] == [link["id"]]


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"kind": "note", "text": "card 4111 1111 1111 1111"}, 422, "sensitive"),
        ({"kind": "link", "url": "http://example.com/"}, 422, "bad_url"),
        ({"kind": "link", "url": "javascript:alert(1)"}, 422, "bad_url"),
        ({"kind": "note", "text": "   "}, 422, "input_rejected"),
        ({"kind": "note", "text": "x" * 4001}, 422, None),
        ({"kind": "bogus", "text": "x"}, 422, None),
        ({"kind": "note", "text": "x", "origin": "typed"}, 422, None),  # no client-set origin
    ],
)
async def test_bad_writes_are_refused_with_plain_codes(
    c: AsyncClient, body: dict[str, Any], status: int, code: str | None
) -> None:
    r = await c.post("/v1/notes", json=body)
    assert r.status_code == status
    if code:
        assert r.json()["error"] == code and r.json()["detail"]
        assert "4111" not in r.text
    assert (await c.get("/v1/notes")).json()["total"] == 0


async def test_unknown_and_malformed_ids_are_404(c: AsyncClient) -> None:
    for nid in ("n_000000000000", "bogus"):
        assert (await c.patch(f"/v1/notes/{nid}", json={"title": "x"})).status_code == 404
        assert (await c.delete(f"/v1/notes/{nid}")).status_code == 404
        assert (
            await c.post(f"/v1/notes/{nid}/fetch", json={"confirm_credit": True})
        ).status_code == 404


async def test_the_live_limit_answers_409(c: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from jarvis.kb import service

    monkeypatch.setattr(service, "MAX_LIVE", 1)
    await post(c, kind="note", text="one")
    r = await c.post("/v1/notes", json={"kind": "note", "text": "two"})
    assert r.status_code == 409 and r.json()["error"] == "notes_full"


async def test_fetch_needs_the_credit_confirmation_and_stores_the_excerpt(
    c: AsyncClient, rig: Rig
) -> None:
    link = await post(c, kind="link", url="https://example.com/story")
    rig.fake.pages["https://example.com/story"] = "Story\n\nsome page words"
    no = await c.post(f"/v1/notes/{link['id']}/fetch", json={"confirm_credit": False})
    assert no.status_code == 422 and rig.fake.requests == []
    ok = await c.post(f"/v1/notes/{link['id']}/fetch", json={"confirm_credit": True})
    assert ok.status_code == 200
    body = ok.json()
    assert "page words" in body["page"]["excerpt"] and body["trusted"] is False
    assert (await rig.allowance.usage()).credits == 1


async def test_fetch_errors_use_the_documented_codes(s: Settings) -> None:
    off = build_rig(with_web=False)
    app = make_app(s, off)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.headers.update(BEARER)
        link = await post(c, kind="link", url="https://example.com/story")
        r = await c.post(f"/v1/notes/{link['id']}/fetch", json={"confirm_credit": True})
        assert r.status_code == 409 and r.json()["error"] == "web_off"
        text = await post(c, kind="note", text="not a link")
        r2 = await c.post(f"/v1/notes/{text['id']}/fetch", json={"confirm_credit": True})
        assert r2.status_code == 422


async def test_private_links_are_refused_at_save_with_a_reason(c: AsyncClient, rig: Rig) -> None:
    for url in (
        "https://example.com/u?email=ravi@example.com",
        "https://aadhaar-123456789012.x.example/",
    ):
        r = await c.post("/v1/notes", json={"kind": "link", "url": url})
        assert r.status_code == 422
        assert r.json()["error"] == "bad_url" and r.json()["reason"] == "private"
    assert rig.fake.requests == []


async def test_export_and_import_round_trip(c: AsyncClient, rig: Rig) -> None:
    a = await post(c, kind="note", text="first words", tags=["x"])
    await post(c, kind="link", url="https://example.com/a", owner_note="why")
    r = await c.get("/v1/notes/export")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith('attachment; filename="jarvis-notes-')
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert len(data["notes"]) == 2
    for n in [*(await c.get("/v1/notes")).json()["items"]]:
        await c.delete(f"/v1/notes/{n['id']}")
    await rig.svc.wipe("owner")
    imp = await c.post("/v1/notes/import", json={"data": data})
    assert imp.status_code == 200 and imp.json() == {"added": 2, "skipped": 0}
    assert (await c.get("/v1/notes")).json()["items"][0]["id"] in {a["id"], data["notes"][1]["id"]}
    bad = await c.post("/v1/notes/import", json={"data": {"format": "other", "notes": []}})
    assert bad.status_code == 422
    nonsense = await c.post("/v1/notes/import", content=b"not json")
    assert nonsense.status_code == 422


async def test_import_over_two_megabytes_is_413_before_reading(c: AsyncClient) -> None:
    big = json.dumps({"data": {"format": "jarvis-notes", "notes": ["x" * IMPORT_MAX_BYTES]}})
    r = await c.post("/v1/notes/import", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"] == "too_large"


async def test_import_applies_the_sensitive_filter(c: AsyncClient) -> None:
    data = {
        "format": "jarvis-notes",
        "version": 1,
        "notes": [
            {
                "id": "n_0000000000aa",
                "kind": "note",
                "title": "t",
                "text": "card 4111 1111 1111 1111",
                "origin": "typed",
                "created_at": "2026-11-01T00:00:00Z",
                "updated_at": "2026-11-01T00:00:00Z",
            }
        ],
    }
    r = await c.post("/v1/notes/import", json={"data": data})
    assert r.json() == {"added": 0, "skipped": 1}


async def test_without_a_key_the_list_says_why_and_writes_are_503(s: Settings) -> None:
    app = make_app(s, None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.headers.update(BEARER)
        r = await c.get("/v1/notes")
        assert r.status_code == 200
        assert r.json()["available"] is False and "no encryption key" in r.json()["reason"]
        w = await c.post("/v1/notes", json={"kind": "note", "text": "x"})
        assert w.status_code == 503 and w.json()["error"] == "notes_off"


async def test_nothing_readable_reaches_firestore_through_the_api(c: AsyncClient, rig: Rig) -> None:
    await post(c, kind="note", text="secret plumber ZZNEEDLE", tags=["tagneedle"])
    assert scan(rig.docs, "ZZNEEDLE", "tagneedle", "plumber") == []
