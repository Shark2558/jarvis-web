# tests/test_connectors_api.py -- R4 D8/D9: /v1/connectors (owner only, CSRF, consent 422s, token
# never echoed or logged).
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from faces_fakes import ROOT
from google_fakes import FakeGoogle
from httpx import ASGITransport, AsyncClient
from photos_fakes import C1, Rig, consent_args, rig
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.integrations.github import GithubClient, GithubStore
from jarvis.keyring import Keyring
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.photos.api import install_connectors
from jarvis.photos.models import FaceHit
from jarvis.photos.tools import ConnectorDeps

OWNER = "akash@example.com"
UID = user_id_for_email(OWNER)
CSRF = {"X-Requested-With": "JARVIS"}
TOKEN = "ghp_SuperSecretTokenValue1234567890abcd"


@pytest.fixture
def gsettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    )


async def _login(c: AsyncClient) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": OWNER}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=abc&state=x")).status_code in (302, 307)


class Ctx:
    def __init__(self, c: AsyncClient, r: Rig, fake: FakeGoogle) -> None:
        self.c, self.r, self.fake = c, r, fake


@pytest.fixture
async def ctx(gsettings: Settings) -> AsyncIterator[Ctx]:
    r = rig([(FaceHit(C1, None, 0.5),)])
    fake = FakeGoogle()
    gh = GithubClient(GithubStore(r.f.docs, Keyring(ROOT)), http=fake.client())
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    install_connectors(app)
    async with app.router.lifespan_context(app):
        app.state.connectors = ConnectorDeps(gh, None, r.svc)
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        await _login(c)
        yield Ctx(c, r, fake)
        await c.aclose()


async def test_needs_sign_in_and_csrf(gsettings: Settings) -> None:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    install_connectors(app)
    async with app.router.lifespan_context(app):
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        assert (await c.get("/v1/connectors")).status_code == 401
        await _login(c)
        r = await c.put("/v1/connectors/github", json={"token": TOKEN})
        assert r.status_code == 403
        await c.aclose()


async def test_status_lists_the_three_connectors_and_the_consent_statements(ctx: Ctx) -> None:
    got = (await ctx.c.get("/v1/connectors")).json()
    assert got["github"]["connected"] is False and got["youtube"]["connected"] is False
    assert "<name> agreed" in got["statements"]["adult"]


async def test_connecting_github_never_echoes_or_logs_the_token(
    ctx: Ctx, caplog: pytest.LogCaptureFixture
) -> None:
    ctx.fake.on(
        "GET", "https://api.github.com/user", httpx.Response(200, json={"login": "akash-dev"})
    )
    with caplog.at_level(logging.DEBUG):
        r = await ctx.c.put("/v1/connectors/github", json={"token": TOKEN}, headers=CSRF)
    assert r.json() == {"connected": True, "login": "akash-dev"}
    assert TOKEN not in r.text and TOKEN not in caplog.text
    assert (await ctx.c.get("/v1/connectors")).json()["github"]["login"] == "akash-dev"
    assert (await ctx.c.delete("/v1/connectors/github", headers=CSRF)).json() == {
        "connected": False
    }


async def test_a_refused_github_token_is_a_422_without_the_token(ctx: Ctx) -> None:
    ctx.fake.on("GET", "https://api.github.com/user", httpx.Response(401, json={}))
    r = await ctx.c.put("/v1/connectors/github", json={"token": TOKEN}, headers=CSRF)
    assert r.status_code == 422 and TOKEN not in r.text


async def test_photos_flow_start_import_enrol_with_consent(ctx: Ctx) -> None:
    start = await ctx.c.post("/v1/connectors/photos/start", headers=CSRF)
    assert start.json()["picker_uri"].startswith("https://photos.google.com/")
    imp = (await ctx.c.post("/v1/connectors/photos/import", headers=CSRF)).json()
    assert imp["status"] == "done" and imp["unknown"] == [C1] and imp["recognised"] == []
    body = {"cluster": C1, "name": "Anjali", **consent_args()}
    ok = await ctx.c.post("/v1/connectors/photos/enrol", json=body, headers=CSRF)
    assert ok.status_code == 200 and ok.json()["at_home"] is True
    assert ctx.r.edge.enrolled and ctx.r.edge.enrolled[0][0] == C1


