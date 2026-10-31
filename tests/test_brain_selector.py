# tests/test_brain_selector.py — several brains at once, chosen per session from the console
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import LLMBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.llm.base import ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import Gateway

TIERS_A = {t: f"a-{t.value}" for t in ModelTier}
TIERS_B = {t: f"b-{t.value}" for t in ModelTier}


def _registry(
    default: str = "claude", training: bool = True
) -> tuple[BrainRegistry, MockProvider, MockProvider]:
    pa, pb = MockProvider(name="a"), MockProvider(name="b")
    reg = BrainRegistry(
        [
            BrainSpec(id="claude", label="Claude", provider=pa, tiers=TIERS_A),
            BrainSpec(
                id="free", label="Free", provider=pb, tiers=TIERS_B, trains_on_content=training
            ),
        ],
        default_id=default,
    )
    return reg, pa, pb


# ---- registry ------------------------------------------------------------------------------


def test_registry_basics_and_derived_tools_flag() -> None:
    reg, _, _ = _registry()
    assert [b.id for b in reg.list()] == ["claude", "free"]
    assert reg.default.id == "claude"
    assert reg.get("claude").tools_allowed is True
    assert reg.get("free").tools_allowed is False  # derived from trains_on_content
    with pytest.raises(LookupError):
        reg.get("nope")
    with pytest.raises(ValueError):
        BrainRegistry([], default_id="x")


def test_registry_from_settings_builds_every_configured_brain() -> None:
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.GEMINI,
        anthropic_api_key=SecretStr("sk-ant-x"),
        gemini_api_key=SecretStr("AIza-x"),
        openai_compat_base_url="http://localhost:11434/v1",
        openai_compat_model_balanced="llama3.2",
        openai_compat_label="Ollama (laptop)",
        openai_compat_trains_on_content=False,
    )
    reg = BrainRegistry.from_settings(s)
    ids = {b.id for b in reg.list()}
    assert ids == {"anthropic", "gemini", "custom"}
    assert reg.default.id == "gemini"
    assert reg.get("gemini").trains_on_content is True
    assert reg.get("gemini").tools_allowed is False
    custom = reg.get("custom")
    assert custom.label == "Ollama (laptop)" and custom.tools_allowed is True
    assert custom.tiers[ModelTier.FAST] == "llama3.2"  # fast/strong default to balanced
    assert reg.router_for("anthropic").resolve(ModelTier.BALANCED) == "claude-sonnet-5-5"


def test_registry_from_settings_requires_default_brain_to_be_configured() -> None:
    s = Settings(_env_file=None, env="dev", llm_backend=LLMBackend.GEMINI)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="GEMINI"):
        BrainRegistry.from_settings(s)


def test_registry_provider_override_wraps_single_brain() -> None:
    s = Settings(_env_file=None, env="dev", llm_backend=LLMBackend.ANTHROPIC)  # type: ignore[call-arg]
    reg = BrainRegistry.from_settings(s, provider=MockProvider())
    assert reg.default.id == "anthropic" and reg.default.provider.name == "mock"


def test_llm_timeout_default_is_short() -> None:
    assert Settings(_env_file=None).llm_timeout_s <= 20  # type: ignore[call-arg]


# ---- Brain -------------------------------------------------------------------------------------


def _brain(reg: BrainRegistry, settings: Settings, gateway: Gateway) -> Brain:
    return Brain(
        brains=reg, store=InMemorySessionStore(ttl_s=60), settings=settings, gateway=gateway
    )


async def test_request_brain_wins_then_sticks_to_the_session(
    settings: Settings, gateway: Gateway
) -> None:
    reg, pa, pb = _registry()
    brain = _brain(reg, settings, gateway)

    r1 = await brain.chat(ChatRequest(message="hi"))
    assert r1.brain == "claude" and pa.calls and not pb.calls

    r2 = await brain.chat(ChatRequest(message="switch", session_id=r1.session_id, brain="free"))
    assert r2.brain == "free" and len(pb.calls) == 1
    assert r2.model == "b-balanced"

    r3 = await brain.chat(ChatRequest(message="still?", session_id=r1.session_id))
    assert r3.brain == "free" and len(pb.calls) == 2  # remembered on the session

    sess = await brain.store.get(r1.session_id)
    assert sess is not None and sess.metadata["brain"] == "free"


async def test_unknown_brain_is_a_lookup_error(settings: Settings, gateway: Gateway) -> None:
    reg, _, _ = _registry()
    with pytest.raises(LookupError, match="brain"):
        await _brain(reg, settings, gateway).chat(ChatRequest(message="x", brain="hal9000"))


async def test_training_brain_never_receives_tool_specs(
    settings: Settings, gateway: Gateway
) -> None:
    reg, pa, pb = _registry()
    brain = _brain(reg, settings, gateway)
    # a non-training brain gets tools and can call them
    pa.script_tool_calls([ToolCall(id="t", name="list_tasks", arguments={})], "done")
    r = await brain.chat(ChatRequest(message="tasks?", brain="claude"))
    assert r.tool_calls == 1 and pa.calls[0].tools

    # the training brain gets none, even though a gateway with tools is wired in
    await brain.chat(ChatRequest(message="tasks?", brain="free"))
    assert pb.calls[0].tools is None


