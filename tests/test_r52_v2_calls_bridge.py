# tests/test_r52_v2_calls_bridge.py -- R5.2 V2: R18's call speech ports on the laptop speech kit
# (I0 seams "R18 reuse"). `LaptopHearing` / `LaptopCallVoice` satisfy `jarvis.calls.ports.Hearing`
# and `Voice` with the name "laptop" (`SpeechOption.LAPTOP`); the I1 join registers them in R18's
# `build_speech(..., laptop=...)`. Every failure is R18's `SpeechUnavailable` in plain words (the
# caller tries the next option): the kit off, slow or refusing, a language it has no engine for.
from __future__ import annotations

import hashlib

import pytest

from jarvis.calls.models import ENGLISH, Heard, SpeechOption
from jarvis.calls.ports import Hearing, SpeechUnavailable, Voice
from jarvis.localspeech import protocol as p
from jarvis.localspeech.memory import INDIAN_TEST_LANGUAGES, MemoryKit
from jarvis.voice.calls_bridge import LaptopCallVoice, LaptopHearing, laptop_speech
from jarvis.voice.laptop import LaptopVoice

HINDI, MALAYALAM = INDIAN_TEST_LANGUAGES
ONE_SECOND = b"\x01\x00" * p.SAMPLE_RATE


def bridge(kit: MemoryKit | None = None) -> tuple[Hearing, Voice, MemoryKit]:
    kit = kit if kit is not None else MemoryKit()
    hearing, voice = laptop_speech(LaptopVoice(kit, health_s=30))
    assert hearing is not None and voice is not None
    return hearing, voice, kit


def test_both_are_named_laptop_for_r18s_selection() -> None:
    hearing, voice, _ = bridge()
    assert hearing.name == voice.name == SpeechOption.LAPTOP.value == "laptop"
    assert isinstance(hearing, LaptopHearing) and isinstance(voice, LaptopCallVoice)


def test_no_kit_means_no_laptop_option() -> None:
    assert laptop_speech(LaptopVoice(None, health_s=30)) == (None, None)


async def test_it_hears_in_the_first_language_the_kit_has() -> None:
    kit = MemoryKit(heard={hashlib.sha256(ONE_SECOND).hexdigest(): "namaskaram"})
    hearing, _, _ = bridge(kit)
    heard = await hearing.transcribe(ONE_SECOND, ["as-IN", MALAYALAM, ENGLISH])
    assert heard == Heard(lang=MALAYALAM, text="namaskaram", confidence=0.9, seconds=1.0)


async def test_too_little_audio_is_heard_as_nothing() -> None:
    hearing, _, kit = bridge()
    heard = await hearing.transcribe(b"\x01\x00" * 100, [ENGLISH])
    assert heard.text == "" and heard.lang == ENGLISH and "stt" not in kit.calls


async def test_it_speaks_pcm16() -> None:
    _, voice, _ = bridge()
    pcm = await voice.speak("Namaste, I am calling for Mr Sharma.", HINDI)
    assert pcm and len(pcm) % 2 == 0
    assert await voice.speak("  ", HINDI) == b""


@pytest.mark.parametrize("reason", ["offline", "timeout", "busy", "unauthorized"])
async def test_a_kit_failure_is_speech_unavailable(reason: p.UnavailableReason) -> None:
    hearing, voice, kit = bridge()
    kit.down = reason
    with pytest.raises(SpeechUnavailable) as heard:
        await hearing.transcribe(ONE_SECOND, [ENGLISH])
    with pytest.raises(SpeechUnavailable):
        await voice.speak("Hello.", ENGLISH)
    assert "Bearer" not in str(heard.value) and str(heard.value)


async def test_a_slow_kit_is_not_used_for_a_call() -> None:
    kit = MemoryKit()
    kit.slow = True
    hearing, voice, _ = bridge(kit)
    with pytest.raises(SpeechUnavailable):
        await hearing.transcribe(ONE_SECOND, [ENGLISH])
    with pytest.raises(SpeechUnavailable):
        await voice.speak("Hello.", ENGLISH)
    assert "stt" not in kit.calls and "tts" not in kit.calls


async def test_a_language_without_an_engine_or_too_much_is_speech_unavailable() -> None:
    hearing, voice, kit = bridge()
    with pytest.raises(SpeechUnavailable):
        await hearing.transcribe(ONE_SECOND, ["as-IN"])
    with pytest.raises(SpeechUnavailable):
        await voice.speak("x", "as-IN")
    with pytest.raises(SpeechUnavailable):
        await voice.speak("x" * (p.TTS_MAX_CHARS + 1), ENGLISH)
    with pytest.raises(SpeechUnavailable):
        await hearing.transcribe(b"\x00\x00" * p.SAMPLE_RATE * 61, [ENGLISH])
    assert "stt" not in kit.calls and "tts" not in kit.calls


async def test_a_refusal_is_speech_unavailable_in_plain_words() -> None:
    class Refusing(MemoryKit):
        async def stt(self, req: p.SttRequest) -> p.SttResult:
            raise p.KitRefused("bad_audio", "the kit's own words <b>")

    hearing, _, _ = bridge(Refusing())
    with pytest.raises(SpeechUnavailable) as refused:
        await hearing.transcribe(ONE_SECOND, [ENGLISH])
    assert "<b>" not in str(refused.value)
