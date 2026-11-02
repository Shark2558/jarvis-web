# tests/test_voice_persona.py — slice 9 D7/D8: the wit dial (three stable persona variants, every
# hard limit in each), the spoken-reply rule in the trailer only for `channel: voice`, the Brain
# choosing the variant from the owner's voice settings (failure → film, never a failed chat), and
# training brains keeping every restriction.
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from billing_fakes import FREE_TIERS

import jarvis.core.brain as brain_module
from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.core.prompts import (
    DEFAULT_WIT,
    HARD_LIMITS,
    PERSONA_VERSION,
    VOICE_RULE_HEADING,
    WIT_LEVELS,
    build_system_prompt,
    build_trailer,
)
from jarvis.llm.base import ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import Gateway, Policy, ToolRegistry
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool

MOCK_TIERS = {t: f"mock-{t.value}" for t in ModelTier}


def _settings(**kw: object) -> Settings:
    return Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
        **kw,  # type: ignore[arg-type]
    )


class Wit:
    def __init__(self, level: str = "film", *, fail: bool = False, delay: float = 0.0) -> None:
        self.level, self.fail, self.delay, self.calls = level, fail, delay, 0

    async def wit_for(self, uid: str) -> str:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("settings store down")
        return self.level


def _brain(wit: Wit | None, *, training: bool = False) -> tuple[Brain, MockProvider]:
    p = MockProvider()
    spec = BrainSpec(
        id="b",
        label="B",
        provider=p,
        tiers=FREE_TIERS if training else MOCK_TIERS,
        trains_on_content=training,
    )
    reg = BrainRegistry([spec], default_id="b")
    return Brain(brains=reg, store=InMemorySessionStore(), settings=_settings(), wit=wit), p


# ---- prompts ---------------------------------------------------------------------------------


def test_version_and_levels() -> None:
    assert PERSONA_VERSION == "p4.1"  # slice 10 integration: bumped once for B, C and E
    assert [w.id for w in WIT_LEVELS] == ["measured", "film", "extra"]
    assert DEFAULT_WIT == "film"
    assert all(w.label and w.description for w in WIT_LEVELS)


@pytest.mark.parametrize("wit", ["measured", "film", "extra"])
def test_slice_10_paragraphs_are_each_present_once_in_their_own_block(wit: str) -> None:
    p = build_system_prompt(honorific="Sir", wit=wit)
    heads = [
        "\nWeb search (standing rule)\n",
        "\nTo-do list (standing rule)\n",
        "\nAttached files (standing rule)\n",
    ]
    assert [p.count(h) for h in heads] == [1, 1, 1]
    at = [p.index(h) for h in heads]
    assert at == sorted(at) and p.index("Memory (standing rule)") < at[0]


@pytest.mark.parametrize("wit", ["measured", "film", "extra"])
def test_every_variant_carries_every_hard_limit(wit: str) -> None:
    p = build_system_prompt(honorific="Sir", wit=wit)
    for rule in HARD_LIMITS:
        assert rule in p, (wit, rule)
    assert "{" not in p and "}" not in p
    assert p == build_system_prompt(honorific="Sir", wit=wit)  # stable → cacheable


def test_variants_differ_and_default_is_film() -> None:
    texts = {w.id: build_system_prompt(honorific="Sir", wit=w.id) for w in WIT_LEVELS}
    assert len(set(texts.values())) == 3
    assert build_system_prompt(honorific="Sir") == texts["film"]
    assert "at most one light quip" in texts["film"]
    assert "teasing" in texts["extra"] and "teasing" not in texts["film"]


def test_hard_limits_name_the_d8_cases() -> None:
    text = " ".join(HARD_LIMITS).lower()
    for word in (
        "answer first",
        "never changes facts",
        "confirmations",
        "approvals",
        "money lost",
        "errors",
        "bad news",
        "health",
        "safety",
        "grief",
        "other people",
        "third parties",
        "never quote films",
        "film character",
        "imitate the actor",
    ):
        assert word in text, word


def test_honorific_is_configurable() -> None:
    p = build_system_prompt(honorific="Ma'am", wit="extra")
    assert '"Ma\'am"' in p and "Sir" not in p


@pytest.mark.parametrize(
    ("wit", "line"),
    [
        ("film", "Your four o'clock overlaps your four o'clock, Ma'am."),
        ("extra", "Three meetings back to back, Ma'am."),
    ],
)
def test_the_film_and_extra_example_lines_use_the_configured_honorific(wit: str, line: str) -> None:
    """Review: the new example lines must substitute the honorific, never hard-code "Sir"."""
    rule = next(w.rule for w in WIT_LEVELS if w.id == wit)
    assert "Sir" not in rule and "{honorific}" in rule
    p = " ".join(build_system_prompt(honorific="Ma'am", wit=wit).split())
    assert line in p and "Sir" not in p and "{honorific}" not in p


def test_unknown_wit_is_refused() -> None:
    with pytest.raises(ValueError):
        build_system_prompt(honorific="Sir", wit="slapstick")


def test_voice_rule_only_on_voice() -> None:
    text = build_trailer(tz="Asia/Kolkata", session_id="s", turn_index=1)
    voice = build_trailer(tz="Asia/Kolkata", session_id="s", turn_index=1, channel="voice")
    assert VOICE_RULE_HEADING not in text
    assert VOICE_RULE_HEADING in voice
    low = voice.lower()
    for word in ("answer first", "60 words", "markdown", "urls", "on screen", "numbers"):
        assert word in low, word


