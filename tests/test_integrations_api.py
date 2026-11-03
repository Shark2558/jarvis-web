# tests/test_integrations_api.py — slice 6: /connect/google flow, /v1/integrations, wiring
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, SessionBackend, Settings
from jarvis.integrations.google import REVOKE_URL, TOOL_SCOPES
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage import build_storage
from jarvis.tools.setup import build_gateway

OWNER = "akash@example.com"
OTHER = "partner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


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


def _fake_consent(
    c: AsyncClient, email: str, *, refresh: bool = True, scopes: tuple[str, ...] = TOOL_SCOPES
) -> None:
    """Google's half of the tools consent: who consented, which tokens came back."""

    async def fake(request: Any) -> dict[str, Any]:
        tok: dict[str, Any] = {
            "access_token": "ya29.new",
            "expires_at": 1_900_000_000,
            "scope": " ".join(scopes),
            "userinfo": {"email": email, "email_verified": True, "sub": "1"},
        }
        if refresh:
            tok["refresh_token"] = "1//refresh"
        return tok

    c.app.state.oauth.google_tools.authorize_access_token = fake  # type: ignore[attr-defined]


@pytest.fixture
async def gc(gsettings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        c = await _client(app)
        try:
            yield c
        finally:
            await c.aclose()


# ---- wiring ---------------------------------------------------------------------------------


async def test_google_mode_registers_google_tools_and_drops_fake_twins(gc: AsyncClient) -> None:
    names = {s.name for s in gc.app.state.gateway.registry.specs()}  # type: ignore[attr-defined]
    assert {"calendar_list_events", "gmail_send", "gmail_search", "calendar_delete_event"} <= names
    assert "get_calendar" not in names and "send_message" not in names
    # slice 11 B: real reminders (Google Calendar) replace the in-memory demo one
    assert "create_reminder" not in names
    assert {"reminder_add", "reminders_list", "reminder_update"} <= names
    assert "list_tasks" in names  # harmless dev builtin stays


async def test_token_mode_has_no_google_tools_or_routes(client: AsyncClient) -> None:
    assert (await client.get("/v1/integrations")).status_code == 404
    assert (await client.get("/connect/google")).status_code == 404


def test_build_gateway_without_connector_keeps_builtins(settings: Settings) -> None:
    names = {s.name for s in build_gateway(settings).registry.specs()}
    assert "get_calendar" in names and "gmail_send" not in names


def test_build_storage_wires_a_token_store(gsettings: Settings) -> None:
    from jarvis.integrations.vault import MemoryTokenStore

    st = build_storage(gsettings.model_copy(update={"session_backend": SessionBackend.MEMORY}))
    assert isinstance(st.tokens, MemoryTokenStore)


def test_tools_disabled_flag_keeps_google_out(gsettings: Settings) -> None:
    from jarvis.integrations.google import build_google_connector
    from jarvis.integrations.vault import MemoryTokenStore

    off = gsettings.model_copy(update={"google_tools_enabled": False})
    assert build_google_connector(off, MemoryTokenStore()) is None
    assert build_google_connector(gsettings, MemoryTokenStore()) is not None


# ---- connect --------------------------------------------------------------------------------


async def test_connect_requires_a_signed_in_owner(gc: AsyncClient) -> None:
    assert (await gc.get("/connect/google", follow_redirects=False)).status_code == 401
    # a bearer token is not a browser: no OAuth dance for scripts
    r = await gc.get(
        "/connect/google", headers={"Authorization": "Bearer cli-token"}, follow_redirects=False
    )
    assert r.status_code == 401


async def test_connect_redirects_to_google_with_offline_consent_and_login_hint(
    gc: AsyncClient,
) -> None:
    await _login(gc, OWNER)
    r = await gc.get("/connect/google", follow_redirects=False)
    assert r.status_code in (302, 307)
    url = urlsplit(r.headers["location"])
    assert url.netloc == "accounts.google.com"
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["include_granted_scopes"] == "true" and q["login_hint"] == OWNER
    assert q["code_challenge_method"] == "S256" and q["code_challenge"] and q["state"]
    assert q["redirect_uri"] == "http://test/connect/google/callback"
    scopes = set(q["scope"].split())
    assert {
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.insert",  # optional (slice 7 inbox delivery)
        "openid",
        "email",
    } <= scopes


async def test_callback_links_the_owner_and_redirects_to_console(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/?connected=google"
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st["connected"] is True and st["email"] == OWNER and st["needs_reconnect"] is False
    assert "https://www.googleapis.com/auth/gmail.compose" in st["scopes"]
    assert st["expires_at"] == 1_900_000_000
    assert "ya29" not in r.text and "refresh" not in str(st)
    saved = await gc.app.state.google.store.get(user_id_for_email(OWNER))  # type: ignore[attr-defined]
    assert saved is not None and saved.refresh_token.get_secret_value() == "1//refresh"


async def test_callback_refuses_a_different_google_account(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, "someone.else@example.com")
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connect_error=wrong_account"
    assert (await gc.get("/v1/integrations")).json()["google"]["connected"] is False


async def test_callback_refuses_when_not_started_by_this_owner(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    _fake_consent(gc, OWNER)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/?connect_error=not_started"  # no connect started here
    # started as OWNER, but the browser is now signed in as OTHER
    await gc.get("/connect/google", follow_redirects=False)
    await _login(gc, OTHER)
    _fake_consent(gc, OTHER)
    r2 = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r2.status_code == 302 and r2.headers["location"] == "/?connect_error=not_started"
    for who in (OWNER, OTHER):
        assert await gc.app.state.google.store.get(user_id_for_email(who)) is None  # type: ignore[attr-defined]


async def test_callback_without_signin_is_unauthorised(gc: AsyncClient) -> None:
    _fake_consent(gc, OWNER)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 401


async def test_callback_without_refresh_token_is_refused(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER, refresh=False)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connect_error=no_refresh_token"
    assert (await gc.get("/v1/integrations")).json()["google"]["connected"] is False


async def test_callback_hides_authlib_errors(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)

    async def boom(request: Any) -> dict[str, Any]:
        raise RuntimeError("mismatching_state: CSRF Warning! secret-detail")

    gc.app.state.oauth.google_tools.authorize_access_token = boom  # type: ignore[attr-defined]
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connect_error=oauth_failed"
    assert "secret-detail" not in r.text


# ---- status + disconnect --------------------------------------------------------------------


async def test_status_requires_auth_and_is_per_user(gc: AsyncClient) -> None:
    assert (await gc.get("/v1/integrations")).status_code == 401
    await _login(gc, OWNER)
    assert (await gc.get("/v1/integrations")).json() == {
        "google": {
            "connected": False,
            "email": None,
            "scopes": [],
            "expires_at": None,
            "needs_reconnect": False,
            "tasks_granted": False,
            "contacts_granted": False,  # slice 12 D7
            "youtube_granted": False,
            "tasks_available": True,  # slice 12 review C7: a Grant row is offered only when
            "contacts_available": True,  # its tools exist here and are not set to Never
            "youtube_available": False,  # no API key on this server: no YouTube tools
        },
        "drive_available": False,  # final review: JARVIS_DRIVE is off on this server
        "maps_available": False,  # no API key: no Maps (Home / Work hidden)
    }
    # bearer token = primary owner (OWNER is first in the list)
    r = await gc.get("/v1/integrations", headers={"Authorization": "Bearer cli-token"})
    assert r.status_code == 200 and r.json()["google"]["connected"] is False


async def test_disconnect_needs_csrf_header_then_revokes_and_forgets(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER)
    await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    revoked: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        revoked.append(req)
        return httpx.Response(200)

    gc.app.state.google.http = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler)
    )
    assert (await gc.post("/v1/integrations/google/disconnect", json={})).status_code == 403
    r = await gc.post("/v1/integrations/google/disconnect", json={}, headers=CSRF)  # console body
    assert r.status_code == 200 and r.json() == {"ok": True, "google": {"connected": False}}
    assert len(revoked) == 1 and str(revoked[0].url) == REVOKE_URL
    assert (await gc.get("/v1/integrations")).json()["google"]["connected"] is False
    # idempotent
    assert (await gc.post("/v1/integrations/google/disconnect", headers=CSRF)).status_code == 200
    assert len(revoked) == 1


async def test_second_owner_does_not_see_the_first_owners_link(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER)
    await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    await _login(gc, OTHER)
    assert (await gc.get("/v1/integrations")).json()["google"]["connected"] is False


async def test_connect_routes_are_rate_limited(gsettings: Settings) -> None:
    s = gsettings.model_copy(update={"rate_limit_per_minute": 2})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = [
                (await c.get("/connect/google", follow_redirects=False)).status_code
                for _ in range(4)
            ]
            assert codes[:2] == [401, 401] and codes[2:] == [429, 429]


# ---- security review M3 / L3 ----------------------------------------------------------------


def _mock_google_http(gc: AsyncClient) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200)

    gc.app.state.google.http = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler)
    )
    return seen


