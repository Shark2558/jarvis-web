# tests/test_voice_persona.py — slice 9 D7/D8: the wit dial (three stable persona variants, every
# hard limit in each), the spoken-reply rule in the trailer only for `channel: voice`, the Brain
# choosing the variant from the owner's voice settings (failure → film, never a failed chat), and
# training brains keeping every restriction.
from __future__ import annotations

import asyncio

import pytest
from billing_fakes import FREE_TIERS

from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
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
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore

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
    assert PERSONA_VERSION == "p4.0"
    assert [w.id for w in WIT_LEVELS] == ["measured", "film", "extra"]
    assert DEFAULT_WIT == "film"
    assert all(w.label and w.description for w in WIT_LEVELS)


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
    assert s is not None and s.metadata["persona"] == "p4.0"
