# tests/test_r4_i2_noai_failclosed.py -- R4 I2 F1: the No-AI switch is FAIL-CLOSED and honoured on
# every model-calling path, including a cold start (persisted "none", nothing loaded yet).
from __future__ import annotations

import pytest
from research_fakes import FakeModel, FakeSearcher

from jarvis.brief.summarize import Prepared as BriefPrepared
from jarvis.brief.summarize import Summarizer
from jarvis.config import Settings
from jarvis.health.probes import brain_probe
from jarvis.llm.base import ChatMessage, Role
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import BrainHealth, BrainOff, ModelRouter, ModelTier
from jarvis.offline.mode import BrainMode
from jarvis.people.research import PeopleService
from jarvis.recall.extract import Extractor
from jarvis.recall.extract import Prepared as LearnPrepared
from jarvis.storage.docs import MemoryDocs

TIERS = {t: f"mock-{t.value}" for t in ModelTier}
MSG = [ChatMessage(role=Role.USER, content="hi")]


async def persisted(settings: Settings, value: str, uid: str = "owner") -> MemoryDocs:
    docs = MemoryDocs()
    await BrainMode(settings, docs).set(uid, value, by=uid)  # type: ignore[arg-type]
    return docs


def bound_registry(mode: BrainMode):
    provider = MockProvider()
    brains = BrainRegistry(
        [BrainSpec(id="mock", label="Mock", provider=provider, tiers=TIERS)], default_id="mock"
    )
    router = brains.router_for("mock")
    router.bind_blocked(lambda: mode.current == "none", mode.load_known)
    return brains, router, provider


# ---- BrainMode ------------------------------------------------------------------------------


async def test_a_store_with_nothing_loaded_reads_none(settings: Settings) -> None:
    mode = BrainMode(settings, MemoryDocs())

    assert mode.current == "none"  # fail closed: we cannot tell yet


async def test_any_closed_owner_keeps_the_router_closed(settings: Settings) -> None:
    docs = await persisted(settings, "ai", "a")
    await BrainMode(settings, docs).set("b", "none", by="b")
    mode = BrainMode(settings, docs)

    await mode.load("a")
    assert mode.current == "ai"
    await mode.load("b")
    assert mode.current == "none"


async def test_the_persisted_value_beats_the_env_default_both_ways(settings: Settings) -> None:
    env_none = settings.model_copy(update={"brain_mode": "none"})
    ai_doc = BrainMode(env_none, await persisted(settings, "ai"))
    none_doc = BrainMode(settings, await persisted(settings, "none"))

    assert await ai_doc.load("owner") == "ai"
    assert await none_doc.load("owner") == "none"


async def test_load_known_refreshes_every_loaded_owner(settings: Settings) -> None:
    docs = await persisted(settings, "ai")
    mode = BrainMode(settings, docs)
    await mode.load("owner")
    await BrainMode(settings, docs).set("owner", "none", by="o")  # flipped elsewhere

    await mode.load_known(force=True)

    assert mode.current == "none"


# ---- the router guard ------------------------------------------------------------------------


async def test_a_cold_router_refuses_complete_and_stream_with_zero_provider_calls(
    settings: Settings,
) -> None:
    mode = BrainMode(settings, await persisted(settings, "none"))
    _, router, provider = bound_registry(mode)

    with pytest.raises(BrainOff):
        await router.complete(tier=ModelTier.FAST, system="s", messages=MSG, max_tokens=5)
    with pytest.raises(BrainOff):
        async for _ in router.stream(tier=ModelTier.FAST, system="s", messages=MSG, max_tokens=5):
            pass

    assert provider.calls == []


async def test_the_router_refreshes_a_flip_made_elsewhere_within_five_seconds(
    settings: Settings,
) -> None:
    docs = await persisted(settings, "ai")
    clock = [0.0]
    mode = BrainMode(settings, docs, clock=lambda: clock[0])
    await mode.load("owner")
    provider = MockProvider()
    router = ModelRouter(provider, TIERS, clock=lambda: clock[0])
    router.bind_blocked(lambda: mode.current == "none", mode.load_known)
    await router.complete(tier=ModelTier.FAST, system="s", messages=MSG, max_tokens=5)
    await BrainMode(settings, docs).set("owner", "none", by="o")
    clock[0] += 6.0

    with pytest.raises(BrainOff):
        await router.complete(tier=ModelTier.FAST, system="s", messages=MSG, max_tokens=5)

    assert len(provider.calls) == 1


async def test_blocked_now_refreshes_before_answering(settings: Settings) -> None:
    mode = BrainMode(settings, await persisted(settings, "none"))
    _, router, _ = bound_registry(mode)

    assert await router.blocked_now() is True


# ---- background callers ----------------------------------------------------------------------


async def test_the_brief_summary_and_the_recall_sweep_make_no_call_on_a_cold_start(
    settings: Settings,
) -> None:
    mode = BrainMode(settings, await persisted(settings, "none"))
    brains, _, provider = bound_registry(mode)

    block = await Summarizer(brains).run(
        BriefPrepared(brains.get("mock"), TIERS[ModelTier.FAST], "x")
    )
    out = await Extractor(brains).run(LearnPrepared(brains.get("mock"), TIERS[ModelTier.FAST], "x"))

    assert block.lines == () and out.extraction is None
    assert provider.calls == []


# ---- people research -------------------------------------------------------------------------


async def test_people_research_on_a_cold_start_calls_no_model(settings: Settings) -> None:
    mode = BrainMode(settings, await persisted(settings, "none"))
    model = FakeModel()
    svc = PeopleService(FakeSearcher(), model, mode=mode.load)

    await svc.research("owner", "Satya Nadella", "Microsoft")

    assert model.calls == []


async def test_people_research_with_the_ai_on_still_uses_the_model(settings: Settings) -> None:
    mode = BrainMode(settings, await persisted(settings, "ai"))
    model = FakeModel()
    svc = PeopleService(FakeSearcher(), model, mode=mode.load)

    await svc.research("owner", "Satya Nadella", "Microsoft")

    assert model.calls != []


# ---- the health probe ------------------------------------------------------------------------


async def test_the_brain_probe_says_switched_off_from_the_persisted_mode(
    settings: Settings,
) -> None:
    mode = BrainMode(settings, await persisted(settings, "none"))
    probe = brain_probe(lambda: BrainHealth(state="refused", on_laptop=False), mode.load)

    out = await probe.check("owner")

    assert out.status == "ok" and "switched off" in out.reason


async def test_the_brain_probe_reads_the_router_when_the_ai_is_on(settings: Settings) -> None:
    mode = BrainMode(settings, await persisted(settings, "ai"))
    probe = brain_probe(lambda: BrainHealth(state="refused", on_laptop=False), mode.load)

    out = await probe.check("owner")

    assert out.status == "down"
