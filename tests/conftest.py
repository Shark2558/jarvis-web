# tests/conftest.py
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import MemoryTokenStore
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
        usd_inr_live=False,  # never call frankfurter.dev from tests (the default rate, 95.24)
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

from google_fakes import GOOGLE_EMAIL, GOOGLE_NOW, GOOGLE_UID, FakeGoogle, google_tokens  # noqa: E402,F401


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
