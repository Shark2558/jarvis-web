# tests/test_google_connector.py — slice 6: token refresh, needs_reconnect, revoke, API errors
from __future__ import annotations

import json

import httpx
import pytest
from google_fakes import FakeGoogle
from google_fakes import google_tokens as _tokens

from jarvis.integrations.google import (
    REQUIRED_SCOPES,
    REVOKE_URL,
    TOKEN_URL,
    GoogleAPIError,
    GoogleConflict,
    GoogleConnector,
    GoogleInvalid,
    GoogleNotConnected,
    GoogleQuotaExceeded,
    GoogleScopesMissing,
    GoogleUncertain,
)
from jarvis.integrations.vault import MemoryTokenStore

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
    fake.on("GET", CAL + "/x", httpx.Response(429), httpx.Response(429))
    with pytest.raises(GoogleAPIError) as ei:
        await conn.request(UID, "GET", CAL + "/x")
    assert len(fake.requests) == 2 and "rate" in str(ei.value).lower()


# ---- security review L2: a write is never sent twice by a retry ------------------------------

SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
FREEBUSY = "https://www.googleapis.com/calendar/v3/freeBusy"


@pytest.mark.parametrize(
    "method, url, status",
    [
        ("POST", SEND, 503),  # messages.send may have gone out before the 503
        ("POST", CAL, 500),  # events.insert
        ("PATCH", CAL + "/abcde", 502),
        ("DELETE", CAL + "/abcde", 429),
    ],
)
async def test_unsafe_calls_are_not_retried(
    conn: GoogleConnector,
    store: MemoryTokenStore,
    fake: FakeGoogle,
    method: str,
    url: str,
    status: int,
) -> None:
    await store.put(UID, _tokens())
    fake.on(method, url, httpx.Response(status), httpx.Response(200, json={"id": "twice"}))
    with pytest.raises(GoogleAPIError):
        await conn.request(UID, method, url, json={} if method != "DELETE" else None)
    assert len(fake.requests) == 1


async def test_read_only_post_can_opt_into_one_retry(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("POST", FREEBUSY, httpx.Response(503), httpx.Response(200, json={"ok": 1}))
    assert await conn.request(UID, "POST", FREEBUSY, json={}, retry_safe=True) == {"ok": 1}
    assert len(fake.requests) == 2


async def test_a_retry_that_never_got_through_after_an_answer_is_not_never_sent(
    conn: GoogleConnector, store: MemoryTokenStore
) -> None:
    """Code review CR-4: the first attempt got a 503 (Google answered), the retry could not
    connect: Google WAS reached, so the call is not "never sent" (its unit is not given back)."""
    from jarvis.integrations.google import never_sent

    await store.put(UID, _tokens())
    answers: list[int | None] = [503, None]

    def handler(request: httpx.Request) -> httpx.Response:
        status = answers.pop(0)
        if status is None:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(status)

    conn.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GoogleUncertain) as ei:
        await conn.request(UID, "GET", CAL)
    assert never_sent(ei.value) is False

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    conn.http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    with pytest.raises(GoogleUncertain) as ei:
        await conn.request(UID, "GET", CAL, send_once=True)
    assert never_sent(ei.value) is True  # one attempt, and it never connected