async def test_callback_refuses_a_grant_with_unticked_scopes(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    partial = tuple(s for s in TOOL_SCOPES if not s.endswith("gmail.compose"))
    _fake_consent(gc, OWNER, scopes=partial)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connect_error=missing_scopes"
    assert await gc.app.state.google.store.get(user_id_for_email(OWNER)) is None  # type: ignore[attr-defined]


TASKS = "https://www.googleapis.com/auth/tasks"


async def test_google_mode_registers_the_todo_tools(gc: AsyncClient) -> None:
    names = {s.name for s in gc.app.state.gateway.registry.specs()}  # type: ignore[attr-defined]
    assert {"tasks_list", "task_add", "task_update", "task_complete", "task_delete"} <= names


def _asked(r: Any) -> set[str]:
    return set(parse_qs(urlsplit(r.headers["location"]).query)["scope"][0].split())


async def test_connect_asks_for_the_tasks_scope_only_on_grant(gc: AsyncClient) -> None:
    """Security review L8: a plain (re)connect asks for exactly what it asked before slice 10;
    only the explicit Grant (`?add=tasks`) adds the to-do list, incrementally."""
    await _login(gc, OWNER)
    plain = await gc.get("/connect/google", follow_redirects=False)
    assert TASKS not in _asked(plain)
    assert "https://www.googleapis.com/auth/gmail.compose" in _asked(plain)
    for junk in ("?add=TASKS", "?add=tasks.readonly", "?add=https://mail.google.com/"):
        r = await gc.get("/connect/google" + junk, follow_redirects=False)
        assert TASKS not in _asked(r) and "https://mail.google.com/" not in _asked(r)
    grant = await gc.get("/connect/google?add=tasks", follow_redirects=False)
    assert TASKS in _asked(grant) and _asked(plain) <= _asked(grant)
    q = parse_qs(urlsplit(grant.headers["location"]).query)
    assert q["include_granted_scopes"] == ["true"]  # Grant keeps everything already granted


async def test_a_reconnect_keeps_asking_for_tasks_once_granted(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google?add=tasks", follow_redirects=False)
    _fake_consent(gc, OWNER)  # every scope, tasks included
    await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    again = await gc.get("/connect/google", follow_redirects=False)  # e.g. "Reconnect" after 7 days
    assert TASKS in _asked(again)


async def test_integrations_say_whether_the_todo_list_is_granted(gc: AsyncClient) -> None:
    """Slice 10 C: a link made before the to-do list (or with its box unticked) stays connected
    and says `tasks_granted: false`; Grant re-runs connect and flips it."""
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER, scopes=tuple(s for s in TOOL_SCOPES if s != TASKS))
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/?connected=google"
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st["connected"] is True and st["tasks_granted"] is False
    await gc.get("/connect/google?add=tasks", follow_redirects=False)  # "Grant"
    _fake_consent(gc, OWNER)
    await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st["connected"] is True and st["tasks_granted"] is True and TASKS in st["scopes"]


async def test_callback_links_without_the_optional_insert_scope(gc: AsyncClient) -> None:
    """Slice 7: gmail.insert is asked for but optional; unticking it still links Google."""
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    without = tuple(s for s in TOOL_SCOPES if not s.endswith("gmail.insert"))
    _fake_consent(gc, OWNER, scopes=without)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connected=google"
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st["connected"] is True
    assert "https://www.googleapis.com/auth/gmail.insert" not in st["scopes"]
    today = (await gc.get("/v1/brief/today")).json()
    assert today["google_connected"] is True and today["inbox_available"] is False


async def test_wrong_account_grant_is_revoked_at_google(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, "someone.else@example.com")
    revoked = _mock_google_http(gc)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/?connect_error=wrong_account"
    assert len(revoked) == 1 and str(revoked[0].url) == REVOKE_URL
    assert dict(httpx.QueryParams(revoked[0].content.decode()))["token"] == "1//refresh"


async def test_wrong_account_still_redirects_when_revoke_fails(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, "someone.else@example.com")

    def down(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    gc.app.state.google.http = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(down)
    )
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connect_error=wrong_account"


async def test_malformed_vault_document_reads_as_needs_reconnect(gc: AsyncClient) -> None:
    """Security review L4: a damaged token document is a reconnect prompt, not a 500."""
    from jarvis.integrations.vault import DocTokenStore, decode_key
    from jarvis.storage.docs import MemoryDocs, Set

    docs = MemoryDocs()
    uid = user_id_for_email(OWNER)
    await docs.write([Set(f"jarvis_tokens/{uid}", {"email": OWNER, "blob": "AAAA"})])
    gc.app.state.google.store = DocTokenStore(docs, key=decode_key(KEY_B64))  # type: ignore[attr-defined]
    await _login(gc, OWNER)
    r = await gc.get("/v1/integrations")
    assert r.status_code == 200
    assert (
        r.json()["google"]["connected"] is False and r.json()["google"]["needs_reconnect"] is True
    )


# ---- slice 12 D7: Grant generalised (to-do list, contacts, YouTube playlists) -----------------

CONTACTS = "https://www.googleapis.com/auth/contacts.readonly"
YOUTUBE = "https://www.googleapis.com/auth/youtube.readonly"


async def _link(gc: AsyncClient, *granted: str) -> None:
    """Link OWNER with the required scopes plus `granted` optional ones."""
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    base = tuple(s for s in TOOL_SCOPES if s not in (TASKS, CONTACTS, YOUTUBE))
    _fake_consent(gc, OWNER, scopes=(*base, *granted))
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/?connected=google"


@pytest.mark.parametrize(("name", "scope"), [("contacts", CONTACTS), ("youtube", YOUTUBE)])
async def test_grant_asks_for_exactly_that_one_scope_incrementally(
    gc: AsyncClient, name: str, scope: str
) -> None:
    await _login(gc, OWNER)
    plain = await gc.get("/connect/google", follow_redirects=False)
    grant = await gc.get(f"/connect/google?add={name}", follow_redirects=False)
    assert _asked(grant) == _asked(plain) | {scope}
    q = parse_qs(urlsplit(grant.headers["location"]).query)
    assert q["include_granted_scopes"] == ["true"]


@pytest.mark.parametrize(
    "junk",
    [
        "?add=contacts&add=youtube",  # exactly one name
        "?add=contacts,youtube",
        "?add=CONTACTS",
        "?add=contacts.readonly",
        "?add=" + CONTACTS,
        "?add=drive",
        "?add=",
    ],
)
async def test_anything_but_one_allow_listed_name_asks_for_nothing_extra(
    gc: AsyncClient, junk: str
) -> None:
    await _login(gc, OWNER)
    plain = await gc.get("/connect/google", follow_redirects=False)
    r = await gc.get("/connect/google" + junk, follow_redirects=False)
    assert r.status_code in (302, 307) and _asked(r) == _asked(plain)


async def test_a_renewal_keeps_every_optional_scope_already_held(gc: AsyncClient) -> None:
    await _link(gc, TASKS, CONTACTS)
    again = await gc.get("/connect/google", follow_redirects=False)  # "Reconnect"
    assert {TASKS, CONTACTS} <= _asked(again) and YOUTUBE not in _asked(again)
    more = await gc.get("/connect/google?add=youtube", follow_redirects=False)  # "Grant"
    assert {TASKS, CONTACTS, YOUTUBE} <= _asked(more)


async def test_a_plain_reconnect_asks_only_for_what_the_link_held(gc: AsyncClient) -> None:
    """Review L8 still holds: nothing optional is asked for that the owner didn't grant."""
    await _link(gc)
    again = await gc.get("/connect/google", follow_redirects=False)
    assert not {TASKS, CONTACTS, YOUTUBE} & _asked(again)


async def test_integrations_say_which_optional_permissions_are_granted(gc: AsyncClient) -> None:
    await _link(gc, CONTACTS)
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st["contacts_granted"] is True
    assert st["youtube_granted"] is False and st["tasks_granted"] is False
    assert "drive" not in st  # Drive has its own route (builder A); not part of this view


# ---- review C7: a Grant row only when its tools exist here and are not switched off ------------


async def test_youtube_is_available_only_with_the_servers_api_key(gsettings: Settings) -> None:
    keyed = gsettings.model_copy(update={"google_api_key": SecretStr("AIza-test-key")})
    app = create_app(keyed, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        c = await _client(app)
        try:
            await _login(c, OWNER)
            r = await c.get("/v1/integrations")
            st = r.json()["google"]
            assert st["youtube_available"] is True and st["contacts_available"] is True
            assert "AIza" not in r.text  # the key never reaches the browser
        finally:
            await c.aclose()


@pytest.mark.parametrize(("row", "grant"), [("contacts", "contacts"), ("todo_change", "tasks")])
async def test_a_grant_whose_permission_row_is_never_is_not_offered(
    gc: AsyncClient, row: str, grant: str
) -> None:
    await _login(gc, OWNER)
    r = await gc.put("/v1/permissions", json={"groups": {row: "deny"}}, headers=CSRF)
    assert r.status_code == 200
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st[f"{grant}_available"] is False
    others = {"tasks", "contacts"} - {grant}
    assert all(st[f"{o}_available"] is True for o in others)
    await gc.put("/v1/permissions", json={"groups": {row: "ask"}}, headers=CSRF)
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st[f"{grant}_available"] is True  # "Ask first" still offers the Grant


async def test_unreadable_permissions_still_offer_the_grants(gc: AsyncClient) -> None:
    """The view can't tell: it offers the row; the gateway itself still fails closed on a call."""

    class Broken:
        async def rules_for(self, user_id: str) -> list[Any]:
            raise RuntimeError("storage down")

    await _login(gc, OWNER)
    gc.app.state.permissions = Broken()  # type: ignore[attr-defined]
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st["contacts_available"] is True and st["tasks_available"] is True


# ---- final review: Drive and Maps say whether the console should show them --------------------


@pytest.fixture
async def full(gsettings: Settings) -> AsyncIterator[AsyncClient]:
    """Drive switched on and the server's Maps / YouTube key set."""
    on = gsettings.model_copy(update={"drive": True, "google_api_key": SecretStr("AIza-test")})
    app = create_app(on, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        c = await _client(app)
        try:
            yield c
        finally:
            await c.aclose()


async def test_drive_and_maps_are_available_when_on_and_not_never(full: AsyncClient) -> None:
    await _login(full, OWNER)
    r = (await full.get("/v1/integrations")).json()
    assert r["drive_available"] is True and r["maps_available"] is True
    assert "drive" not in r["google"] and "maps" not in r["google"]  # no summary blocks (D7)


@pytest.mark.parametrize(
    ("row", "field"), [("drive", "drive_available"), ("maps", "maps_available")]
)
async def test_never_on_drive_or_maps_hides_it_and_ask_first_does_not(
    full: AsyncClient, row: str, field: str
) -> None:
    await _login(full, OWNER)
    assert (
        await full.put("/v1/permissions", json={"groups": {row: "deny"}}, headers=CSRF)
    ).status_code == 200
    r = (await full.get("/v1/integrations")).json()
    assert r[field] is False
    other = ({"drive_available", "maps_available"} - {field}).pop()
    assert r[other] is True
    await full.put("/v1/permissions", json={"groups": {row: "ask"}}, headers=CSRF)
    assert (await full.get("/v1/integrations")).json()[field] is True
