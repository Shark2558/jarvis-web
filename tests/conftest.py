# tests/conftest.py
from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

TIERS = {
    ModelTier.FAST: "mock-fast",
    ModelTier.BALANCED: "mock-balanced",
    ModelTier.STRONG: "mock-strong",
}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        model_fast=TIERS[ModelTier.FAST],
        model_balanced=TIERS[ModelTier.BALANCED],
        model_strong=TIERS[ModelTier.STRONG],
        session_max_turns=6,
        session_max_chars=2_000,
        max_input_chars=500,
    )


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def store() -> InMemorySessionStore:
    return InMemorySessionStore(ttl_s=3600)


@pytest.fixture
def world() -> InMemoryWorld:
    return InMemoryWorld()


@pytest.fixture
def gateway(world: InMemoryWorld) -> Gateway:
    reg = ToolRegistry()
    for t in builtin_tools(world):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


@pytest.fixture
def brain(
    settings: Settings, provider: MockProvider, store: InMemorySessionStore, gateway: Gateway
) -> Brain:
    return Brain(
        router=ModelRouter(provider, TIERS), store=store, settings=settings, gateway=gateway
    )


@pytest.fixture
async def client(
    settings: Settings, provider: MockProvider, store: InMemorySessionStore, gateway: Gateway
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, provider=provider, store=store, gateway=gateway)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# ---- Google (slice 6): scriptable fake transport + a connected connector --------------------

GOOGLE_NOW = 1_800_000_000.0  # 2027-01-15T08:00:00Z
GOOGLE_UID = "u_owner"
GOOGLE_EMAIL = "akash@example.com"


class FakeGoogle:
    """Scriptable httpx transport: records every request, answers from `routes`. A route with
    several responses serves them in order and repeats the last one."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, list[httpx.Response]] = {}

    def on(self, method: str, url: str, *responses: httpx.Response) -> None:
        self.routes.setdefault(f"{method} {url}", []).extend(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.scheme}://{request.url.host}{request.url.path}"
        queue = self.routes.get(key)
        if not queue:
            return httpx.Response(599, json={"error": f"unscripted {key}"})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def sent(self, method: str, path_suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.endswith(path_suffix)]


def google_tokens(expires_at: float = GOOGLE_NOW + 3600, **over: object) -> GoogleTokens:
    base: dict[str, object] = {
        "email": GOOGLE_EMAIL,
        "access_token": "old-access",
        "refresh_token": "the-refresh",
        "expires_at": expires_at,
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }
    base.update(over)
    return GoogleTokens.model_validate(base)


@pytest.fixture
def fake_google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def token_store() -> MemoryTokenStore:
    return MemoryTokenStore()


@pytest.fixture
def google_conn(fake_google: FakeGoogle, token_store: MemoryTokenStore) -> GoogleConnector:
    return GoogleConnector(
        token_store,
        client_id="cid",
        client_secret=SecretStr("csecret"),
        http=fake_google.client(),
        now=lambda: GOOGLE_NOW,
    )


@pytest.fixture
async def connected(google_conn: GoogleConnector, token_store: MemoryTokenStore) -> GoogleConnector:
    await token_store.put(GOOGLE_UID, google_tokens())
    return google_conn
