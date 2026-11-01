# tests/test_memory_api.py — slice 8 §5: /v1/memory/* (owner-only, CSRF on cookie writes, exact
# shapes and error codes), and memory_used on chat replies and the stream's final event.
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.recall.models import IMPORT_MAX_BYTES, MAX_ACTIVE

OWNER = "akash@example.com"
OTHER = "partner@example.com"
UID = user_id_for_email(OWNER)
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
VIEW_KEYS = {"settings", "profile", "facts", "counts", "learn_cost_note_inr", "runs_today"}
FACT_KEYS = {
    "id",
    "text",
    "category",
    "keywords",
    "origin",
    "pinned",
    "confidence",
    "source",
    "created_at",
    "updated_at",
    "last_used_at",
    "use_count",
    "replaced_by",
    "replaced_at",
}
STREAM_FINAL = "\x1e"


@pytest.fixture
def gsettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER, OTHER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "token_key": SecretStr(KEY_B64),
        }
    )


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
async def gc(gsettings: Settings, provider: MockProvider) -> AsyncIterator[AsyncClient]:
    app = create_app(gsettings, provider=provider, store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def _login(c: AsyncClient, email: str) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=a&state=b")).status_code in (302, 307)


async def _add(c: AsyncClient, text: str, category: str = "preferences") -> dict[str, Any]:
    r = await c.post("/v1/memory/facts", json={"text": text, "category": category}, headers=BEARER)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


# ---- auth + CSRF ---------------------------------------------------------------------------------


async def test_every_route_needs_the_owner(gc: AsyncClient) -> None:
    for method, path, body in (
        ("GET", "/v1/memory", None),
        ("PUT", "/v1/memory/settings", {"use": False}),
        ("PUT", "/v1/memory/profile/about", {"text": "x"}),
        ("POST", "/v1/memory/facts", {"text": "x", "category": "other"}),
        ("PATCH", "/v1/memory/facts/mabc123", {"pinned": True}),
        ("DELETE", "/v1/memory/facts/mabc123", None),
        ("GET", "/v1/memory/export", None),
        ("POST", "/v1/memory/import", {"data": {}}),
        ("DELETE", "/v1/memory", {"confirm": "FORGET"}),
    ):
        r = await gc.request(method, path, json=body, headers=CSRF)
        assert r.status_code == 401, (method, path)


async def test_cookie_writes_need_the_csrf_header(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    r = await gc.put("/v1/memory/settings", json={"use": False})
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = await gc.post("/v1/memory/facts", json={"text": "Prefers tea", "category": "preferences"})
    assert r.status_code == 403
    r = await gc.put("/v1/memory/settings", json={"use": False}, headers=CSRF)
    assert r.status_code == 200 and r.json()["use"] is False
    assert (await gc.get("/v1/memory")).status_code == 200  # reads need no header


async def test_each_owner_has_their_own_memory_and_client_user_id_is_ignored(
    gc: AsyncClient,
) -> None:
    await _login(gc, OTHER)
    r = await gc.post(
        "/v1/memory/facts",
        json={"text": "Prefers coffee", "category": "preferences", "user_id": UID},
        headers=CSRF,
    )
    assert r.status_code == 200
    svc = gc.app.state.memory  # type: ignore[attr-defined]
    assert (await svc.view(UID)).facts == []
    assert [f.text for f in (await svc.view(user_id_for_email(OTHER))).facts] == ["Prefers coffee"]


# ---- shapes ----------------------------------------------------------------------------------


async def test_get_memory_shape(gc: AsyncClient) -> None:
    await _add(gc, "Prefers window seats")
    body = (await gc.get("/v1/memory", headers=BEARER)).json()
    assert set(body) == VIEW_KEYS
    assert set(body["settings"]) == {"use", "learn", "learn_consented_at"}
    assert body["settings"]["use"] is True and body["settings"]["learn"] is False
    assert set(body["profile"]) == {"about", "preferences", "people", "work"}
    assert body["counts"] == {"active": 1, "replaced": 0, "limit": MAX_ACTIVE}
    assert set(body["facts"][0]) == FACT_KEYS
    assert body["facts"][0]["origin"] == "added" and body["facts"][0]["pinned"] is True
    assert body["runs_today"] == 0
    note = body["learn_cost_note_inr"]
    assert isinstance(note, str) and "₹" in note and "$" not in note and len(note) <= 300


# ---- settings ------------------------------------------------------------------------------------


async def test_learn_needs_confirm_spend(gc: AsyncClient) -> None:
    r = await gc.put("/v1/memory/settings", json={"learn": True}, headers=BEARER)
    assert r.status_code == 409 and r.json()["error"] == "consent_required"
    assert "₹" in r.json()["detail"] or "cost" in r.json()["detail"].lower()
    r = await gc.put(
        "/v1/memory/settings", json={"learn": True, "confirm_spend": True}, headers=BEARER
    )
    assert r.status_code == 200
    body = r.json()
    assert body["learn"] is True and body["learn_consented_at"] is not None


async def test_settings_reject_wrong_types(gc: AsyncClient) -> None:
    r = await gc.put("/v1/memory/settings", json={"use": "yes"}, headers=BEARER)
    assert r.status_code == 422


# ---- profile ----------------------------------------------------------------------------------


async def test_profile_blocks(gc: AsyncClient) -> None:
    r = await gc.put(
        "/v1/memory/profile/about", json={"text": "Akash\nProject lead"}, headers=BEARER
    )
    assert r.status_code == 200 and r.json()["about"] == "Akash\nProject lead"
    assert set(r.json()) == {"about", "preferences", "people", "work"}
    r = await gc.put("/v1/memory/profile/secrets", json={"text": "x"}, headers=BEARER)
    assert r.status_code == 404
    r = await gc.put("/v1/memory/profile/work", json={"text": "x" * 1001}, headers=BEARER)
    assert r.status_code == 422
    r = await gc.put(
        "/v1/memory/profile/work", json={"text": "Salary a/c no 50100123456789"}, headers=BEARER
    )
    assert r.status_code == 422 and r.json()["error"] == "sensitive"
    assert "50100123456789" not in r.text


# ---- facts --------------------------------------------------------------------------------------


async def test_add_edit_delete_fact(gc: AsyncClient) -> None:
    f = await _add(gc, "Prefers tea", "preferences")
    assert set(f) == FACT_KEYS and f["id"].startswith("m") and f["origin"] == "added"
    r = await gc.patch(
        f"/v1/memory/facts/{f['id']}",
        json={"text": "Prefers green tea", "pinned": False},
        headers=BEARER,
    )
    assert r.status_code == 200
    assert r.json()["text"] == "Prefers green tea" and r.json()["pinned"] is False
    assert (
        await gc.patch("/v1/memory/facts/mnope1", json={"pinned": True}, headers=BEARER)
    ).status_code == 404
    assert (await gc.delete(f"/v1/memory/facts/{f['id']}", headers=BEARER)).status_code == 204
    assert (await gc.delete(f"/v1/memory/facts/{f['id']}", headers=BEARER)).status_code == 404
    assert (await gc.get("/v1/memory", headers=BEARER)).json()["facts"] == []


async def test_fact_errors(gc: AsyncClient) -> None:
    r = await gc.post(
        "/v1/memory/facts", json={"text": "My PIN is 4521", "category": "other"}, headers=BEARER
    )
    assert r.status_code == 422 and r.json()["error"] == "sensitive" and "4521" not in r.text
    r = await gc.post("/v1/memory/facts", json={"text": "x", "category": "secrets"}, headers=BEARER)
    assert r.status_code == 422
    r = await gc.post(
        "/v1/memory/facts", json={"text": "x" * 301, "category": "other"}, headers=BEARER
    )
    assert r.status_code == 422
    f = await _add(gc, "Prefers tea")
    r = await gc.patch(f"/v1/memory/facts/{f['id']}", json={"text": "OTP 482913"}, headers=BEARER)
    assert r.status_code == 422 and r.json()["error"] == "sensitive"


async def test_memory_full_is_409(gc: AsyncClient) -> None:
    svc = gc.app.state.memory  # type: ignore[attr-defined]
    for i in range(MAX_ACTIVE):
        await svc.add_fact(UID, f"note {i} about topic t{i}", "other")
    r = await gc.post(
        "/v1/memory/facts", json={"text": "one more", "category": "other"}, headers=BEARER
    )
    assert r.status_code == 409 and r.json()["error"] == "memory_full"
    assert "delete some" in r.json()["detail"].lower()


# ---- export / import / forget ------------------------------------------------------------------


async def test_export_forget_import_round_trip(gc: AsyncClient) -> None:
    await _add(gc, "Prefers tea", "preferences")
    await _add(gc, "Daughter is Anaya", "people")
    await gc.put("/v1/memory/profile/about", json={"text": "Akash"}, headers=BEARER)
    before = (await gc.get("/v1/memory", headers=BEARER)).json()
    r = await gc.get("/v1/memory/export", headers=BEARER)
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment;") and "jarvis-memory-" in cd and cd.endswith('.json"')
    exported = r.json()
    r = await gc.request("DELETE", "/v1/memory", json={"confirm": "nope"}, headers=BEARER)
    assert r.status_code == 422
    r = await gc.request("DELETE", "/v1/memory", json={"confirm": "FORGET"}, headers=BEARER)
    assert r.status_code == 204
    gone = (await gc.get("/v1/memory", headers=BEARER)).json()
    assert gone["facts"] == [] and gone["profile"]["about"] == ""
    r = await gc.post("/v1/memory/import", json={"data": exported}, headers=BEARER)
    assert r.status_code == 200 and r.json() == {"added": 2, "skipped": 0}
    after = (await gc.get("/v1/memory", headers=BEARER)).json()
    key = lambda v: sorted((f["text"], f["category"], tuple(f["keywords"])) for f in v["facts"])  # noqa: E731
    assert key(after) == key(before) and after["profile"] == before["profile"]
    r = await gc.post("/v1/memory/import", json={"data": exported}, headers=BEARER)
    assert r.json() == {"added": 0, "skipped": 2}


async def test_import_limits(gc: AsyncClient) -> None:
    big = {"data": {"version": 1, "facts": [{"text": "x" * 200, "category": "other"}] * 3000}}
    assert len(json.dumps(big)) > IMPORT_MAX_BYTES
    r = await gc.post("/v1/memory/import", json=big, headers=BEARER)
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    r = await gc.post("/v1/memory/import", json={"data": "nope"}, headers=BEARER)
    assert r.status_code == 422
    r = await gc.post(
        "/v1/memory/import",
        json={"data": {"version": 1, "facts": [{"text": "CVV 123", "category": "other"}]}},
        headers=BEARER,
    )
    assert r.json() == {"added": 0, "skipped": 1}


async def test_an_oversized_import_is_refused_from_its_content_length(gc: AsyncClient) -> None:
    """HIGH 2: the whole body was read before the size check."""
    r = await gc.post(
        "/v1/memory/import",
        content=b'{"data": {}}',
        headers={**BEARER, "Content-Length": str(IMPORT_MAX_BYTES + 1)},
    )
    assert r.status_code == 413 and r.json()["error"] == "too_large"

    async def chunks() -> AsyncIterator[bytes]:  # no Content-Length: counted while reading
        yield b'{"data": {"facts": ['
        for _ in range(IMPORT_MAX_BYTES // 1000 + 2):
            yield b'{"text": "' + b"y" * 970 + b'", "category": "other"},'
        yield b"{}]}}"

    r = await gc.post("/v1/memory/import", content=chunks(), headers=BEARER)
    assert r.status_code == 413 and r.json()["error"] == "too_large"


async def test_a_500_fact_round_trip_is_fast_and_identical(gc: AsyncClient) -> None:
    """HIGH 2: a 500-fact import held the event loop for ~14 s."""
    svc = gc.app.state.memory  # type: ignore[attr-defined]
    for i in range(MAX_ACTIVE):
        await svc.add_fact(
            UID, f"note {i} about topic t{i} and q{i * 7}", "other", keywords=[f"k{i}"]
        )
    exported = (await gc.get("/v1/memory/export", headers=BEARER)).json()
    r = await gc.request("DELETE", "/v1/memory", json={"confirm": "FORGET"}, headers=BEARER)
    assert r.status_code == 204
    t0 = time.perf_counter()
    r = await gc.post("/v1/memory/import", json={"data": exported}, headers=BEARER)
    assert time.perf_counter() - t0 < 1.0
    assert r.status_code == 200 and r.json() == {"added": MAX_ACTIVE, "skipped": 0}
    after = (await gc.get("/v1/memory", headers=BEARER)).json()
    key = lambda v: sorted((f["text"], tuple(f["keywords"])) for f in v["facts"])  # noqa: E731
    assert key(after) == key(exported)


async def test_an_import_over_1000_facts_is_422(gc: AsyncClient) -> None:
    facts = [{"text": f"n{i}", "category": "other"} for i in range(1_001)]
    r = await gc.post("/v1/memory/import", json={"data": {"facts": facts}}, headers=BEARER)
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"
    assert "1,000" in r.json()["detail"]


async def test_blank_or_invisible_text_is_422_input_rejected(gc: AsyncClient) -> None:
    """LOW 13: these were 500s."""
    r = await gc.post(
        "/v1/memory/facts", json={"text": "\u200b\u200b", "category": "other"}, headers=BEARER
    )
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"
    assert r.json()["detail"] == "A fact needs some text."
    f = await _add(gc, "Prefers tea")
    r = await gc.patch(f"/v1/memory/facts/{f['id']}", json={"text": "   \u200b "}, headers=BEARER)
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"


async def test_patch_on_a_replaced_fact_is_404(gc: AsyncClient) -> None:
    svc = gc.app.state.memory  # type: ignore[attr-defined]
    old = await svc.add_fact(UID, "Lives in Kochi", "places")
    state = await svc.store.load(UID)
    from jarvis.recall.ops import new_fact, replace_fact

    await svc.store.mutate(
        UID,
        lambda cur: replace_fact(
            cur,
            old.id,
            new_fact(cur, "Lives in Delhi", "places", origin="told", now=old.created_at),
            old.created_at,
        ),
    )
    assert state is not None
    r = await gc.patch(f"/v1/memory/facts/{old.id}", json={"pinned": False}, headers=BEARER)
    assert r.status_code == 404


async def test_import_never_switches_learning_on(gc: AsyncClient) -> None:
    data = {"version": 1, "settings": {"learn": True, "use": False}, "facts": []}
    await gc.post("/v1/memory/import", json={"data": data}, headers=BEARER)
    s = (await gc.get("/v1/memory", headers=BEARER)).json()["settings"]
    assert s["learn"] is False and s["use"] is True


# ---- chat ---------------------------------------------------------------------------------------


async def test_chat_reply_carries_memory_used(gc: AsyncClient, provider: MockProvider) -> None:
    f = await _add(gc, "Prefers window seats")
    r = await gc.post("/v1/chat", json={"message": "a seat please"}, headers=BEARER)
    assert r.status_code == 200
    assert r.json()["memory_used"] == [{"id": f["id"], "text": "Prefers window seats"}]


async def test_stream_ends_with_a_final_event(gc: AsyncClient, provider: MockProvider) -> None:
    f = await _add(gc, "Prefers window seats")
    provider.script("A window seat it is, Sir.")
    async with gc.stream(
        "POST", "/v1/chat/stream", json={"message": "a seat please"}, headers=BEARER
    ) as r:
        assert r.status_code == 200
        body = "".join([t async for t in r.aiter_text()])
    text, final = body.split(STREAM_FINAL)
    assert text.strip() == "A window seat it is, Sir."
    assert json.loads(final) == {"memory_used": [{"id": f["id"], "text": "Prefers window seats"}]}
