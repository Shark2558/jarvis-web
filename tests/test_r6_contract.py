# tests/test_r6_contract.py -- R6 I0 seam 8 (docs/plans/r6-build-book.md "Contract"): every build
# book route exists from day one and, until builders B and C fill them, answers 503
# {error: "book_off", detail} with Cache-Control: no-store; nothing else answers under /v1/book.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
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
]
TOKEN = "contract-token"


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
async def test_every_contract_route_answers_book_off_without_caching(
    token_client: AsyncClient, method: str, path: str, body: Any
) -> None:
    r = await _call(token_client, method, path, body, Authorization=f"Bearer {TOKEN}")
    assert r.status_code == 503, (method, path, r.text)
    got = r.json()
    assert got["error"] == "book_off" and isinstance(got["detail"], str) and got["detail"]
    assert r.headers["cache-control"] == "no-store"


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