async def test_send_once_sends_exactly_one_request_and_refreshes_without_resending(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("GET", CAL, httpx.Response(503), httpx.Response(200, json={"ok": 1}))
    with pytest.raises(GoogleUncertain):
        await conn.request(UID, "GET", CAL, send_once=True)
    assert len(fake.requests) == 1
    fake.requests.clear()
    fake.on("GET", CAL + "/x", httpx.Response(401), httpx.Response(200, json={"ok": 2}))
    fake.on("POST", TOKEN_URL, httpx.Response(200, json={"access_token": "n2", "expires_in": 999}))
    with pytest.raises(GoogleAPIError) as ei:
        await conn.request(UID, "GET", CAL + "/x", send_once=True)
    assert "again" in str(ei.value).lower()
    assert [r.method for r in fake.requests] == ["GET", "POST"]  # sent once, then the refresh
    assert await conn.request(UID, "GET", CAL + "/x", send_once=True) == {"ok": 2}
    assert fake.requests[-1].headers["authorization"] == "Bearer n2"


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


async def test_a_lost_answer_is_uncertain_and_a_duplicate_or_bad_request_has_its_own_class(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    """Slice 11 fix: a change Google may or may not have made (no answer, a 5xx) is
    `GoogleUncertain`, so a delete can be checked by reading the item again; a 409 (an id that
    already exists) and a 400 are told apart. All stay `GoogleAPIError` with plain words."""
    await store.put(UID, _tokens())
    fake.on("DELETE", CAL + "/e1", httpx.Response(503, json={"error": {"message": "x-secret"}}))
    with pytest.raises(GoogleUncertain) as e1:
        await conn.request(UID, "DELETE", CAL + "/e1")
    assert isinstance(e1.value, GoogleAPIError) and "x-secret" not in str(e1.value)
    fake.on("POST", CAL, httpx.Response(409, json={"error": {"message": "duplicate"}}))
    with pytest.raises(GoogleConflict):
        await conn.request(UID, "POST", CAL, json={})
    fake.on("POST", CAL + "/x", httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(GoogleInvalid):
        await conn.request(UID, "POST", CAL + "/x", json={})

    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer")

    conn.http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    with pytest.raises(GoogleUncertain):
        await conn.request(UID, "DELETE", CAL + "/e1")


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
            "scope": "openid " + " ".join(REQUIRED_SCOPES),
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


# ---- security review M3: the link needs every tool scope ------------------------------------


def test_required_scopes_drop_the_redundant_gmail_send() -> None:
    from jarvis.integrations.google import TOOL_SCOPES

    # gmail.compose already permits messages.send (Google's users.messages.send scope list)
    assert "https://www.googleapis.com/auth/gmail.send" not in TOOL_SCOPES
    assert set(REQUIRED_SCOPES) == {
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    }
    assert set(REQUIRED_SCOPES) <= set(TOOL_SCOPES)


def test_gmail_insert_is_requested_but_never_required() -> None:
    from jarvis.integrations.google import INSERT_SCOPE, OPTIONAL_SCOPES, TOOL_SCOPES, can_insert

    assert INSERT_SCOPE == "https://www.googleapis.com/auth/gmail.insert"
    assert INSERT_SCOPE in OPTIONAL_SCOPES and INSERT_SCOPE in TOOL_SCOPES
    assert INSERT_SCOPE not in REQUIRED_SCOPES
    assert set(TOOL_SCOPES) == {"openid", "email", *REQUIRED_SCOPES, *OPTIONAL_SCOPES}
    assert can_insert([INSERT_SCOPE]) and can_insert(["https://mail.google.com/"])
    assert can_insert(["https://www.googleapis.com/auth/gmail.modify"])
    assert not can_insert(REQUIRED_SCOPES) and not can_insert([])


def test_the_tasks_scope_is_requested_but_never_required() -> None:
    """Slice 10 C: the to-do list is optional like gmail.insert; read-only Tasks is not enough
    (the to-do tools write)."""
    from jarvis.integrations.google import (
        OPTIONAL_SCOPES,
        TASKS_SCOPE,
        TOOL_SCOPES,
        can_use_tasks,
    )

    assert TASKS_SCOPE == "https://www.googleapis.com/auth/tasks"
    # slice 12 D7: contacts and YouTube playlists are optional Grants too (tests/test_google_grants)
    assert OPTIONAL_SCOPES[:2] == (
        "https://www.googleapis.com/auth/gmail.insert",
        TASKS_SCOPE,
    )
    assert TASKS_SCOPE in TOOL_SCOPES and TASKS_SCOPE not in REQUIRED_SCOPES
    assert can_use_tasks([*REQUIRED_SCOPES, TASKS_SCOPE])
    assert not can_use_tasks(REQUIRED_SCOPES)
    assert not can_use_tasks(["https://www.googleapis.com/auth/tasks.readonly"])


async def test_a_link_without_the_tasks_scope_stays_connected(
    conn: GoogleConnector, store: MemoryTokenStore
) -> None:
    await conn.save(
        UID,
        email="akash@example.com",
        token={
            "access_token": "a1",
            "refresh_token": "r1",
            "expires_in": 3600,
            "scope": "openid email https://www.googleapis.com/auth/gmail.insert "
            + " ".join(REQUIRED_SCOPES),
        },
    )
    st = await conn.status(UID)
    assert st["connected"] is True and st["needs_reconnect"] is False


async def test_a_link_without_gmail_insert_stays_connected(
    conn: GoogleConnector, store: MemoryTokenStore
) -> None:
    """Slice 7 added an optional scope: links made before it (or with it unticked) keep every
    slice 6 tool."""
    await conn.save(
        UID,
        email="akash@example.com",
        token={
            "access_token": "a1",
            "refresh_token": "r1",
            "expires_in": 3600,
            "scope": "openid email " + " ".join(REQUIRED_SCOPES),
        },
    )
    st = await conn.status(UID)
    assert st["connected"] is True and st["needs_reconnect"] is False
    assert "https://www.googleapis.com/auth/gmail.insert" not in st["scopes"]


async def test_save_refuses_a_partial_grant(conn: GoogleConnector, store: MemoryTokenStore) -> None:
    partial = [s for s in REQUIRED_SCOPES if "gmail.compose" not in s]
    with pytest.raises(GoogleScopesMissing) as ei:
        await conn.save(
            UID,
            email="akash@example.com",
            token={
                "access_token": "a1",
                "refresh_token": "r1",
                "expires_in": 3600,
                "scope": "openid email " + " ".join(partial),
            },
        )
    assert "gmail.compose" in str(ei.value)
    assert await store.get(UID) is None


async def test_revoke_is_best_effort(conn: GoogleConnector, fake: FakeGoogle) -> None:
    fake.on("POST", REVOKE_URL, httpx.Response(200))
    await conn.revoke("tok-1")
    assert dict(httpx.QueryParams(fake.requests[0].content.decode()))["token"] == "tok-1"

    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    conn.http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    await conn.revoke("tok-2")  # never raises
    await conn.revoke("")  # nothing to revoke: no request


# ---- slice 12 final review: quota words per service ------------------------------------------

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
CAL_EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
YT_ITEMS = "https://www.googleapis.com/youtube/v3/playlistItems"


def _quota_403(reason: str) -> httpx.Response:
    body = {"error": {"code": 403, "message": "VENDOR", "errors": [{"reason": reason}]}}
    return httpx.Response(403, json=body)


@pytest.mark.parametrize(("method", "url"), [("POST", CAL_EVENTS), ("GET", GMAIL)])
async def test_a_calendar_or_gmail_quota_answer_is_neutral_never_youtubes_pacific_midnight(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle, method: str, url: str
) -> None:
    await store.put(UID, _tokens())
    fake.on(method, url, _quota_403("quotaExceeded"), _quota_403("quotaExceeded"))
    with pytest.raises(GoogleAPIError) as ei:
        await conn.request(UID, method, url)
    said = str(ei.value)
    assert said == "Google is limiting requests for now; try again later."
    assert "Pacific" not in said and "allowance" not in said and "VENDOR" not in said


@pytest.mark.parametrize(("method", "url"), [("POST", CAL_EVENTS), ("GET", GMAIL)])
async def test_a_calendar_or_gmail_rate_limit_still_says_try_again_shortly(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle, method: str, url: str
) -> None:
    await store.put(UID, _tokens())
    fake.on(method, url, _quota_403("rateLimitExceeded"), _quota_403("rateLimitExceeded"))
    with pytest.raises(GoogleAPIError) as ei:
        await conn.request(UID, method, url)
    assert "try again shortly" in str(ei.value) and "Pacific" not in str(ei.value)


async def test_youtube_on_the_owners_token_keeps_the_pacific_midnight_words(
    conn: GoogleConnector, store: MemoryTokenStore, fake: FakeGoogle
) -> None:
    await store.put(UID, _tokens())
    fake.on("GET", YT_ITEMS, _quota_403("quotaExceeded"), _quota_403("quotaExceeded"))
    with pytest.raises(GoogleQuotaExceeded) as ei:
        await conn.request(UID, "GET", YT_ITEMS)
    assert "midnight Pacific" in str(ei.value) and ei.value.period == "day"
