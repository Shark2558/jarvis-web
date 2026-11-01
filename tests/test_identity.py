# tests/test_identity.py — slice 5c: who the caller is comes from the sign-in, never the client.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import LEGACY_USER_ID, primary_user_id, user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.core.models import Session, Turn
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.base import SessionStore
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage import doc_storage
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.gateway import Gateway

A, B = "akash@example.com", "partner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}


@pytest.fixture
def two_owner_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [A, B],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    )


async def _client(app: Any) -> AsyncClient:
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    c.app = app  # type: ignore[attr-defined]
    return c


async def _login(c: AsyncClient, email: str) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    r = await c.get("/auth/callback?code=abc&state=x")
    assert r.status_code in (302, 307)


@pytest.fixture
async def deck(
    two_owner_settings: Settings, provider: MockProvider, gateway: Gateway
) -> AsyncIterator[tuple[AsyncClient, AsyncClient, AsyncClient, InMemorySessionStore]]:
    """Owner A's browser, owner B's browser, a bearer-token client — one app, one store."""
    store = InMemorySessionStore()
    app = create_app(two_owner_settings, provider=provider, store=store, gateway=gateway)
    async with app.router.lifespan_context(app):
        a, b, cli = await _client(app), await _client(app), await _client(app)
        await _login(a, A)
        await _login(b, B)
        try:
            yield a, b, cli, store
        finally:
            for c in (a, b, cli):
                await c.aclose()


# ---- the id itself ---------------------------------------------------------------------------


def test_user_id_is_stable_case_insensitive_and_hides_the_email() -> None:
    uid = user_id_for_email(" Akash@Example.com ")
    assert uid == user_id_for_email(A)
    assert uid.startswith("u_") and len(uid) == 18
    assert "akash" not in uid and "@" not in uid
    assert user_id_for_email(B) != uid


def test_primary_user_is_the_first_owner_or_legacy_without_owners(settings: Settings) -> None:
    assert primary_user_id(settings) == LEGACY_USER_ID == "owner"
    s = settings.model_copy(update={"owner_emails": [A, B]})
    assert primary_user_id(s) == user_id_for_email(A)


# ---- the API never trusts a client-supplied user_id ----------------------------------------


async def test_chat_is_stored_under_the_signed_in_owner_whatever_the_body_says(
    deck: Any, provider: MockProvider
) -> None:
    a, _, _, store = deck
    provider.script("Morning, Sir.")
    r = await a.post("/v1/chat", json={"message": "hi", "user_id": "someone-else"}, headers=CSRF)
    assert r.status_code == 200
    s = await store.get(r.json()["session_id"])
    assert s is not None and s.user_id == user_id_for_email(A)


async def test_owners_cannot_see_or_touch_each_others_conversations(
    deck: Any, provider: MockProvider
) -> None:
    a, b, _, _ = deck
    provider.script("Hello A.")
    sid = (await a.post("/v1/chat", json={"message": "mine"}, headers=CSRF)).json()["session_id"]
    uid_a = user_id_for_email(A)

    assert [x["id"] for x in (await a.get("/v1/sessions")).json()] == [sid]
    # B, even when naming A's id in the query string, sees nothing of A's
    assert (await b.get(f"/v1/sessions?user_id={uid_a}")).json() == []
    assert (await b.get(f"/v1/sessions/{sid}?user_id={uid_a}")).status_code == 404
    assert (await b.delete(f"/v1/sessions/{sid}?user_id={uid_a}", headers=CSRF)).status_code == 404
    # B cannot continue A's conversation either
    provider.script("nope")
    r = await b.post("/v1/chat", json={"message": "hijack", "session_id": sid}, headers=CSRF)
    assert r.status_code == 404
    assert (await a.get(f"/v1/sessions/{sid}")).status_code == 200


async def test_approvals_are_listed_and_decided_only_by_their_owner(
    deck: Any, provider: MockProvider
) -> None:
    a, b, _, _ = deck
    provider.script_tool_calls(
        [ToolCall(id="t1", name="send_message", arguments={"to": "x@y.com", "body": "hi"})],
        "Awaiting your approval, Sir.",
    )
    body = (await a.post("/v1/chat", json={"message": "send"}, headers=CSRF)).json()
    pid, sid = body["pending_approvals"][0]["id"], body["session_id"]

    assert [p["id"] for p in (await a.get("/v1/approvals")).json()] == [pid]
    assert (await b.get("/v1/approvals")).json() == []
    r = await b.post(
        f"/v1/approvals/{pid}/approve",
        json={"session_id": sid, "user_id": user_id_for_email(A)},
        headers=CSRF,
    )
    assert r.status_code == 404
    assert [p["id"] for p in (await a.get("/v1/approvals")).json()] == [pid]  # still waiting


async def test_bearer_token_acts_as_the_primary_owner(deck: Any, provider: MockProvider) -> None:
    a, _, cli, _ = deck
    provider.script("From the CLI.")
    sid = (await cli.post("/v1/chat", json={"message": "cli"}, headers=BEARER)).json()["session_id"]
    assert sid in [x["id"] for x in (await a.get("/v1/sessions")).json()]


# ---- conversations saved before this change move to the first owner, once -------------------


async def _legacy(store: SessionStore, sid: str, user_id: str = LEGACY_USER_ID) -> Session:
    s = Session(id=sid, user_id=user_id, turns=[Turn(role="user", content=f"hello {sid}")])
    await store.save(s)
    return s


@pytest.mark.parametrize("kind", ["memory", "docs"])
async def test_reassign_user_moves_only_that_users_sessions_and_is_idempotent(kind: str) -> None:
    store: SessionStore = (
        InMemorySessionStore() if kind == "memory" else doc_storage(MemoryDocs()).sessions
    )
    old1 = await _legacy(store, "s1")
    await _legacy(store, "s2")
    await _legacy(store, "s3", user_id="u_someoneelse0000")

    assert await store.reassign_user(LEGACY_USER_ID, "u_new") == 2
    assert await store.reassign_user(LEGACY_USER_ID, "u_new") == 0
    assert await store.list_for_user(LEGACY_USER_ID) == []
    assert sorted(x.id for x in await store.list_for_user("u_new")) == ["s1", "s2"]
    moved = await store.get("s1")
    assert moved is not None and moved.turns == old1.turns and moved.updated_at == old1.updated_at
    other = await store.get("s3")
    assert other is not None and other.user_id == "u_someoneelse0000"


async def test_startup_adopts_legacy_conversations_for_the_first_owner(
    two_owner_settings: Settings, provider: MockProvider
) -> None:
    store = InMemorySessionStore()
    await _legacy(store, "old1")
    app = create_app(two_owner_settings, provider=provider, store=store)
    async with app.router.lifespan_context(app):
        a = await _client(app)
        await _login(a, A)
        assert [x["id"] for x in (await a.get("/v1/sessions")).json()] == ["old1"]
        await a.aclose()


async def test_startup_survives_a_failing_adoption(
    two_owner_settings: Settings, provider: MockProvider
) -> None:
    class Broken(InMemorySessionStore):
        async def reassign_user(self, old: str, new: str) -> int:
            raise RuntimeError("database unavailable")

    app = create_app(two_owner_settings, provider=provider, store=Broken())
    async with app.router.lifespan_context(app):
        c = await _client(app)
        assert (await c.get("/health")).status_code == 200
        await c.aclose()
