# tests/test_no_ai_brain.py
"""Brain in `brain_mode == "none"` (R4 D7): zero provider calls, deterministic tool routing."""

from __future__ import annotations

from typing import Any

import pytest
from research_fakes import FakeModel, FakeSearcher, fixed_mode

from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.llm.base import ChatMessage, Role
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import BrainOff, ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.rules import NO_AI_LINE
from jarvis.people.research import PeopleService
from jarvis.people.tools import PeopleDeps, people_tools
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.base import Tool
from tests.conftest import TIERS


def fake(name: str, result: Any, risk: ActionRisk = ActionRisk.READ_ONLY) -> Tool:
    async def run(_a: dict[str, Any]) -> Any:
        return result

    return Tool(name, f"fake {name}", {"type": "object", "properties": {}}, risk, run)


@pytest.fixture
def mode_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"brain_mode": "none", "user_timezone": "Asia/Kolkata"})


@pytest.fixture
def composer() -> FakeModel:
    return FakeModel()


@pytest.fixture
def no_ai_brain(
    mode_settings: Settings, provider: MockProvider, store: InMemorySessionStore, composer
) -> Brain:
    reg = ToolRegistry()
    for t in [
        fake("systems_check", {"spoken": "All systems nominal, Sir."}),
        fake("vitals_show", {"summary": "All keys are within their limits."}),
        fake("reminders_list", {"reminders": []}),
        fake("reminder_add", {"status": "set"}, ActionRisk.REVERSIBLE),
        fake("calendar_list_events", {"events": [{"title": "Standup"}]}),
        *people_tools(
            PeopleDeps(
                PeopleService(FakeSearcher(), composer, mode=fixed_mode(mode_settings.brain_mode))
            )
        ),
    ]:
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    return Brain(
        router=ModelRouter(provider, TIERS), store=store, settings=mode_settings, gateway=gw
    )


async def test_systems_check_answers_with_no_provider_call(
    no_ai_brain: Brain, provider: MockProvider
) -> None:
    resp = await no_ai_brain.chat(ChatRequest(message="run a systems check"))

    assert provider.calls == []
    assert "All systems nominal" in resp.reply
    assert resp.tool_calls == 1
    assert resp.cost_usd == 0 and resp.model == "no-ai"


async def test_vitals_and_calendar_work_without_the_ai(
    no_ai_brain: Brain, provider: MockProvider
) -> None:
    vitals = await no_ai_brain.chat(ChatRequest(message="show my vitals"))
    cal = await no_ai_brain.chat(ChatRequest(message="what's on my calendar today"))

    assert "within their limits" in vitals.reply
    assert "Standup" in cal.reply
    assert provider.calls == []


async def test_generative_request_gets_the_fixed_line_and_no_provider_call(
    no_ai_brain: Brain, provider: MockProvider
) -> None:
    resp = await no_ai_brain.chat(ChatRequest(message="draft an email to the vendor"))

    assert resp.reply == NO_AI_LINE
    assert provider.calls == []


async def test_the_exchange_is_stored_in_the_session(
    no_ai_brain: Brain, store: InMemorySessionStore
) -> None:
    resp = await no_ai_brain.chat(ChatRequest(message="systems check"))

    session = await store.get(resp.session_id)
    assert session is not None
    assert [t.role for t in session.turns] == [Role.USER, Role.ASSISTANT]


async def test_a_write_still_goes_through_the_gateway_policy(
    no_ai_brain: Brain, provider: MockProvider
) -> None:
    resp = await no_ai_brain.chat(ChatRequest(message="set a timer for 10 minutes"))

    assert provider.calls == []
    assert resp.tool_calls == 1
    assert resp.reply  # either it ran or it asked for the owner's OK, in plain words


async def test_open_profiles_lists_the_urls_with_no_summary_and_no_model(
    no_ai_brain: Brain, provider: MockProvider, composer: FakeModel
) -> None:
    resp = await no_ai_brain.chat(
        ChatRequest(message="open profiles for Satya Nadella at Microsoft")
    )

    assert composer.calls == [] and provider.calls == []
    assert "https://www.linkedin.com/in/satyanadella" in resp.reply


async def test_private_person_request_is_refused_in_plain_words(
    no_ai_brain: Brain,
) -> None:
    resp = await no_ai_brain.chat(
        ChatRequest(message="research Ravi Kumar my neighbour home address")
    )

    assert "public" in resp.reply.lower()


async def test_a_tool_that_is_not_registered_says_so(
    mode_settings: Settings, provider: MockProvider, store: InMemorySessionStore
) -> None:
    gw = Gateway(
        registry=ToolRegistry(), policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()
    )
    brain = Brain(
        router=ModelRouter(provider, TIERS), store=store, settings=mode_settings, gateway=gw
    )

    resp = await brain.chat(ChatRequest(message="show my vitals"))

    assert "isn't available" in resp.reply


async def test_no_gateway_still_answers_in_plain_words(
    mode_settings: Settings, provider: MockProvider, store: InMemorySessionStore
) -> None:
    brain = Brain(router=ModelRouter(provider, TIERS), store=store, settings=mode_settings)

    resp = await brain.chat(ChatRequest(message="show my vitals"))

    assert "isn't available" in resp.reply and provider.calls == []


async def test_streaming_yields_the_deterministic_reply(
    no_ai_brain: Brain, provider: MockProvider
) -> None:
    chunks = [d async for d in no_ai_brain.chat_stream(ChatRequest(message="systems check"))]

    assert "All systems nominal" in "".join(chunks)
    assert provider.calls == []


async def test_switching_back_to_ai_uses_the_provider_again(
    no_ai_brain: Brain, provider: MockProvider
) -> None:
    no_ai_brain.s.brain_mode = "ai"
    provider.script("Good day, Sir.")

    resp = await no_ai_brain.chat(ChatRequest(message="hello"))

    assert resp.reply == "Good day, Sir." and len(provider.calls) == 1


async def test_router_refuses_a_stray_model_call_in_no_ai_mode(
    no_ai_brain: Brain, provider: MockProvider
) -> None:
    router = no_ai_brain.router

    with pytest.raises(BrainOff):
        await router.complete(
            tier=ModelTier.FAST,
            system="s",
            messages=[ChatMessage(role=Role.USER, content="x")],
            max_tokens=10,
        )

    assert provider.calls == []


async def test_router_refuses_a_stray_stream_in_no_ai_mode(no_ai_brain: Brain) -> None:
    with pytest.raises(BrainOff):
        async for _ in no_ai_brain.router.stream(
            tier=ModelTier.FAST,
            system="s",
            messages=[ChatMessage(role=Role.USER, content="x")],
            max_tokens=10,
        ):
            pass


async def test_ai_mode_is_untouched_by_the_no_ai_code(
    settings: Settings, provider: MockProvider, store: InMemorySessionStore, gateway: Gateway
) -> None:
    brain = Brain(
        router=ModelRouter(provider, TIERS), store=store, settings=settings, gateway=gateway
    )

    resp = await brain.chat(ChatRequest(message="run a systems check"))

    assert len(provider.calls) == 1 and resp.model == "mock-balanced"


async def test_a_bare_private_name_gets_the_fixed_refusal_and_no_links_in_no_ai_mode(
    no_ai_brain: Brain, provider: MockProvider
) -> None:
    resp = await no_ai_brain.chat(ChatRequest(message="research Priya Nair"))

    assert "verify" in resp.reply and "https://" not in resp.reply
    assert provider.calls == []