async def test_enrol_without_a_yes_is_422_and_nothing_is_enrolled(ctx: Ctx) -> None:
    await ctx.c.post("/v1/connectors/photos/start", headers=CSRF)
    await ctx.c.post("/v1/connectors/photos/import", headers=CSRF)
    body = {"cluster": C1, "name": "Anjali", **consent_args(confirm=False)}
    r = await ctx.c.post("/v1/connectors/photos/enrol", json=body, headers=CSRF)
    assert r.status_code == 422 and r.json()["error"] == "consent_missing"
    assert ctx.r.edge.enrolled == []


async def test_connectors_that_are_not_built_answer_503(gsettings: Settings) -> None:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    install_connectors(app)
    async with app.router.lifespan_context(app):
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        await _login(c)
        assert (await c.post("/v1/connectors/photos/start", headers=CSRF)).status_code == 503
        r = await c.put("/v1/connectors/github", json={"token": TOKEN}, headers=CSRF)
        assert r.status_code == 503
        await c.aclose()


# ---- review fixes ----------------------------------------------------------------------------

LONG_TOKEN = "ghp_" + "Z" * 400


@pytest.mark.parametrize(
    "payload",
    [
        {"token": LONG_TOKEN},  # too long
        {"token": TOKEN, "extra": "x"},  # extra field
        {TOKEN: "x"},  # the secret as a KEY
        {"token": 12345678},  # wrong type
        {"token": ["ghp_" + "Q" * 40]},  # wrong shape
        {"token": "has space " + TOKEN},
    ],
)
async def test_a_422_never_echoes_the_pasted_token(ctx: Ctx, payload: dict) -> None:
    r = await ctx.c.put("/v1/connectors/github", json=payload, headers=CSRF)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"
    for secret in (TOKEN, LONG_TOKEN, "Q" * 40, "Z" * 40):
        assert secret not in r.text
    assert "input" not in r.json() and "ctx" not in r.json()


async def test_a_malformed_json_body_is_a_clean_422(ctx: Ctx) -> None:
    r = await ctx.c.put(
        "/v1/connectors/github",
        content=b'{"token": "' + TOKEN.encode() + b'"',
        headers={**CSRF, "content-type": "application/json"},
    )
    assert r.status_code == 422 and TOKEN not in r.text


async def test_validation_errors_name_fields_only(ctx: Ctx) -> None:
    r = await ctx.c.post("/v1/connectors/photos/enrol", json={"cluster": 5}, headers=CSRF)
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"
    assert "cluster" in r.json()["detail"]


async def test_a_child_is_never_named_or_contact_matched_by_the_server(ctx: Ctx) -> None:
    child = await ctx.r.f.svc.add(
        UID,
        name="Mini",
        relation="family",
        child=True,
        vip=False,
        given_by="parent_guardian",
        consent_version="fc1",
        confirm=True,
    )
    await ctx.r.f.svc.apply_pictures(UID, {child.id: 5})
    ctx.r.edge.script = [(FaceHit(C1, child.id, 0.99),)]
    await ctx.c.post("/v1/connectors/photos/start", headers=CSRF)
    imp = (await ctx.c.post("/v1/connectors/photos/import", headers=CSRF)).json()
    assert imp["recognised"] == [{"name": "a child from your family", "child": True}]
    assert "Mini" not in str(imp)
    assert ctx.r.contacts.queries == []


async def test_waiting_import_returns_the_picker_link_again(ctx: Ctx) -> None:
    ctx.r.picker.ready = False
    await ctx.c.post("/v1/connectors/photos/start", headers=CSRF)
    imp = (await ctx.c.post("/v1/connectors/photos/import", headers=CSRF)).json()
    assert imp["status"] == "waiting" and imp["picker_uri"].startswith("https://photos.google.com/")


async def test_the_photos_path_never_logs_tokens_or_base_urls(
    ctx: Ctx, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        await ctx.c.post("/v1/connectors/photos/start", headers=CSRF)
        await ctx.c.post("/v1/connectors/photos/import", headers=CSRF)
    assert "Bearer" not in caplog.text and "googleusercontent" not in caplog.text


async def test_a_bad_home_reply_is_reported_apart_from_offline(ctx: Ctx) -> None:
    ctx.r.edge.bad = True
    await ctx.c.post("/v1/connectors/photos/start", headers=CSRF)
    imp = (await ctx.c.post("/v1/connectors/photos/import", headers=CSRF)).json()
    assert imp["status"] == "edge_error"
