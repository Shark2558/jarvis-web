# tests/test_google_connector.py — slice 6: token refresh, needs_reconnect, revoke, API errors
from __future__ import annotations

import json

import httpx
import pytest

from jarvis.integrations.google import (
    REVOKE_URL,
    TOKEN_URL,
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
)
from jarvis.integrations.vault import MemoryTokenStore
from tests.conftest import FakeGoogle
from tests.conftest import google_tokens as _tokens

NOW = 1_800_000_000.0
UID = "u_owner"


@pytest.fixture
def fake(fake_google: FakeGoogle) -> FakeGoogle:
    return fake_google


@pytest.fixture
def store(token_store: MemoryTokenStore) -> MemoryTokenStore:
    return token_store


@pytest.fixture
def conn(google_conn: GoogleConnector) -> GoogleConnector:
    return google_conn


# ---- status ---------------------------------------------------------------------------------


async def test_status_when_not_connected(conn: GoogleConnector) -> None:
    assert await conn.status(UID) == {
        "connected": False,
        "email": None,
        "scopes": [],
        "expires_at": None,
        "needs_reconnect": False,
    }


async def test_status_when_connected_never_contains_tokens(
    conn: GoogleConnector, store: MemoryTokenStore
) -> None:
    await store.put(UID, _tokens())
    st = await conn.status(UID)
    assert st["connected"] is True and st["email"] == "akash@example.com"
    assert st["expires_at"] == NOW + 3600 and st["needs_reconnect"] is False
    assert "old-access" not in json.dumps(st) and "the-refresh" not in json.dumps(st)


# ---- access tokens / refresh ----------------------------------------------------------------


async def test_access_token_requires_a_connection(conn: GoogleConnector) -> None:
    with pytest.raises(GoogleNotConnected) as ei:
        await conn.access_token(UID)
    assert "connect" in str(ei.value).lower()