def test_chat_request_channel_defaults_to_text() -> None:
    assert ChatRequest(message="hi").channel == "text"
    assert ChatRequest(message="hi", channel="voice").channel == "voice"
    with pytest.raises(ValueError):
        ChatRequest(message="hi", channel="video")  # type: ignore[arg-type]


# ---- the Brain -------------------------------------------------------------------------------


async def test_brain_uses_the_owners_wit_level() -> None:
    brain, p = _brain(Wit("extra"))
    await brain.chat(ChatRequest(message="hello", user_id="u1"))
    assert p.calls[0].system.startswith(build_system_prompt(honorific="Sir", wit="extra"))


async def test_brain_without_settings_or_with_a_failing_store_uses_film() -> None:
    for wit in (None, Wit("extra", fail=True), Wit("nonsense")):
        brain, p = _brain(wit)
        res = await brain.chat(ChatRequest(message="hello", user_id="u1"))
        assert res.reply
        assert p.calls[0].system.startswith(build_system_prompt(honorific="Sir", wit="film"))


async def test_a_slow_settings_read_never_holds_the_reply() -> None:
    brain, p = _brain(Wit("extra", delay=5.0))
    res = await asyncio.wait_for(brain.chat(ChatRequest(message="hi", user_id="u1")), 3.0)
    assert res.reply
    assert p.calls[0].system.startswith(build_system_prompt(honorific="Sir", wit="film"))


async def test_voice_channel_adds_the_spoken_rule_to_chat_and_stream() -> None:
    brain, p = _brain(Wit("film"))
    await brain.chat(ChatRequest(message="hi", user_id="u1", channel="voice"))
    await brain.chat(ChatRequest(message="hi", user_id="u1"))
    async for _ in brain.chat_stream(ChatRequest(message="hi", user_id="u1", channel="voice")):
        pass
    assert VOICE_RULE_HEADING in p.calls[0].system
    assert VOICE_RULE_HEADING not in p.calls[1].system
    assert VOICE_RULE_HEADING in p.calls[2].system


async def test_stream_uses_the_wit_level() -> None:
    brain, p = _brain(Wit("measured"))
    async for _ in brain.chat_stream(ChatRequest(message="hi", user_id="u1")):
        pass
    assert p.calls[0].system.startswith(build_system_prompt(honorific="Sir", wit="measured"))


async def test_training_brain_gets_wit_and_voice_rule_but_still_no_tools() -> None:
    brain, p = _brain(Wit("extra"), training=True)
    await brain.chat(ChatRequest(message="hi", user_id="u1", channel="voice"))
    call = p.calls[0]
    assert call.system.startswith(build_system_prompt(honorific="Sir", wit="extra"))
    assert VOICE_RULE_HEADING in call.system
    assert call.tools is None


async def test_new_sessions_record_the_persona_version() -> None:
    brain, _ = _brain(None)
    res = await brain.chat(ChatRequest(message="hi", user_id="u1"))
    s = await brain.store.get(res.session_id)
    assert s is not None and s.metadata["persona"] == "p4.1"


# ---- review fixes (slice 9 backend review) -----------------------------------------------------


def _tool_brain(wit: Wit) -> tuple[Brain, MockProvider]:
    """A brain with one read-only tool, so a turn makes more than one model call."""
    reg = ToolRegistry()
    reg.register(
        Tool(
            "clock",
            "What time is it?",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            lambda a: {"time": "10:00"},
            trusted_output=True,
        )
    )
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    p = MockProvider()
    spec = BrainSpec(id="b", label="B", provider=p, tiers=MOCK_TIERS)
    brain = Brain(
        brains=BrainRegistry([spec], default_id="b"),
        store=InMemorySessionStore(),
        settings=_settings(),
        gateway=gw,
        wit=wit,
    )
    return brain, p


async def test_the_wit_level_is_read_once_per_turn_not_per_model_call() -> None:
    wit = Wit("extra")
    brain, p = _tool_brain(wit)
    p.script_tool_calls([ToolCall(id="t1", name="clock", arguments={})])
    p.script_tool_calls([ToolCall(id="t2", name="clock", arguments={})], "Ten o'clock, Sir.")
    res = await brain.chat(ChatRequest(message="time?", user_id="u1"))
    assert res.reply == "Ten o'clock, Sir." and len(p.calls) == 3
    assert wit.calls == 1
    extra = build_system_prompt(honorific="Sir", wit="extra")
    assert all(c.system.startswith(extra) for c in p.calls)


def test_persona_selection_lives_in_its_own_module_and_brain_stays_small() -> None:
    from jarvis.core.persona import WIT_READ_TIMEOUT_S, Persona, WitSource

    assert WIT_READ_TIMEOUT_S <= 1.5 and Persona and WitSource
    lines = Path(brain_module.__file__).read_text(encoding="utf-8").count("\n")
    assert lines <= 800, lines


async def test_persona_falls_back_to_film_on_failure_unknown_or_slow() -> None:
    from jarvis.core.persona import Persona

    film = build_system_prompt(honorific="Sir", wit="film")
    assert await Persona(honorific="Sir", wit=None).system_for("u1") == film
    for wit in (Wit("x", fail=True), Wit("nonsense"), Wit("extra", delay=5.0)):
        got = await asyncio.wait_for(Persona(honorific="Sir", wit=wit).system_for("u1"), 3.0)
        assert got == film
    measured = await Persona(honorific="Ma'am", wit=Wit("measured")).system_for("u1")
    assert measured == build_system_prompt(honorific="Ma'am", wit="measured")
