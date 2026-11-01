# tests/test_permissions_api.py — /v1/permissions, /v1/passkeys and the passkey guard on
# /v1/approvals/{id}/approve through the real app (mock brain, in-process storage, software
# authenticator). Token mode (the CLI's bearer) and Google mode (cookie, re-auth path).
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from passkey_fakes import SoftAuthenticator
from pydantic import SecretStr

from jarvis.api import auth as auth_mod
from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import Gateway
from jarvis.tools.builtin import InMemoryWorld

ORIGIN = "http://test"
OWNER = "akash@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}


@pytest.fixture
def rp_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"public_base_url": ORIGIN})


async def _client(app: Any) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
async def pclient(
    rp_settings: Settings, provider: MockProvider, store: InMemorySessionStore, gateway: Gateway
) -> AsyncIterator[AsyncClient]:
    app = create_app(rp_settings, provider=provider, store=store, gateway=gateway)
    async for c in _client(app):
        yield c


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


async def _send_card(
    c: AsyncClient, provider: MockProvider, tool: str = "send_message"
) -> tuple[str, str]:
    args = (
        {"to": "priya@x.com", "body": "3pm"}
        if tool == "send_message"
        else {"text": "call bank", "when": "17:00"}
    )
    provider.script_tool_calls([ToolCall(id="t1", name=tool, arguments=args)], "Waiting for you.")
    body = (await c.post("/v1/chat", json={"message": "do it"}, headers=CSRF)).json()
    card = body["pending_approvals"][0]
    return card["id"], body["session_id"]


# ---- choices -----------------------------------------------------------------------------------


async def test_view_defaults_without_a_public_address(client: AsyncClient) -> None:
    v = (await client.get("/v1/permissions")).json()
    assert v["passkeys_available"] is False and "JARVIS_PUBLIC_BASE_URL" in v["passkeys_note"]
    assert v["require_passkey"] is False and v["can_reauth"] is False
    send = next(g for g in v["groups"] if g["id"] == "email_send")
    assert send["choices"] == ["ask", "deny"] and send["effect"] == "ask" and send["irreversible"]
    r = await client.post("/v1/passkeys/register/options", json={})
    assert r.status_code == 409 and r.json()["error"] == "passkeys_unavailable"


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


async def test_ask_first_on_a_reversible_group_makes_a_card_without_passkey(
    pclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    await _register(pclient, SoftAuthenticator(origin=ORIGIN))
    await pclient.put("/v1/permissions", json={"groups": {"todo_change": "ask"}}, headers=CSRF)
    pid, sid = await _send_card(pclient, provider, "create_reminder")
    cards = (await pclient.get("/v1/approvals")).json()
    assert cards[0]["tool_risk"] == "reversible" and cards[0]["passkey_required"] is False
    provider.script("Done.")
    r = await pclient.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid}, headers=CSRF)
    assert r.status_code == 200 and len(world.reminders) == 1


# ---- passkeys and the approval guard -----------------------------------------------------------