async def test_fresh_token_is_used_without_refresh(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    assert await conn.access_token(UID) == "old-access"
    assert fake.requests == []


async def test_expiring_token_is_refreshed_and_persisted(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens(expires_at=NOW + 10))
    fake.on(
        "POST",
        TOKEN_URL,
        httpx.Response(200, json={"access_token": "new-access", "expires_in": 3599}),
    )
    assert await conn.access_token(UID) == "new-access"
    body = dict(httpx.QueryParams(fake.requests[0].content.decode()))
    assert body["grant_type"] == "refresh_token" and body["refresh_token"] == "the-refresh"
    assert body["client_id"] == "cid" and body["client_secret"] == "csecret"
    saved = await store.get(UID)
    assert saved is not None and saved.access_token.get_secret_value() == "new-access"
    assert saved.expires_at == NOW + 3599
    assert saved.refresh_token.get_secret_value() == "the-refresh"  # kept when Google omits it


async def test_invalid_grant_marks_needs_reconnect(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens(expires_at=NOW - 1))
    fake.on("POST", TOKEN_URL, httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(GoogleNotConnected) as ei:
        await conn.access_token(UID)
    assert "reconnect" in str(ei.value).lower()
    saved = await store.get(UID)
    assert saved is not None and saved.needs_reconnect is True
    assert (await conn.status(UID))["needs_reconnect"] is True
    # and nothing is attempted again until the owner reconnects
    with pytest.raises(GoogleNotConnected):
        await conn.access_token(UID)
    assert len(fake.requests) == 1


async def test_transient_refresh_failure_is_an_api_error_not_a_disconnect(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens(expires_at=NOW - 1))
    fake.on("POST", TOKEN_URL, httpx.Response(503, text="<html>upstream</html>"))
    with pytest.raises(GoogleAPIError) as ei:
        await conn.access_token(UID)
    assert "upstream" not in str(ei.value)  # vendor text never reaches the UI
    saved = await store.get(UID)
    assert saved is not None and saved.needs_reconnect is False


# ---- request --------------------------------------------------------------------------------

CAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


async def test_request_adds_bearer_and_parses_json(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("GET", CAL, httpx.Response(200, json={"items": [1]}))
    out = await conn.request(UID, "GET", CAL, params={"maxResults": 5})
    assert out == {"items": [1]}
    req = fake.requests[0]
    assert req.headers["authorization"] == "Bearer old-access"
    assert req.url.params["maxResults"] == "5"


async def test_request_retries_once_on_5xx_and_429(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("GET", CAL, httpx.Response(503), httpx.Response(200, json={"ok": 1}))
    assert await conn.request(UID, "GET", CAL) == {"ok": 1}
    fake.requests.clear()
    fake.on("DELETE", CAL, httpx.Response(429), httpx.Response(429))
    with pytest.raises(GoogleAPIError) as ei:
        await conn.request(UID, "DELETE", CAL)
    assert len(fake.requests) == 2 and "rate" in str(ei.value).lower()


async def test_request_refreshes_once_on_401(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("GET", CAL, httpx.Response(401), httpx.Response(200, json={"ok": 2}))
    fake.on("POST", TOKEN_URL, httpx.Response(200, json={"access_token": "n2", "expires_in": 100}))
    assert await conn.request(UID, "GET", CAL) == {"ok": 2}
    assert fake.requests[-1].headers["authorization"] == "Bearer n2"


async def test_request_maps_errors_to_friendly_text(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("GET", CAL, httpx.Response(404, json={"error": {"message": "Not Found: xyz-secret"}}))
    with pytest.raises(GoogleAPIError) as ei:
        await conn.request(UID, "GET", CAL)
    assert "xyz-secret" not in str(ei.value) and "not found" in str(ei.value).lower()
    fake.on(
        "GET",
        CAL + "/x",
        httpx.Response(403, json={"error": {"message": "insufficientPermissions"}}),
    )
    with pytest.raises(GoogleAPIError) as ei2:
        await conn.request(UID, "GET", CAL + "/x")
    assert "permission" in str(ei2.value).lower()


async def test_request_handles_empty_body_and_network_errors(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("DELETE", CAL + "/e1", httpx.Response(204))
    assert await conn.request(UID, "DELETE", CAL + "/e1") == {}

    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    conn.http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    with pytest.raises(GoogleAPIError) as ei:
        await conn.request(UID, "GET", CAL)
    assert "reach" in str(ei.value).lower()


# ---- save / disconnect ----------------------------------------------------------------------


async def test_save_from_oauth_token_response(
    conn: GoogleConnector, store: MemoryTokenStore
) -> None:
    await conn.save(
        UID,
        email="akash@example.com",
        token={
            "access_token": "a1",
            "refresh_token": "r1",
            "expires_at": int(NOW + 3000),
            "scope": "openid email https://www.googleapis.com/auth/gmail.readonly",
        },
    )
    saved = await store.get(UID)
    assert saved is not None and saved.refresh_token.get_secret_value() == "r1"
    assert "https://www.googleapis.com/auth/gmail.readonly" in saved.scopes
    assert saved.expires_at == NOW + 3000 and saved.needs_reconnect is False


async def test_save_without_refresh_token_is_refused(conn: GoogleConnector) -> None:
    with pytest.raises(ValueError):
        await conn.save(UID, email="a@b.c", token={"access_token": "a", "expires_in": 10})


async def test_disconnect_revokes_best_effort_and_deletes(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("POST", REVOKE_URL, httpx.Response(400, json={"error": "invalid_token"}))
    await conn.disconnect(UID)
    assert await store.get(UID) is None
    body = dict(httpx.QueryParams(fake.requests[0].content.decode()))
    assert body["token"] == "the-refresh"
    await conn.disconnect(UID)  # nothing connected: no request, no error
    assert len(fake.requests) == 1


async def test_unreadable_vault_entry_reads_as_not_connected(fake: FakeGoogle) -> None:
    """Key rotated or document tampered: the owner is told to reconnect, nothing crashes."""
    import os

    from pydantic import SecretStr

    from jarvis.integrations.vault import DocTokenStore
    from jarvis.storage.docs import MemoryDocs

    docs = MemoryDocs()
    await DocTokenStore(docs, key=os.urandom(32)).put(UID, _tokens())
    conn = GoogleConnector(
        DocTokenStore(docs, key=os.urandom(32)),  # a different key
        client_id="cid",
        client_secret=SecretStr("s"),
        http=fake.client(),
        now=lambda: NOW,
    )
    st = await conn.status(UID)
    assert st["connected"] is False and st["needs_reconnect"] is True
    with pytest.raises(GoogleNotConnected):
        await conn.access_token(UID)
    await conn.disconnect(UID)  # clears the unreadable entry
    assert await docs.get("jarvis_tokens/" + UID) is None
