# tests/test_r52_v2_laptop.py -- R5.2 V2: the laptop speech kit for the console's voice (plan 3.2;
# I0 seams). `LaptopVoice` keeps the kit's health for `local_speech_health_s` (a kit found down is
# not asked again meanwhile, and a stale "down" is re-checked in the background so no turn waits
# for an absent laptop); its STT / TTS adapters sit on `jarvis.voice.ports`. A kit that is off,
# slow or refusing is `LaptopUnavailable` (the service falls back silently: never Google's words),
# a recording the kit can't use is `BadAudio`. `LaptopApi.status` and the Vitals line say which
# engine served, at ₹0, and never the laptop's name or the kit's key.
from __future__ import annotations

import asyncio
import hashlib

import pytest
from pydantic import SecretStr

from jarvis.calls.models import ENGLISH
from jarvis.config import Settings
from jarvis.localspeech import protocol as p
from jarvis.localspeech.memory import MemoryKit
from jarvis.voice.laptop import (
    HEALTH_WAIT_S,
    LaptopUnavailable,
    LaptopVoice,
    kit_phrases,
    laptop_voice,
)
from jarvis.voice.ports import BadAudio, VoiceError
from jarvis.voice.profile_ports import LaptopApi

ONE_SECOND = b"\x01\x00" * p.SAMPLE_RATE
UID = "owner-1"
KEY = SecretStr("k" * 40)
URL = "https://my-laptop.tail1234.ts.net:8443"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def laptop(kit: MemoryKit | None = None, clock: Clock | None = None) -> LaptopVoice:
    return LaptopVoice(kit if kit is not None else MemoryKit(), health_s=30, clock=clock or Clock())


async def settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


# ---- health, cached ------------------------------------------------------------------------------
async def test_a_healthy_kit_is_ready_and_asked_once_per_period() -> None:
    kit, clock = MemoryKit(), Clock()
    lap = laptop(kit, clock)
    assert await lap.ready(p.Kind.STT) and await lap.ready(p.Kind.TTS)
    assert await lap.ready(p.Kind.STT, p.EngineSlot.WHISPER_MEDIUM)
    assert kit.calls == ["health"]
    clock.now += 31
    assert await lap.ready(p.Kind.STT)
    assert kit.calls == ["health", "health"]


@pytest.mark.parametrize("why", ["slow", "old", "offline", "unauthorized", "busy"])
async def test_a_slow_old_or_absent_kit_is_not_ready(why: str) -> None:
    kit = MemoryKit()
    if why == "slow":
        kit.slow = True
    elif why == "old":
        kit.base_health = kit.base_health.model_copy(update={"protocol": p.PROTOCOL + 1})
    else:
        kit.down = why  # type: ignore[assignment]
    lap = laptop(kit)
    assert not await lap.ready(p.Kind.STT)
    assert (await lap.status(UID)).state in ("slow", "old", "down")


async def test_a_missing_engine_is_not_ready() -> None:
    kit = MemoryKit()
    kit.base_health = kit.base_health.model_copy(
        update={"engines": tuple(e for e in kit.base_health.engines if e.kind is p.Kind.TTS)}
    )
    lap = laptop(kit)
    assert not await lap.ready(p.Kind.STT) and await lap.ready(p.Kind.TTS)


async def test_a_kit_found_down_is_not_asked_again_until_the_period_ends() -> None:
    kit, clock = MemoryKit(), Clock()
    kit.down = "offline"
    lap = laptop(kit, clock)
    assert not await lap.ready(p.Kind.STT)
    assert not await lap.ready(p.Kind.STT)
    assert kit.calls == ["health"]
    kit.down = None
    clock.now += 31
    assert not await lap.ready(p.Kind.STT)  # stale "down": answered at once, checked behind
    await settle()
    assert kit.calls == ["health", "health"]
    assert await lap.ready(p.Kind.STT)


