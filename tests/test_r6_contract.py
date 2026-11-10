# tests/test_r6_contract.py -- R6 "Contract" (docs/plans/r6-build-book.md; I0 seam 8, I1 wired):
# exactly these build book routes, each behind a signed-in owner and `no-store`. With the book OFF
# (no keyring) every route answers 503 {error: "book_off", detail} except `GET /v1/book` (200
# {available: false, reason}: the panel says why, the console logs no error) and `GET
# /v1/book/show/lock` (200 {on: false}). Wired, a made-up book token gets 401 session_gone and
# never a 503 book_off. I1 added `GET /v1/book/show/lock` (D's show reads the lock without a token).
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

import jarvis.api.r6_wiring as r6
from jarvis.api import create_app
from jarvis.buildbook.release import ReleaseSource
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

RID = "3f2a1c9"
TICKET = "t" * 43
# (method, path, json body) -- every Contract row; ● rows carry X-Jarvis-Book in real use
ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/v1/book", None),
    ("POST", "/v1/book/open", {"audience": "owner"}),
    ("GET", "/v1/book/sections", None),
    ("GET", f"/v1/book/releases/{RID}/sections", None),
    ("POST", f"/v1/book/releases/{RID}/ticket", {}),
    ("GET", f"/v1/book/download/{TICKET}", None),
    ("GET", "/v1/book/show/script", None),
    ("POST", "/v1/book/show/speak", {"line_id": "s01b01"}),
    ("POST", "/v1/book/show/hear", None),
    ("POST", "/v1/book/show/ask", {"text": "How does JARVIS read e-mail?"}),
    ("POST", "/v1/book/show/beat", {}),
    ("POST", "/v1/book/close", {}),
    ("POST", "/v1/book/resume", {}),
    ("GET", "/v1/book/settings", None),
    ("PUT", "/v1/book/settings", {}),
    ("GET", "/v1/book/show/lock", None),  # I1 (INTEGRATION-D "Needed")
]
TOKEN = "contract-token"
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "book" / "_book"
ANSWER_WHEN_OFF = {("GET", "/v1/book"), ("GET", "/v1/book/show/lock")}
# wired, token-mode dev, a made-up book token: (status, error code or None for a 200 body)
WIRED: dict[tuple[str, str], tuple[int, str | None]] = {
    ("GET", "/v1/book"): (200, None),
    ("POST", "/v1/book/open"): (200, None),  # token-mode dev: the owner, no passkey (D8)
    ("GET", "/v1/book/download/" + TICKET): (410, "gone"),
    ("POST", "/v1/book/resume"): (403, "console_only"),
    ("GET", "/v1/book/settings"): (200, None),
    ("PUT", "/v1/book/settings"): (200, None),
    ("GET", "/v1/book/show/lock"): (200, None),
}


@pytest.fixture
async def token_client(settings: Settings) -> AsyncIterator[AsyncClient]:
    s = settings.model_copy(update={"api_token": SecretStr(TOKEN)})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def _call(c: AsyncClient, method: str, path: str, body: Any, **headers: str) -> Any:
    h = {"X-Jarvis-Book": "b" * 43, **headers}
    if path.endswith("/hear"):
        return await c.request(
            method, path, content=b"RIFF", headers={**h, "Content-Type": "audio/wav"}
        )
    return await c.request(method, path, json=body, headers=h)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_with_the_book_off_every_route_answers_book_off_without_caching(
    token_client: AsyncClient, method: str, path: str, body: Any
) -> None:
    r = await _call(token_client, method, path, body, Authorization=f"Bearer {TOKEN}")
    assert r.headers["cache-control"] == "no-store"
    got = r.json()
    if (method, path) in ANSWER_WHEN_OFF:
        assert r.status_code == 200 and got.get("available", got.get("on")) is False, got
        return
    assert r.status_code == 503, (method, path, r.text)
    assert got["error"] == "book_off" and isinstance(got["detail"], str) and got["detail"]


@pytest.fixture
async def wired_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(r6, "default_source", lambda: ReleaseSource(FIXTURE))
    s = settings.model_copy(update={"api_token": SecretStr(TOKEN), "token_key": SecretStr(KEY_B64)})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_wired_every_route_answers_for_real_without_caching(
    wired_client: AsyncClient, method: str, path: str, body: Any
) -> None:
    r = await _call(wired_client, method, path, body, Authorization=f"Bearer {TOKEN}")
    want = WIRED.get((method, path), (401, "session_gone"))  # every ● route: no such session
    assert r.headers["cache-control"] == "no-store"
    assert r.status_code == want[0], (method, path, r.text)
    got = r.json()
    if want[1] is None:
        assert "error" not in got
    else:
        assert got["error"] == want[1] and isinstance(got["detail"], str) and got["detail"]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_a_contract_route_wants_a_signed_in_owner_first(
    token_client: AsyncClient, method: str, path: str, body: Any
) -> None:
    r = await _call(token_client, method, path, body)
    assert r.status_code == 401, (method, path)


def test_the_app_has_exactly_the_contract_routes_under_v1_book(settings: Settings) -> None:
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    paths = app.openapi()["paths"]  # every mounted route, however FastAPI nests its routers
    mounted = {
        (m.upper(), path) for path, ops in paths.items() if path.startswith("/v1/book") for m in ops
    }
    want = {(m, p.replace(RID, "{rid}").replace(TICKET, "{ticket}")) for m, p, _ in ROUTES}
    assert mounted == want
