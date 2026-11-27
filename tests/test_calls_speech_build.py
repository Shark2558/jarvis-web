# tests/test_calls_speech_build.py — R18 B: the speech options a deployment has, from Settings:
# Google only with the cloud voice on, Azure / Bhashini only with their keys, Sarvam only with its
# key AND sarvam_enabled AND the owner's own YES on every request; the laptop when the desk offers.
from __future__ import annotations

import httpx
import pytest
from calls_speech_fakes import UID, FakeHearing, FakeVoice, billing, tone
from pydantic import SecretStr
from voice_fakes import FakeTokens

from jarvis.calls.speech.build import build_speech
from jarvis.calls.speech.errors import PaidOptionOff
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.config import Settings


async def yes() -> bool:
    return True


async def no() -> bool:
    return False


def meter() -> SpeechMeter:
    return SpeechMeter(billing(), UID)


def test_nothing_configured_builds_nothing_and_says_why() -> None:
    s = Settings(_env_file=None, voice_cloud=False)
    out = build_speech(s, meter(), http=httpx.AsyncClient(), google_tokens=None, sarvam_on=yes)
    assert out.hearing == {} and out.voices == {}
    assert set(out.missing) == {"laptop", "google", "azure", "bhashini", "sarvam"}
    assert "paid option and is off" in out.missing["sarvam"]


def test_every_option_with_its_settings() -> None:
    s = Settings(
        _env_file=None,
        voice_cloud=True,
        azure_speech_key=SecretStr("k"),
        bhashini_user_id="u",
        bhashini_api_key=SecretStr("b"),
        sarvam_api_key=SecretStr("s"),
        sarvam_enabled=True,
    )
    out = build_speech(
        s,
        meter(),
        http=httpx.AsyncClient(),
        google_tokens=FakeTokens(),
        sarvam_on=yes,
        laptop=(FakeHearing("laptop"), FakeVoice("laptop")),
    )
    assert list(out.hearing) == ["laptop", "google", "azure", "bhashini", "sarvam"]
    assert list(out.voices) == list(out.hearing) and out.missing == {}
    assert all(h.name == n for n, h in out.hearing.items())


def test_google_needs_working_credentials() -> None:
    s = Settings(_env_file=None, voice_cloud=True)
    out = build_speech(
        s, meter(), http=httpx.AsyncClient(), google_tokens=FakeTokens(missing=True), sarvam_on=yes
    )
    assert "google" not in out.hearing and "google" in out.missing


async def test_sarvam_with_its_key_still_asks_the_owner_every_time() -> None:
    s = Settings(_env_file=None, sarvam_api_key=SecretStr("s"), sarvam_enabled=True)
    out = build_speech(s, meter(), http=httpx.AsyncClient(), google_tokens=None, sarvam_on=no)
    with pytest.raises(PaidOptionOff):
        await out.hearing["sarvam"].transcribe(tone(1.0), ["hi-IN"])
    off = Settings(_env_file=None, sarvam_api_key=SecretStr("s"), sarvam_enabled=False)
    out = build_speech(off, meter(), http=httpx.AsyncClient(), google_tokens=None, sarvam_on=yes)
    assert "sarvam" not in out.hearing