async def test_legacy_router_constructor_still_works(
    settings: Settings, provider: MockProvider, gateway: Gateway
) -> None:
    b = Brain(
        router=ModelRouter(provider, TIERS_A),
        store=InMemorySessionStore(ttl_s=60),
        settings=settings,
        gateway=gateway,
    )
    r = await b.chat(ChatRequest(message="hi"))
    assert r.brain == settings.llm_backend.value


# ---- API ----------------------------------------------------------------------------------------


@pytest.fixture
async def multi_client(settings: Settings, gateway: Gateway) -> AsyncIterator[AsyncClient]:
    reg, _, _ = _registry()
    app = create_app(settings, brains=reg, store=InMemorySessionStore(ttl_s=60), gateway=gateway)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c


async def test_brains_endpoint_lists_and_marks_default(multi_client: AsyncClient) -> None:
    r = await multi_client.get("/v1/brains")
    assert r.status_code == 200
    rows: list[dict[str, Any]] = r.json()
    by_id = {b["id"]: b for b in rows}
    assert by_id["claude"]["default"] is True and by_id["free"]["default"] is False
    assert by_id["free"]["trains_on_content"] is True and by_id["free"]["tools_allowed"] is False
    assert "improve" in by_id["free"]["warning"].lower() and by_id["claude"]["warning"] == ""
    assert by_id["claude"]["models"]["balanced"] == "a-balanced"


async def test_chat_accepts_brain_and_rejects_unknown(multi_client: AsyncClient) -> None:
    r = await multi_client.post("/v1/chat", json={"message": "hi", "brain": "free"})
    assert r.status_code == 200 and r.json()["brain"] == "free"
    bad = await multi_client.post("/v1/chat", json={"message": "hi", "brain": "nope"})
    assert bad.status_code == 404


# ---- history boundary: a training brain never sees earlier tool output --------------------------


async def test_switching_to_training_brain_withholds_earlier_history(
    settings: Settings, gateway: Gateway
) -> None:
    reg, pa, pb = _registry()
    brain = _brain(reg, settings, gateway)
    pa.script_tool_calls(
        [ToolCall(id="t", name="get_calendar", arguments={"day": "today"})],
        "You have a stand-up at 09:30, Sir.",
    )
    r1 = await brain.chat(ChatRequest(message="what's on today?", brain="claude"))
    assert r1.tool_calls == 1

    await brain.chat(ChatRequest(message="and now?", session_id=r1.session_id, brain="free"))
    sent = pb.calls[0].messages
    flat = " ".join(str(m.content) for m in sent)
    assert all(isinstance(m.content, str) for m in sent)  # no block turns at all
    assert "tool_result" not in flat and "get_calendar" not in flat
    assert "stand-up" not in flat and "what's on today" not in flat  # pre-switch history withheld
    assert [m.text() for m in sent] == ["and now?"]

    # switching back to the tool-capable brain restores the history (within the window)
    await brain.chat(ChatRequest(message="back", session_id=r1.session_id, brain="claude"))
    assert len(pa.calls[-1].messages) > 1


async def test_stream_on_training_brain_also_withholds_history(
    settings: Settings, gateway: Gateway
) -> None:
    reg, pa, pb = _registry()
    brain = _brain(reg, settings, gateway)
    r1 = await brain.chat(ChatRequest(message="secret: the budget is 4 crore", brain="claude"))
    chunks = [
        c
        async for c in brain.chat_stream(
            ChatRequest(message="summarise", session_id=r1.session_id, brain="free")
        )
    ]
    assert chunks
    assert "4 crore" not in " ".join(m.text() for m in pb.calls[0].messages)


async def test_approval_narration_never_calls_a_training_brain(
    settings: Settings, gateway: Gateway, world: Any
) -> None:
    reg, pa, pb = _registry()
    brain = _brain(reg, settings, gateway)
    pa.script_tool_calls(
        [ToolCall(id="s", name="send_message", arguments={"to": "a@b.c", "body": "hi"})],
        "Awaiting approval.",
    )
    r = await brain.chat(ChatRequest(message="tell a", brain="claude"))
    pending = r.pending_approvals[0]
    # owner switches the session to the free brain, then approves
    await brain.chat(ChatRequest(message="switch", session_id=r.session_id, brain="free"))
    calls_before = len(pb.calls)
    r2 = await brain.approve(pending.id, session_id=r.session_id)
    assert world.sent  # the action itself still executed
    assert len(pb.calls) == calls_before  # but the training brain saw nothing
    assert r2.reply.startswith("Done, Sir")


async def test_unknown_brain_creates_no_orphan_session(
    settings: Settings, gateway: Gateway
) -> None:
    reg, _, _ = _registry()
    brain = _brain(reg, settings, gateway)
    with pytest.raises(LookupError):
        await brain.chat(ChatRequest(message="x", brain="nope"))
    assert await brain.store.list_for_user("owner") == []


def test_openai_compat_base_url_validation() -> None:
    def mk(url: str) -> Settings:
        return Settings(_env_file=None, env="dev", openai_compat_base_url=url)  # type: ignore[call-arg]

    assert (
        mk("https://api.groq.com/openai/v1/").openai_compat_base_url
        == "https://api.groq.com/openai/v1"
    )
    assert mk("http://localhost:11434/v1").openai_compat_base_url  # loopback http is fine
    assert mk("http://192.168.1.20:11434/v1").openai_compat_base_url
    for bad in ("http://api.groq.com/v1", "ftp://x/v1", "not a url"):
        with pytest.raises(ValueError):
            mk(bad)
