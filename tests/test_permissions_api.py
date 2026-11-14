# tests/test_permissions_api.py — /v1/permissions, /v1/passkeys and the passkey check on
# /v1/approvals/{id}/approve through the real app (mock brain, in-process storage, software
# authenticator). Passkeys need Google sign-in: the owner's browser has a signed cookie, and the
# first passkey / a reset need a re-sign-in (/auth/login?reauth=1) in the last 5 minutes. The CLI's
# bearer token is accepted everywhere else, and gets plain refusals for passkey-only steps.
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from passkey_fakes import SoftAuthenticator
from pydantic import SecretStr

from jarvis.api import auth as auth_mod
from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.base import Preview, Tool
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

ORIGIN = "http://test"
OWNER = "akash@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}


async def _client(app: Any) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
def google_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": ORIGIN,
            "api_token": SecretStr("cli-token"),
        }
    )


@pytest.fixture
async def gclient(
    google_settings: Settings, provider: MockProvider, gateway: Gateway
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        google_settings, provider=provider, store=InMemorySessionStore(), gateway=gateway
    )
    async for c in _client(app):
        yield c


def _cli(c: AsyncClient) -> AsyncClient:
    """A second client on the same app: the bearer token only, never the browser's cookie."""
    return AsyncClient(transport=ASGITransport(app=c.app), base_url=ORIGIN, headers=BEARER)  # type: ignore[attr-defined]


def _fresh(claims: dict[str, Any]) -> dict[str, Any]:
    """Google's ID token carries `auth_time` once its Session age claims are on (R14 D13 (1)):
    now, unless the test names one; `auth_time=None` leaves it out (the setting decides)."""
    out = {"auth_time": int(auth_mod._now()), **claims}
    return {k: v for k, v in out.items() if v is not None}


async def _google(c: AsyncClient, *, reauth: bool = True, **claims: Any) -> Any:
    """Sign in through the real /auth routes; Google's half is faked (who the user is)."""

    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": "1", **_fresh(claims)}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    if reauth:
        start = await c.get("/auth/login?reauth=1", follow_redirects=False)
        assert "max_age=0" in start.headers["location"]
    return await c.get("/auth/callback?code=abc&state=s")