async def test_a_kit_that_hangs_never_holds_a_turn_long() -> None:
    class Hanging(MemoryKit):
        async def health(self) -> p.KitHealth:
            await asyncio.sleep(5)
            return await super().health()

    lap = LaptopVoice(Hanging(), health_s=30, wait_s=0.05, clock=Clock())
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert not await lap.ready(p.Kind.STT)
    assert loop.time() - started < 1.0
    await lap.aclose()
    assert HEALTH_WAIT_S <= 3.0


# ---- listening -----------------------------------------------------------------------------------
async def test_listening_on_the_laptop() -> None:
    kit = MemoryKit(heard={hashlib.sha256(ONE_SECOND).hexdigest(): "lights on"})
    lap = laptop(kit)
    t = await lap.stt.recognize(
        ONE_SECOND,
        sample_rate=16_000,
        language="en-IN",
        phrases=("JARVIS",),
        slot=p.EngineSlot.WHISPER_SMALL,
    )
    assert (t.text, t.confidence, t.language, t.billed_seconds) == ("lights on", 0.9, ENGLISH, 0)
    assert lap.last_served(p.Kind.STT) == "laptop-whisper-small"


async def test_any_english_is_the_kits_english() -> None:
    lap = laptop()
    t = await lap.stt.recognize(ONE_SECOND, sample_rate=16_000, language="en-GB", phrases=())
    assert t.language == ENGLISH


def test_the_words_to_recognise_fit_the_kits_request() -> None:
    words = ("JARVIS", "x" * 41, "  ", "jarvis", *(f"word{i}" for i in range(80)))
    out = kit_phrases(words)
    assert len(out) == p.PHRASES_MAX and out[0] == "JARVIS"
    assert all(1 <= len(w) <= 40 for w in out) and "jarvis" not in out  # one spelling each
    p.SttRequest.of_pcm(ONE_SECOND, lang=ENGLISH, phrases=out)  # the kit's model accepts them


@pytest.mark.parametrize("reason", ["offline", "timeout", "busy", "unauthorized", "protocol"])
async def test_a_kit_failure_is_laptop_unavailable_and_marks_it_down(
    reason: p.UnavailableReason,
) -> None:
    kit = MemoryKit()
    lap = laptop(kit)
    assert await lap.ready(p.Kind.STT)
    kit.down = reason
    with pytest.raises(LaptopUnavailable) as down:
        await lap.stt.recognize(ONE_SECOND, sample_rate=16_000, language="en-IN", phrases=())
    assert down.value.reason == reason and isinstance(down.value, VoiceError)
    assert "Google" not in str(down.value)
    kit.down = None
    calls = len(kit.calls)
    assert not await lap.ready(p.Kind.STT)  # remembered: no new check this period
    assert len(kit.calls) == calls


async def test_a_recording_the_kit_cant_use_is_bad_audio_and_other_refusals_fall_back() -> None:
    class Refusing(MemoryKit):
        code: p.KitErrorCode = "bad_audio"

        async def stt(self, req: p.SttRequest) -> p.SttResult:
            raise p.KitRefused(self.code, "refused")

    kit = Refusing()
    lap = laptop(kit)
    with pytest.raises(BadAudio):
        await lap.stt.recognize(ONE_SECOND, sample_rate=16_000, language="en-IN", phrases=())
    kit.code = "unsupported_language"
    with pytest.raises(LaptopUnavailable):
        await lap.stt.recognize(ONE_SECOND, sample_rate=16_000, language="en-IN", phrases=())
    assert await lap.ready(p.Kind.STT)  # a refusal is about this request, not the kit


async def test_audio_the_kit_cant_take_falls_back_before_anything_is_sent() -> None:
    kit = MemoryKit()
    lap = laptop(kit)
    for rate, lang in ((8_000, "en-IN"), (16_000, "fr-FR")):
        with pytest.raises(LaptopUnavailable):
            await lap.stt.recognize(ONE_SECOND, sample_rate=rate, language=lang, phrases=())
    assert "stt" not in kit.calls