async def test_irreversible_approval_needs_the_passkey_once_one_exists(
    pclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    auth = SoftAuthenticator(origin=ORIGIN)
    v = await _register(pclient, auth)
    assert v["require_passkey"] is True and len(v["passkeys"]) == 1
    pid, sid = await _send_card(pclient, provider)
    cards = (await pclient.get("/v1/approvals")).json()
    assert cards[0]["passkey_required"] is True and cards[0]["tool_risk"] == "irreversible"

    r = await pclient.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    assert world.sent == [] and len((await pclient.get("/v1/approvals")).json()) == 1

    proof = await _proof(pclient, auth, purpose="approve", approval_id=pid)
    provider.script("Sent, Sir.")
    r = await pclient.post(
        f"/v1/approvals/{pid}/approve", json={"session_id": sid, "passkey": proof}, headers=CSRF
    )
    assert r.status_code == 200, r.text
    assert world.sent == [{"to": "priya@x.com", "body": "3pm"}]

    # the same check again: refused before anything (and the card is spent anyway)
    pid2, sid2 = await _send_card(pclient, provider)
    r = await pclient.post(
        f"/v1/approvals/{pid2}/approve", json={"session_id": sid2, "passkey": proof}, headers=CSRF
    )
    assert r.status_code == 403 and r.json()["reason"] == "replayed"
    assert len(world.sent) == 1


async def test_a_check_for_another_card_is_refused(
    pclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    auth = SoftAuthenticator(origin=ORIGIN)
    await _register(pclient, auth)
    a, sid = await _send_card(pclient, provider)
    provider.script_tool_calls(
        [ToolCall(id="t2", name="send_message", arguments={"to": "b@x.com", "body": "other"})], "ok"
    )
    body = (
        await pclient.post("/v1/chat", json={"message": "x", "session_id": sid}, headers=CSRF)
    ).json()
    b = body["pending_approvals"][0]["id"]
    proof = await _proof(pclient, auth, purpose="approve", approval_id=a)
    r = await pclient.post(
        f"/v1/approvals/{b}/approve", json={"session_id": sid, "passkey": proof}, headers=CSRF
    )
    assert r.status_code == 403 and r.json()["reason"] == "wrong_action" and world.sent == []


async def test_a_check_from_another_origin_is_refused(
    pclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    auth = SoftAuthenticator(origin=ORIGIN)
    await _register(pclient, auth)
    pid, sid = await _send_card(pclient, provider)
    ch = (
        await pclient.post(
            "/v1/passkeys/challenge", json={"purpose": "approve", "approval_id": pid}, headers=CSRF
        )
    ).json()
    cred = auth.get(ch["public_key"], origin="https://evil.example")
    r = await pclient.post(
        f"/v1/approvals/{pid}/approve",
        json={
            "session_id": sid,
            "passkey": {"challenge_id": ch["challenge_id"], "credential": cred},
        },
        headers=CSRF,
    )
    assert r.status_code == 403 and r.json()["reason"] == "failed" and world.sent == []


async def test_the_cli_bearer_token_gets_a_plain_refusal(
    rp_settings: Settings,
    provider: MockProvider,
    store: InMemorySessionStore,
    gateway: Gateway,
    world: InMemoryWorld,
) -> None:
    app = create_app(
        rp_settings.model_copy(update={"api_token": SecretStr("cli-token")}),
        provider=provider,
        store=store,
        gateway=gateway,
    )
    async for c in _client(app):
        c.headers.update(BEARER)
        await _register(c, SoftAuthenticator(origin=ORIGIN))
        pid, sid = await _send_card(c, provider)
        r = await c.post(f"/v1/approvals/{pid}/approve", json={"session_id": sid})
        assert r.status_code == 403 and r.json()["error"] == "passkey_required"
        assert "command line" in r.json()["detail"] and world.sent == []


async def test_decline_never_needs_a_passkey(
    pclient: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    await _register(pclient, SoftAuthenticator(origin=ORIGIN))
    pid, sid = await _send_card(pclient, provider)
    provider.script("Understood.")
    r = await pclient.post(f"/v1/approvals/{pid}/decline", json={"session_id": sid}, headers=CSRF)
    assert r.status_code == 200 and world.sent == []


async def test_remove_and_switch_off_need_proof_in_token_mode(pclient: AsyncClient) -> None:
    auth = SoftAuthenticator(origin=ORIGIN)
    v = await _register(pclient, auth)
    cid = v["passkeys"][0]["id"]
    r = await pclient.post(f"/v1/passkeys/{cid}/remove", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json() == {
        "error": "proof_required",
        "detail": r.json()["detail"],
        "reason": "passkey",
    }
    r = await pclient.put("/v1/permissions", json={"require_passkey": False}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "proof_required"
    proof = await _proof(pclient, auth, purpose="disable")
    r = await pclient.put(
        "/v1/permissions", json={"require_passkey": False, "proof": proof}, headers=CSRF
    )
    assert r.status_code == 200 and r.json()["require_passkey"] is False
    proof = await _proof(pclient, auth, purpose="remove", credential_id=cid)
    r = await pclient.post(f"/v1/passkeys/{cid}/remove", json={"proof": proof}, headers=CSRF)
    assert r.status_code == 200 and r.json()["passkeys"] == []
    r = await pclient.post(f"/v1/passkeys/{cid}/remove", json={}, headers=CSRF)
    assert r.status_code == 404


async def test_garbage_credentials_are_422_not_500(pclient: AsyncClient) -> None:
    await _register(pclient, SoftAuthenticator(origin=ORIGIN))
    for body in (
        {
            "proof": {
                "challenge_id": "x" * 20,
                "credential": {"id": "a", "rawId": "a", "type": "nope"},
            }
        },
        {"proof": {"challenge_id": "short", "credential": {}}},
        {
            "proof": {
                "challenge_id": "x" * 20,
                "credential": {"id": "a b", "rawId": "a", "type": "public-key", "response": {}},
            }
        },
    ):
        r = await pclient.post("/v1/passkeys/register/options", json=body, headers=CSRF)
        assert r.status_code == 422, (body, r.text)


# ---- Google mode: the cookie records when Google authenticated; the 5-minute recovery path -----


@pytest.fixture
def google_rp_settings(settings: Settings) -> Settings:
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
async def gclient(google_rp_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(google_rp_settings, provider=MockProvider(), store=InMemorySessionStore())
    async for c in _client(app):
        yield c


async def _google_login(c: AsyncClient, **claims: Any) -> Any:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": "1", **claims}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    return await c.get("/auth/callback?code=abc&state=s")


async def test_reauth_asks_google_to_authenticate_again_and_comes_back(
    gclient: AsyncClient,
) -> None:
    plain = await gclient.get("/auth/login", follow_redirects=False)
    assert "max_age" not in plain.headers["location"]
    r = await gclient.get("/auth/login?reauth=1", follow_redirects=False)
    assert r.status_code in (302, 307) and "max_age=0" in r.headers["location"]
    back = await _google_login(gclient)
    assert back.status_code == 302 and back.headers["location"] == "/?reauth=done"
    again = await _google_login(gclient)
    assert again.headers["location"] == "/"  # the flag is spent


async def test_fresh_sign_in_window_and_googles_auth_time(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth_mod, "_now", lambda: now[0])
    await _google_login(gclient)
    v = (await gclient.get("/v1/permissions")).json()
    assert v["can_reauth"] is True and v["fresh_sign_in_s"] == 300
    now[0] += 299
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 1
    now[0] += 2
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 0
    # Google says the owner last authenticated an hour ago: not fresh
    await _google_login(gclient, auth_time=int(now[0] - 3600))
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 0
    await _google_login(gclient, auth_time=int(now[0] - 10))
    assert (await gclient.get("/v1/permissions")).json()["fresh_sign_in_s"] == 290


async def test_lost_passkey_recovery_with_a_fresh_google_sign_in(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth_mod, "_now", lambda: now[0])
    await _google_login(gclient)
    v = await _register(gclient, SoftAuthenticator(origin=ORIGIN))
    cid = v["passkeys"][0]["id"]
    now[0] += 600  # ten minutes later the passkey is lost
    r = await gclient.post(f"/v1/passkeys/{cid}/remove", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["reason"] == "reauth"
    await _google_login(gclient)  # /auth/login?reauth=1 → Google → back
    r = await gclient.post(f"/v1/passkeys/{cid}/remove", json={}, headers=CSRF)
    assert r.status_code == 200 and r.json()["passkeys"] == []
    assert r.json()["require_passkey"] is False


async def test_a_second_passkey_needs_proof_after_the_window(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth_mod, "_now", lambda: now[0])
    await _google_login(gclient)
    auth = SoftAuthenticator(origin=ORIGIN)
    await _register(gclient, auth)
    now[0] += 301
    r = await gclient.post("/v1/passkeys/register/options", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "proof_required"
    proof = await _proof(gclient, auth, purpose="add")
    v = await _register(gclient, auth, proof=proof)
    assert len(v["passkeys"]) == 2


async def test_cookie_writes_need_the_csrf_header(gclient: AsyncClient) -> None:
    await _google_login(gclient)
    r = await gclient.put("/v1/permissions", json={"groups": {"web": "deny"}})
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = await gclient.post("/v1/passkeys/challenge", json={"purpose": "add"})
    assert r.status_code == 403 and r.json()["error"] == "csrf"


async def test_signed_out_gets_401(gclient: AsyncClient) -> None:
    assert (await gclient.get("/v1/permissions")).status_code == 401
    r = await gclient.post("/v1/passkeys/register/options", json={}, headers=CSRF)
    assert r.status_code == 401
