# tests/test_api.py
from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["llm"] == "mock"
    assert "x-trace-id" in r.headers


async def test_chat_roundtrip_and_session_endpoints(
    client: AsyncClient, provider: MockProvider
) -> None:
    provider.script("At your service, Sir.")
    r = await client.post("/v1/chat", json={"message": "Hello"}, headers={"x-trace-id": "abc123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "At your service, Sir."
    assert body["trace_id"] == "abc123"
    sid = body["session_id"]

    r2 = await client.post("/v1/chat", json={"message": "Again", "session_id": sid})
    assert r2.json()["turn_count"] == 4

    lst = await client.get("/v1/sessions")
    assert [s["id"] for s in lst.json()] == [sid]

    full = await client.get(f"/v1/sessions/{sid}")
    assert len(full.json()["turns"]) == 4

    assert (await client.delete(f"/v1/sessions/{sid}")).status_code == 204
    assert (await client.get(f"/v1/sessions/{sid}")).status_code == 404


async def test_chat_stream(client: AsyncClient, provider: MockProvider) -> None:
    provider.script("Streamed reply, Sir.")
    async with client.stream("POST", "/v1/chat/stream", json={"message": "go"}) as r:
        assert r.status_code == 200
        body = "".join([chunk async for chunk in r.aiter_text()])
    # slice 8: the reply text, then one final event after an ASCII record separator
    text, final = body.split("\x1e")
    assert text.strip() == "Streamed reply, Sir."
    assert final == '{"memory_used": []}'


async def test_error_mapping(client: AsyncClient, provider: MockProvider) -> None:
    r = await client.post("/v1/chat", json={"message": "hi", "session_id": "sess_missing"})
    assert r.status_code == 404 and r.json()["error"] == "session_not_found"

    r = await client.post("/v1/chat", json={"message": "x" * 600})
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"

    provider.fail_next = 5  # exhaust every tier
    r = await client.post("/v1/chat", json={"message": "hi"})
    assert r.status_code == 503 and r.json()["error"] == "llm_unavailable"


async def test_bearer_auth_enforced_when_configured(settings: Settings) -> None:
    s = settings.model_copy(update={"api_token": SecretStr("s3cret")})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/health")).status_code == 200  # health stays open
            assert (await c.post("/v1/chat", json={"message": "hi"})).status_code == 401
            body = {"message": "hi"}
            bad = {"Authorization": "Bearer nope"}
            assert (await c.post("/v1/chat", json=body, headers=bad)).status_code == 401
            good = {"Authorization": "Bearer s3cret"}
            assert (await c.post("/v1/chat", json=body, headers=good)).status_code == 200


async def test_the_api_schema_and_its_pages_are_not_served(settings: Settings) -> None:
    """R6.1 security review L3: /openapi.json listed every route and the version to anyone, signed
    in or not (the docs pages were already off). All three are 404 now; `app.openapi()` still
    builds the schema in-process for the tests that read it."""
    s = settings.model_copy(update={"api_token": SecretStr("s3cret")})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            for path in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
                assert (await c.get(path)).status_code == 404, path
                signed_in = await c.get(path, headers={"Authorization": "Bearer s3cret"})
                assert signed_in.status_code == 404, path
    assert app.openapi_url is None  # FastAPI then mounts no docs pages either
    assert "/v1/chat" in app.openapi()["paths"]