# ---- speaking ------------------------------------------------------------------------------------
async def test_speaking_on_the_laptop_answers_mp3() -> None:
    lap = laptop()
    audio = await lap.tts.synthesize("Good evening.", voice="en-GB-x", language="en-GB", rate=1.1)
    assert audio.startswith(b"ID3")
    assert lap.last_served(p.Kind.TTS) == "laptop-kokoro"
    assert await lap.tts.voices("en-GB")


async def test_speaking_failures_fall_back() -> None:
    kit = MemoryKit()
    lap = laptop(kit)
    with pytest.raises(LaptopUnavailable):
        await lap.tts.synthesize("x" * 601, voice="v", language="en-IN", rate=1.0)
    kit.down = "timeout"
    with pytest.raises(LaptopUnavailable) as down:
        await lap.tts.synthesize("Hello.", voice="v", language="en-IN", rate=1.0)
    assert down.value.reason == "timeout"


# ---- LaptopApi.status and the Vitals line --------------------------------------------------------
async def test_the_status_lists_the_engines_and_never_the_laptop() -> None:
    lap = laptop()
    api: LaptopApi = lap
    await lap.stt.recognize(ONE_SECOND, sample_rate=16_000, language="en-IN", phrases=())
    lap.note_served(p.Kind.TTS, "google")
    view = await api.status(UID)
    data = view.model_dump(mode="json") if hasattr(view, "model_dump") else view
    assert data["configured"] is True and data["state"] == "ready"
    assert {e["slot"] for e in data["engines"]} >= {"whisper-small", "kokoro"}
    assert ENGLISH in data["languages"]["hear"] and data["inr_per_minute"] == 0.0
    assert data["last_heard_by"] == "laptop-whisper-small" and data["last_spoken_by"] == "google"
    shown = str(data)
    assert "ts.net" not in shown and KEY.get_secret_value() not in shown


async def test_without_a_kit_the_laptop_is_off() -> None:
    lap = LaptopVoice(None, health_s=30)
    assert not await lap.ready(p.Kind.STT)
    view = await lap.status(UID)
    assert view.configured is False and view.state == "off" and view.engines == []
    assert await lap.vitals_line(UID) is None
    with pytest.raises(LaptopUnavailable) as off:
        await lap.stt.recognize(ONE_SECOND, sample_rate=16_000, language="en-IN", phrases=())
    assert off.value.reason == "not_configured"


async def test_the_vitals_line_says_which_engine_served_at_no_cost() -> None:
    kit = MemoryKit()
    lap = laptop(kit)
    line = await lap.vitals_line(UID)
    assert line is not None and line.state == "ready" and line.heard_by is None
    await lap.tts.synthesize("Hello.", voice="v", language="en-IN", rate=1.0)
    lap.note_served(p.Kind.STT, "google")
    line = await lap.vitals_line(UID)
    assert line is not None
    assert (line.heard_by, line.spoken_by, line.inr_per_minute) == ("google", "laptop-kokoro", 0)
    kit.down = "offline"
    lap.mark_down("offline")
    down = await lap.vitals_line(UID)
    assert down is not None and down.state == "down"


# ---- built from the settings ---------------------------------------------------------------------
def test_built_from_the_settings(settings: Settings) -> None:
    off = laptop_voice(settings)
    assert off.kit is None
    on = laptop_voice(
        settings.model_copy(update={"local_speech_url": URL, "local_speech_key": KEY})
    )
    assert on.kit is not None and "tailscale" in repr(on.kit) and on.inr_per_minute == 0.0
    disabled = settings.model_copy(
        update={"local_speech_url": URL, "local_speech_key": KEY, "local_speech_enabled": False}
    )
    assert laptop_voice(disabled).kit is None
