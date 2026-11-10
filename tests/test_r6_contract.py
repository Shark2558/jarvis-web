# tests/test_r6_contract.py
"""R6 I0: the build book's HTTP contract (docs/plans/r6-build-book.md "Contract", I0 item 8).

Every route in the Contract table exists with exactly its method, behind the same auth and CSRF
dependency as the console's other /v1 routes (`require_auth`), and every answer is `no-store`
(errors included). At I0 every route answers 503 {error: "book_off", detail}; on a server
without the token key (these apps) that stays the answer after parts B and C fill the routes,
because without a keyring the book is OFF (D6). Parts B and C extend this file when a route
gains a real answer; they never drop a path or a method from ROUTES.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import book as book_api
from jarvis.api import book_show as book_show_api
from jarvis.api import create_app
from jarvis.api.book_http import BOOK_OFF, BOOK_TOKEN_HEADER
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

OWNER = "owner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
RID = "3f2a1c9"
TICKET = "t" * 43
# (method, path template, a concrete path): the Contract table, in its order
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("GET", "/v1/book", "/v1/book"),
    ("POST", "/v1/book/open", "/v1/book/open"),
    ("GET", "/v1/book/sections", "/v1/book/sections"),
    ("GET", "/v1/book/releases/{rid}/sections", f"/v1/book/releases/{RID}/sections"),
    ("POST", "/v1/book/releases/{rid}/ticket", f"/v1/book/releases/{RID}/ticket"),
    ("GET", "/v1/book/download/{ticket}", f"/v1/book/download/{TICKET}"),
    ("GET", "/v1/book/show/script", "/v1/book/show/script"),
    ("POST", "/v1/book/show/speak", "/v1/book/show/speak"),
    ("POST", "/v1/book/show/hear", "/v1/book/show/hear"),
    ("POST", "/v1/book/show/ask", "/v1/book/show/ask"),
    ("POST", "/v1/book/show/beat", "/v1/book/show/beat"),
    ("POST", "/v1/book/close", "/v1/book/close"),
    ("POST", "/v1/book/resume", "/v1/book/resume"),
    ("GET", "/v1/book/settings", "/v1/book/settings"),
    ("PUT", "/v1/book/settings", "/v1/book/settings"),
)
OFF = {"error": "book_off", "detail": BOOK_OFF}


def _book_routes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in (*book_api.router.routes, *book_show_api.router.routes):
        assert isinstance(route, APIRoute)
        found |= {(m, route.path) for m in route.methods if m != "HEAD"}
    return found


async def _call(c: AsyncClient, method: str, path: str, **kw: Any) -> Any:
    body = {} if method in ("POST", "PUT") else None
    return await c.request(method, path, json=body, **kw)


def test_the_contract_header_and_detail() -> None:
    assert BOOK_TOKEN_HEADER == "X-Jarvis-Book"
    assert BOOK_OFF and "$" not in BOOK_OFF


async def test_every_contract_route_exists_with_exactly_its_method(client: AsyncClient) -> None:
    assert _book_routes() == {(m, t) for m, t, _ in ROUTES}  # B's router + C's router
    methods = {p: {m for m, _, q in ROUTES if q == p} for _, _, p in ROUTES}
    for path, allowed in methods.items():  # through the app: any other method is refused
        for method in {"GET", "POST", "PUT", "DELETE", "PATCH"} - allowed:
            r = await _call(client, method, path, headers=CSRF)
            assert r.status_code == 405, (method, path, r.status_code)


@pytest.mark.parametrize(("method", "template", "path"), ROUTES)
async def test_every_route_answers_book_off_and_no_store(
    client: AsyncClient, method: str, template: str, path: str
) -> None:
    r = await _call(client, method, path, headers={**CSRF, BOOK_TOKEN_HEADER: "x" * 43})
    assert r.status_code == 503, (method, path, r.text)
    assert r.json() == OFF
    assert r.headers["cache-control"] == "no-store"


# ---- the same auth and CSRF dependency as the console's other /v1 routes ---------------------
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


@pytest.fixture
async def gclient(gsettings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def _login(c: AsyncClient) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": OWNER}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=a&state=b")).status_code in (302, 307)


@pytest.mark.parametrize(("method", "template", "path"), ROUTES)
async def test_no_route_answers_without_the_owner_and_the_refusal_is_not_stored(
    gclient: AsyncClient, method: str, template: str, path: str
) -> None:
    r = await _call(gclient, method, path, headers=CSRF)
    assert r.status_code == 401, (method, path)
    assert r.headers["cache-control"] == "no-store"
    assert "book_off" not in r.text  # nothing about the book before the owner is known


async def test_cookie_writes_need_the_csrf_header_and_reads_do_not(gclient: AsyncClient) -> None:
    await _login(gclient)
    for method, _, path in ROUTES:
        bare = await _call(gclient, method, path)
        if method == "GET":
            assert bare.status_code == 503, path
        else:
            assert bare.status_code == 403 and bare.json()["error"] == "csrf", (method, path)
            assert bare.headers["cache-control"] == "no-store"
        r = await _call(gclient, method, path, headers=CSRF)
        assert r.status_code == 503 and r.json() == OFF, (method, path)


async def test_a_bearer_caller_is_authenticated_like_on_every_other_route(
    gclient: AsyncClient,
) -> None:
    # parts B and C refuse the console-only routes to a bearer with 403 console_only (D8)
    r = await gclient.get("/v1/book", headers={"Authorization": "Bearer cli-token"})
    assert r.status_code == 503 and r.json() == OFF


async def test_no_store_covers_only_the_book(client: AsyncClient) -> None:
    r = await client.get("/console/config")
    assert r.status_code == 200 and r.headers.get("cache-control") != "no-store"
    r = await client.get("/v1/bookshelf")  # a path that merely starts with the same letters
    assert r.status_code == 404 and r.headers.get("cache-control") != "no-store"
