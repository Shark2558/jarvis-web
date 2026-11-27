# tests/test_calls_speech_lines.py — R18 B: the pre-made call lines: translated once by the
# brain's fast tier (checked: keys, placeholders, numbers, facts), spoken once per language and
# voice, kept, and made again only when the English, the name or the translation changes.
from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from billing_fakes import PricedMock, registry
from calls_speech_fakes import UID, FakeVoice, billing

from jarvis.calls.models import OPENING_LINE
from jarvis.calls.speech.lines import LINES, MAX_AUDIO_BYTES, LinesCache
from jarvis.calls.speech.translate import (
    BrainTranslator,
    Translation,
    TranslationRefused,
    check_reply,
    private_brain,
)
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs


class CountingTranslator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def translate(self, english: Mapping[str, str], lang: str) -> dict[str, Translation]:
        self.calls.append(lang)
        return {k: Translation(f"[{lang}] {v}") for k, v in english.items()}


def test_the_opening_line_is_the_brief_s() -> None:
    assert LINES["opening"] == OPENING_LINE
    assert "This call is recorded." in LINES["opening"]
    assert {"hold", "goodbye", "handover", "call_back", "stop_recording"} <= set(LINES)


async def test_english_is_never_translated_and_is_spoken_once() -> None:
    t, voice = CountingTranslator(), FakeVoice("google")
    cache = LinesCache(MemoryDocs(), prefix="t_", translator=t)
    first = await cache.line("en-IN", "opening", "Ravi", voice)
    again = await cache.line("en-IN", "opening", "Ravi", voice)
    assert first == again and t.calls == []
    assert voice.spoken == [(OPENING_LINE.format(first_name="Ravi"), "en-IN")]


async def test_a_language_is_translated_once_and_each_line_spoken_once() -> None:
    docs = MemoryDocs()
    t, voice = CountingTranslator(), FakeVoice("azure")
    cache = LinesCache(docs, prefix="t_", translator=t)
    await cache.prepare("ml-IN", "Ravi", voice)
    await cache.prepare("ml-IN", "Ravi", voice)
    fresh = LinesCache(docs, prefix="t_", translator=t)  # another instance: the store is read
    await fresh.prepare("ml-IN", "Ravi", voice)
    assert t.calls == ["ml-IN"]
    assert len(voice.spoken) == len(LINES)
    spoken = dict(zip(LINES, (text for text, _ in voice.spoken), strict=True))
    assert all(text.startswith("[ml-IN] ") for text in spoken.values())
    assert "Ravi" in spoken["opening"] and "{first_name}" not in spoken["handover"]


async def test_a_new_name_or_a_new_voice_speaks_again_without_translating() -> None:
    t = CountingTranslator()
    cache = LinesCache(MemoryDocs(), prefix="t_", translator=t)
    g, a = FakeVoice("google"), FakeVoice("azure")
    await cache.line("hi-IN", "opening", "Ravi", g)
    await cache.line("hi-IN", "opening", "Meera", g)
    await cache.line("hi-IN", "opening", "Meera", a)
    await cache.line("hi-IN", "hold", "Meera", a)
    await cache.line("hi-IN", "hold", "Ravi", a)  # the hold line has no name: kept as it is
    assert t.calls == ["hi-IN"]
    assert len(g.spoken) == 2 and len(a.spoken) == 2


async def test_audio_too_large_to_keep_is_spoken_each_time() -> None:
    class Long(FakeVoice):
        async def speak(self, text: str, lang: str) -> bytes:
            self.spoken.append((text, lang))
            return b"\x00\x00" * (MAX_AUDIO_BYTES // 2 + 1)

    voice = Long("google")
    cache = LinesCache(MemoryDocs(), prefix="t_", translator=CountingTranslator())
    await cache.line("en-IN", "goodbye", "Ravi", voice)
    await cache.line("en-IN", "goodbye", "Ravi", voice)
    assert len(voice.spoken) == 2


async def test_no_name_no_line() -> None:
    cache = LinesCache(MemoryDocs(), prefix="t_", translator=CountingTranslator())
    with pytest.raises(ValueError):
        await cache.line("en-IN", "opening", "  ", FakeVoice("google"))
    with pytest.raises(KeyError):
        await cache.line("en-IN", "sing", "Ravi", FakeVoice("google"))


# ---- the brain's reply, checked ---------------------------------------------------------------

ENGLISH = {"a": "Hello, {first_name} here.", "b": "Pickup at 10:30, yes."}


def reply(a: str, b: str, facts: list[str] | None = None) -> str:
    return json.dumps({"a": {"text": a, "facts": []}, "b": {"text": b, "facts": facts or []}})


def test_a_good_reply_is_kept_with_its_true_facts() -> None:
    out = check_reply(
        ENGLISH, reply("नमस्ते, {first_name} बोल रहे हैं।", "हाँ, 10:30 बजे।", ["हाँ", "10:30", "कल"])
    )
    assert out["b"] == Translation("हाँ, 10:30 बजे।", ("हाँ", "10:30"))  # "कल" is not in it


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps({"a": {"text": "x {first_name}"}}),  # a key missing
        reply("नमस्ते", "हाँ, 10:30 बजे।"),  # the placeholder lost
        reply("नमस्ते {first_name} {owner}", "हाँ, 10:30 बजे।"),  # one added
        reply("नमस्ते {first_name}", "हाँ, 11:30 बजे।"),  # a number changed
        reply("नमस्ते {first_name}", ""),  # empty
        reply("नमस्ते {first_name}", "x" * 401),  # too long
    ],
)
def test_a_wrong_reply_is_refused_whole(bad: str) -> None:
    with pytest.raises(TranslationRefused):
        check_reply(ENGLISH, bad)


def test_numbers_in_another_script_count_as_the_same_numbers() -> None:
    out = check_reply(ENGLISH, reply("नमस्ते {first_name}", "हाँ, १०:३० बजे।"))
    assert out["b"].text == "हाँ, १०:३० बजे।"


async def test_the_brain_is_a_private_one_on_the_fast_tier_and_metered() -> None:
    paid = PricedMock(per_call=0.001)
    paid.script(reply("नमस्ते {first_name}", "हाँ 10:30"))
    brains = registry(paid=paid)
    b = billing()
    out = await BrainTranslator(brains, b, UID).translate(ENGLISH, "hi-IN")
    assert out["b"].text == "हाँ 10:30"
    call = paid.calls[-1]
    assert call.model == brains.get("anthropic").tiers[ModelTier.FAST]
    assert "Hindi" in call.system and call.tools in (None, [])
    assert (await b.month(UID)).by_brain["anthropic"] == pytest.approx(0.001)


def test_a_training_brain_is_never_chosen() -> None:
    brains = registry(default="gemini")
    chosen = private_brain(brains)
    assert chosen is not None and chosen.id != "gemini" and not chosen.trains_on_content