async def _register(c: AsyncClient, auth: SoftAuthenticator, **body: Any) -> dict[str, Any]:
    r = await c.post("/v1/passkeys/register/options", json=body, headers=CSRF)
    assert r.status_code == 200, r.text
    opts = r.json()
    cred = auth.create(opts["public_key"])
    r = await c.post(
        "/v1/passkeys/register",
        json={"challenge_id": opts["challenge_id"], "credential": cred, "label": "Laptop"},
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


async def _proof(c: AsyncClient, auth: SoftAuthenticator, **req: Any) -> dict[str, Any]:
    r = await c.post("/v1/passkeys/challenge", json=req, headers=CSRF)
    assert r.status_code == 200, r.text
    ch = r.json()
    assert ch["expires_in_s"] == 120 and ch["public_key"]["userVerification"] == "required"
    return {"challenge_id": ch["challenge_id"], "credential": auth.get(ch["public_key"])}


async def _card(
    c: AsyncClient, provider: MockProvider, tool: str = "send_message", **args: Any
) -> tuple[str, str]:
    args = args or (
        {"to": "priya@x.com", "body": "3pm"}
        if tool == "send_message"
        else {"text": "call bank", "when": "17:00"}
    )
    provider.script_tool_calls([ToolCall(id="t1", name=tool, arguments=args)], "Waiting for you.")
    body = (await c.post("/v1/chat", json={"message": "do it"}, headers=CSRF)).json()
    card = body["pending_approvals"][0]
    return card["id"], body["session_id"]


async def _ready(c: AsyncClient) -> SoftAuthenticator:
    """Signed in again, first passkey set up."""
    auth = SoftAuthenticator(origin=ORIGIN)
    await _google(c)
    v = await _register(c, auth)
    assert v["require_passkey"] is True
    return auth


# ---- choices (token mode, no public address) ----------------------------------------------------


async def test_view_defaults_without_a_public_address(client: AsyncClient) -> None:
    v = (await client.get("/v1/permissions")).json()
    assert v["passkeys_available"] is False and "JARVIS_PUBLIC_BASE_URL" in v["passkeys_note"]
    assert v["require_passkey"] is False and v["can_reauth"] is False and v["reset"] is None
    send = next(g for g in v["groups"] if g["id"] == "email_send")
    assert send["choices"] == ["ask", "deny"] and send["effect"] == "ask" and send["irreversible"]
    r = await client.post("/v1/passkeys/register/options", json={})
    assert r.status_code == 409 and r.json()["error"] == "passkeys_unavailable"


async def test_token_mode_with_an_address_still_has_no_passkeys(
    settings: Settings, provider: MockProvider
) -> None:
    app = create_app(
        settings.model_copy(update={"public_base_url": ORIGIN}),
        provider=provider,
        store=InMemorySessionStore(),
    )
    async for c in _client(app):
        v = (await c.get("/v1/permissions")).json()
        assert v["passkeys_available"] is False and "Google sign-in" in v["passkeys_note"]


async def test_put_validates_and_refuses_allow_for_irreversible(client: AsyncClient) -> None:
    r = await client.put("/v1/permissions", json={"groups": {"email_send": "allow"}})
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"
    assert "can't be set to Allow" in r.json()["detail"]
    for bad in ({"nope": "deny"}, {"web": "maybe"}, {"web": 3}):
        r = await client.put("/v1/permissions", json={"groups": bad})
        assert r.status_code == 422, bad
    r = await client.put("/v1/permissions", json={"groups": {"web": "deny"}})
    assert r.status_code == 200
    assert {g["id"]: g["effect"] for g in r.json()["groups"]}["web"] == "deny"


async def test_never_reaches_the_tool_and_the_model_reads_why(
    client: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    await client.put("/v1/permissions", json={"groups": {"email_send": "deny"}})
    provider.script_tool_calls(
        [ToolCall(id="t1", name="send_message", arguments={"to": "a@x.com", "body": "b"})],
        "It is switched off, Sir.",
    )
    body = (await client.post("/v1/chat", json={"message": "send it"})).json()
    assert body["pending_approvals"] == [] and world.sent == []
    tool_result = provider.calls[-1].messages[-1].content[0]
    assert "switched off by the owner in Permissions" in tool_result.content
    audit = (await client.get("/v1/audit")).json()["entries"]
    assert audit[-1]["outcome"] == "denied" and audit[-1]["detail"] == "policy:owner:email_send"


async def test_permission_changes_land_in_the_shared_audit_chain(client: AsyncClient) -> None:
    await client.put("/v1/permissions", json={"groups": {"web": "deny", "email_send": "deny"}})
    audit = (await client.get("/v1/audit")).json()
    last = audit["entries"][-1]
    assert audit["verified"] is True
    assert (last["agent"], last["tool"], last["outcome"]) == ("owner", "permissions", "changed")
    assert last["detail"] == "email_send=deny; web=deny"


# ---- sign-in: only a real re-sign-in counts ------------------------------------------------------


async def test_reauth_asks_google_again_and_only_it_stamps_the_window(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth_mod, "_now", lambda: now[0])
    plain = await gclient.get("/auth/login", follow_redirects=False)
    assert "max_age" not in plain.headers["location"]
    r = await _google(gclient, reauth=False)
    assert r.headers["location"] == "/"
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 0  # not stamped
    # R14 D13 (1): no auth_time from Google and `reauth_requires_auth_time` off (the default):
    # the moment it completed, as before R14 (tests/test_r14_d_auth.py has the setting on)
    r = await _google(gclient, auth_time=None)
    assert r.headers["location"] == "/?reauth=done"
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 300
    r = await _google(gclient)  # Google's auth_time: the moment it asked again
    assert r.headers["location"] == "/?reauth=done"
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 300
    now[0] += 299
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 1
    now[0] += 2
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 0
    # Google says the owner last authenticated before this re-sign-in began: nothing stamped
    r = await _google(gclient, auth_time=int(now[0] - 3600))
    assert r.headers["location"] == "/?reauth=stale"
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 0
    r = await _google(gclient, auth_time=int(now[0]))
    assert r.headers["location"] == "/?reauth=done"
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 300


async def test_a_re_sign_in_started_long_ago_does_not_count(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth_mod, "_now", lambda: now[0])
    await gclient.get("/auth/login?reauth=1", follow_redirects=False)
    now[0] += 3600  # the tab sat at Google's page for an hour
    r = await _google(gclient, reauth=False)
    assert r.headers["location"] == "/"
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 0


# ---- the first passkey: a fresh re-sign-in in this browser ---------------------------------------


async def test_the_first_passkey_needs_a_re_sign_in_and_refuses_bearer(
    gclient: AsyncClient,
) -> None:
    r = await gclient.post("/v1/passkeys/register/options", json={}, headers=BEARER)
    assert r.status_code == 403 and r.json()["reason"] == "reauth"
    await _google(gclient, reauth=False)
    r = await gclient.post("/v1/passkeys/register/options", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json() == {
        "error": "proof_required",
        "detail": r.json()["detail"],
        "reason": "reauth",
    }
    await _ready(gclient)


async def test_a_second_passkey_or_switching_off_needs_a_passkey_not_a_sign_in(
    gclient: AsyncClient,
) -> None:
    auth = await _ready(gclient)
    await _google(gclient)  # a fresh sign-in is no shortcut
    r = await gclient.post("/v1/passkeys/register/options", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["reason"] == "passkey"
    r = await gclient.put("/v1/permissions", json={"require_passkey": False}, headers=CSRF)
    assert r.status_code == 403 and r.json()["reason"] == "passkey"
    v = await _register(gclient, auth, proof=await _proof(gclient, auth, purpose="add"))
    assert len(v["passkeys"]) == 2
    proof = await _proof(gclient, auth, purpose="disable")
    r = await gclient.put(
        "/v1/permissions", json={"require_passkey": False, "proof": proof}, headers=CSRF
    )
    assert r.status_code == 200 and r.json()["require_passkey"] is False


# ---- approvals --------------------------------------------------------------------------------


async def test_irreversible_approval_needs_the_passkey_once_one_exists(
    gclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    auth = await _ready(gclient)
    pid, sid = await _card(gclient, provider)
    cards = (await gclient.get("/v1/approvals")).json()
    assert cards[0]["passkey_required"] is True and cards[0]["tool_risk"] == "irreversible"
    r = await gclient.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    assert world.sent == [] and len((await gclient.get("/v1/approvals")).json()) == 1
    proof = await _proof(gclient, auth, purpose="approve", approval_id=pid)
    provider.script("Sent, Sir.")
    r = await gclient.post(
        f"/v1/approvals/{pid}/approve", json={"session_id": sid, "passkey": proof}, headers=CSRF
    )
    assert r.status_code == 200, r.text
    assert world.sent == [{"to": "priya@x.com", "body": "3pm"}]
    executing = [
        e for e in (await gclient.get("/v1/audit")).json()["entries"] if e["outcome"] == "executing"
    ]
    assert executing[-1]["detail"].startswith("confirmed; passkey ")
    # the same check again on another card: refused before anything runs
    pid2, sid2 = await _card(gclient, provider)
    r = await gclient.post(
        f"/v1/approvals/{pid2}/approve", json={"session_id": sid2, "passkey": proof}, headers=CSRF
    )
    assert r.status_code == 403 and r.json()["reason"] == "replayed" and len(world.sent) == 1


async def test_the_cli_bearer_token_gets_a_plain_refusal(
    gclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    await _ready(gclient)
    pid, sid = await _card(gclient, provider)
    async with _cli(gclient) as cli:  # the CLI: bearer token, no browser cookie
        r = await cli.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid})
    assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    assert "command line" in r.json()["detail"] and world.sent == []


async def test_a_check_for_another_card_or_origin_is_refused(
    gclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    auth = await _ready(gclient)
    a, sid = await _card(gclient, provider)
    b, sid_b = await _card(gclient, provider, to="b@x.com", body="other")
    proof = await _proof(gclient, auth, purpose="approve", approval_id=a)
    r = await gclient.post(
        f"/v1/approvals/{b}/approve", json={"session_id": sid_b, "passkey": proof}, headers=CSRF
    )
    assert r.status_code == 403 and r.json()["reason"] == "wrong_action"
    ch = (
        await gclient.post(
            "/v1/passkeys/challenge", json={"purpose": "approve", "approval_id": a}, headers=CSRF
        )
    ).json()
    cred = auth.get(ch["public_key"], origin="https://evil.example")
    body = {"session_id": sid, "passkey": {"challenge_id": ch["challenge_id"], "credential": cred}}
    r = await gclient.post(f"/v1/approvals/{a}/approve", json=body, headers=CSRF)
    assert r.status_code == 403 and r.json()["reason"] == "failed" and world.sent == []


async def test_reversible_cards_and_declines_never_need_a_passkey(
    gclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    await _ready(gclient)
    await gclient.put("/v1/permissions", json={"groups": {"todo_change": "ask"}}, headers=CSRF)
    pid, sid = await _card(gclient, provider, "create_reminder")
    cards = (await gclient.get("/v1/approvals")).json()
    assert cards[0]["tool_risk"] == "reversible" and cards[0]["passkey_required"] is False
    provider.script("Done.")
    r = await gclient.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid}, headers=CSRF)
    assert r.status_code == 200 and len(world.reminders) == 1
    pid, sid = await _card(gclient, provider)
    provider.script("Understood.")
    r = await gclient.post(f"/v1/approvals/{pid}/decline", json={"session_id": sid}, headers=CSRF)
    assert r.status_code == 200 and world.sent == []


async def test_a_card_that_became_irreversible_comes_back_as_a_new_passkey_card(
    google_settings: Settings, provider: MockProvider
) -> None:
    """H1 through the brain: approved as R2 after guests were added → nothing runs, a new R3
    card (passkey) is waiting, and the reply says so."""
    world, ran, guests = InMemoryWorld(), [], [False]

    async def preview(a: dict[str, Any]) -> Preview:
        who = "and email the guests" if guests[0] else "only you"
        return Preview(
            f"Move the dentist to {a['when']} ({who})",
            ActionRisk.IRREVERSIBLE if guests[0] else None,
        )

    reg = ToolRegistry()
    for t in builtin_tools(world):
        reg.register(t)
    reg.register(
        Tool(
            "calendar_update_event",
            "move",
            {"type": "object", "properties": {"when": {"type": "string"}}},
            ActionRisk.REVERSIBLE,
            ran.append,
            preview=preview,
        )
    )
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    app = create_app(google_settings, provider=provider, store=InMemorySessionStore(), gateway=gw)
    async for c in _client(app):
        auth = await _ready(c)
        await c.put("/v1/permissions", json={"groups": {"calendar_change": "ask"}}, headers=CSRF)
        pid, sid = await _card(c, provider, "calendar_update_event", when="15:00")
        assert (await c.get("/v1/approvals")).json()[0]["passkey_required"] is False
        guests[0] = True
        provider.script("It changed, Sir.")
        r = await c.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid}, headers=CSRF)
        assert r.status_code == 200 and ran == []
        (new,) = r.json()["pending_approvals"]
        assert new["id"] != pid and new["tool_risk"] == "irreversible"
        assert "email the guests" in new["summary"]
        listed = (await c.get("/v1/approvals")).json()
        assert [x["id"] for x in listed] == [new["id"]] and listed[0]["passkey_required"] is True
        r = await c.post(
            f"/v1/approvals/{new['id']}/approve", json={"session_id": sid}, headers=CSRF
        )
        assert r.status_code == 403 and ran == []
        proof = await _proof(c, auth, purpose="approve", approval_id=new["id"])
        provider.script("Moved.")
        r = await c.post(
            f"/v1/approvals/{new['id']}/approve",
            json={"session_id": sid, "passkey": proof},
            headers=CSRF,
        )
        assert r.status_code == 200 and len(ran) == 1


# ---- removal and the delayed reset --------------------------------------------------------------


async def test_remove_needs_a_passkey_check(gclient: AsyncClient) -> None:
    auth = await _ready(gclient)
    cid = (await gclient.get("/v1/permissions")).json()["passkeys"][0]["id"]
    r = await gclient.post(f"/v1/passkeys/{cid}/remove", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["reason"] == "passkey"
    proof = await _proof(gclient, auth, purpose="remove", credential_id=cid)
    r = await gclient.post(f"/v1/passkeys/{cid}/remove", json={"proof": proof}, headers=CSRF)
    assert r.status_code == 200 and r.json()["passkeys"] == []
    r = await gclient.post(f"/v1/passkeys/{cid}/remove", json={}, headers=CSRF)
    assert r.status_code == 404


async def test_lost_passkey_reset_waits_24_hours_and_can_be_cancelled(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = await _ready(gclient)
    now = [time.time() + 600]  # ten minutes later: the window has closed
    monkeypatch.setattr(auth_mod, "_now", lambda: now[0])
    r = await gclient.post("/v1/passkeys/reset", headers=CSRF)
    assert r.status_code == 403 and r.json()["reason"] == "reauth"
    async with _cli(gclient) as cli:
        r = await cli.post("/v1/passkeys/reset")
    assert r.status_code == 403 and r.json()["reason"] == "reauth"
    await _google(gclient)
    r = await gclient.post("/v1/passkeys/reset", headers=CSRF)
    assert r.status_code == 200 and r.json()["reset"]["effective_at"]
    assert len(r.json()["passkeys"]) == 1 and r.json()["require_passkey"] is True
    events = [e["outcome"] for e in (await gclient.get("/v1/audit")).json()["entries"]]
    assert events[-2:] == ["reset_requested", "reset_notice"]
    r = await gclient.post("/v1/passkeys/reset/cancel", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["reason"] == "passkey"
    proof = await _proof(gclient, auth, purpose="cancel_reset")
    r = await gclient.post("/v1/passkeys/reset/cancel", json={"proof": proof}, headers=CSRF)
    assert r.status_code == 200 and r.json()["reset"] is None and len(r.json()["passkeys"]) == 1


async def test_garbage_credentials_are_422_not_500(gclient: AsyncClient) -> None:
    await _ready(gclient)
    for body in (
        {"proof": {"challenge_id": "x" * 20, "credential": {"id": "a", "rawId": "a", "type": "x"}}},
        {"proof": {"challenge_id": "short", "credential": {}}},
        {
            "proof": {
                "challenge_id": "x" * 20,
                "credential": {"id": "a b", "rawId": "a", "type": "public-key", "response": {}},
            }
        },
    ):
        r = await gclient.post("/v1/passkeys/register/options", json=body, headers=CSRF)
        assert r.status_code == 422, (body, r.text)


async def test_cookie_writes_need_the_csrf_header(gclient: AsyncClient) -> None:
    await _google(gclient)
    r = await gclient.put("/v1/permissions", json={"groups": {"web": "deny"}})
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = await gclient.post("/v1/passkeys/reset")
    assert r.status_code == 403 and r.json()["error"] == "csrf"


async def test_signed_out_gets_401(gclient: AsyncClient) -> None:
    assert (await gclient.get("/v1/permissions")).status_code == 401
    r = await gclient.post("/v1/passkeys/register/options", json={}, headers=CSRF)
    assert r.status_code == 401
