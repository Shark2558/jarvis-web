# tests/test_calls_speech_google.py — R18 B: Google hearing and voice for calls, through
# jarvis.voice's request and token source: utterance recognition with alternativeLanguageCodes for
# detection, LINEAR16 16 kHz voice in Chirp 3: HD, the shared free allowance metered then priced,
# retries only where Google surely did not bill, plain errors.
from __future__ import annotations

import base64

import httpx
import pytest
from calls_speech_fakes import UID, Vendor, billing, no_sleep, respond, tone
from voice_fakes import FakeTokens, google_error

from jarvis.calls.speech.audio import wav_from_pcm
from jarvis.calls.speech.errors import (
    NotOffered,
    OptionUnavailable,
    SpeechBusy,
    SpeechRejected,
)
from jarvis.calls.speech.google import GoogleHearing, GoogleVoice
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.speech.rest import RetryPolicy
from jarvis.voice.catalogue import Price, PriceList
from jarvis.voice.google_cloud import STT_URL, TTS_URL

PRICES = PriceList(
    chirp3_hd=Price("tts_chirp3-hd", 30 / 1e6, 1_000.0),
    studio=Price("tts_studio", 160 / 1e6, 1_000.0),
    stt=Price("stt_seconds", 0.024 / 60, 60.0),
)
FAST = RetryPolicy(attempts=3, base_s=0.01, max_s=0.01, deadline_s=5.0)


def stt_answer(
    text: str, lang: str = "hi-in", conf: float = 0.87, billed: str = "2s"
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "results": [
                {"alternatives": [{"transcript": text, "confidence": conf}], "languageCode": lang}
            ],
            "totalBilledTime": billed,
        },
    )


def hearing(
    v: Vendor, costs: list[tuple[str, float | None]] | None = None
) -> tuple[GoogleHearing, SpeechMeter]:
    def sink(part: str, inr: float | None) -> None:
        if costs is not None:
            costs.append((part, inr))

    meter = SpeechMeter(billing(), UID, on_cost=sink)
    h = GoogleHearing(v.client(), FakeTokens(), meter, PRICES, policy=FAST, sleep=no_sleep)
    return h, meter


# ---- hearing -----------------------------------------------------------------------------------


async def test_one_language_is_recognised_as_an_utterance() -> None:
    v = Vendor([lambda r: stt_answer("नमस्ते", "hi-in")])
    h, _ = hearing(v)
    heard = await h.transcribe(tone(2.0), ["hi-IN"])
    assert (heard.lang, heard.text, heard.confidence, heard.seconds) == ("hi-IN", "नमस्ते", 0.87, 2.0)
    req = v.requests[0]
    assert str(req.url) == STT_URL and req.headers["Authorization"] == "Bearer test-token"
    config = v.body()["config"]
    assert config == {
        "encoding": "LINEAR16",
        "sampleRateHertz": 16_000,
        "audioChannelCount": 1,
        "languageCode": "hi-IN",
        "model": "latest_short",
        "enableAutomaticPunctuation": True,
    }
    assert base64.b64decode(v.body()["audio"]["content"]) == tone(2.0)


async def test_other_languages_go_as_alternatives_and_the_detected_one_comes_back() -> None:
    v = Vendor([lambda r: stt_answer("ಹೌದು", "kn-in")])
    h, _ = hearing(v)
    heard = await h.transcribe(tone(1.0), ["en-IN", "kn-IN", "or-IN", "ta-IN", "ml-IN", "hi-IN"])
    assert heard.lang == "kn-IN"
    config = v.body()["config"]
    assert config["languageCode"] == "en-IN"
    # Odia is not Google's; at most 3 alternatives; the model is Google's default for them
    assert config["alternativeLanguageCodes"] == ["kn-IN", "ta-IN", "ml-IN"]
    assert "model" not in config


async def test_alternatives_refused_fall_back_to_the_first_language_once() -> None:
    v = Vendor([lambda r: google_error(400, grpc="INVALID_ARGUMENT"), lambda r: stt_answer("hi")])
    h, _ = hearing(v)
    heard = await h.transcribe(tone(1.0), ["en-IN", "hi-IN"])
    assert len(v.requests) == 2
    assert "alternativeLanguageCodes" not in v.body(1)["config"]
    assert heard.lang == "en-IN"  # Google's "hi-in" is not what was asked any more: the first


async def test_hearing_is_metered_on_google_s_billed_time_inside_the_free_allowance() -> None:
    costs: list[tuple[str, float | None]] = []
    v = Vendor([lambda r: stt_answer("ok", billed="3s")])
    h, meter = hearing(v, costs)
    await h.transcribe(tone(2.2), ["en-IN"])
    assert costs == [("hearing", 0.0)]
    used = (await meter.billing.allowance(["stt_seconds"])).used("stt_seconds")
    assert used == 3.0


async def test_no_speech_is_an_empty_heard() -> None:
    v = Vendor([respond(json={"totalBilledTime": "1s"})])
    h, _ = hearing(v)
    heard = await h.transcribe(tone(1.0), ["ta-IN"])
    assert (heard.text, heard.confidence, heard.lang) == ("", 0.0, "ta-IN")


async def test_a_language_google_does_not_hear_is_not_sent() -> None:
    v = Vendor([lambda r: stt_answer("x")])
    h, _ = hearing(v)
    with pytest.raises(NotOffered):
        await h.transcribe(tone(1.0), ["or-IN"])
    assert v.requests == []


async def test_a_throttle_is_retried_and_a_disabled_api_is_not() -> None:
    v = Vendor([lambda r: google_error(429), lambda r: stt_answer("ok")])
    h, _ = hearing(v)
    assert (await h.transcribe(tone(1.0), ["en-IN"])).text == "ok"
    assert len(v.requests) == 2

    v = Vendor([lambda r: google_error(403, "SERVICE_DISABLED")])
    h, _ = hearing(v)
    with pytest.raises(OptionUnavailable) as e:
        await h.transcribe(tone(1.0), ["en-IN"])
    assert e.value.reason == "off" and len(v.requests) == 1

    v = Vendor([lambda r: google_error(429)])
    h, _ = hearing(v)
    with pytest.raises(SpeechBusy):
        await h.transcribe(tone(1.0), ["en-IN"])
    assert len(v.requests) == 3


async def test_a_timeout_after_sending_is_metered_on_the_estimate_and_not_retried() -> None:
    def slow(_r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    costs: list[tuple[str, float | None]] = []
    v = Vendor([slow])
    h, meter = hearing(v, costs)
    with pytest.raises(OptionUnavailable) as e:
        await h.transcribe(tone(2.5), ["en-IN"])
    assert e.value.reason == "timeout" and len(v.requests) == 1
    assert (await meter.billing.allowance(["stt_seconds"])).used("stt_seconds") == 3.0
    assert costs == [("hearing", 0.0)]


# ---- voice -------------------------------------------------------------------------------------


async def test_voice_asks_for_16khz_linear16_in_chirp3_hd_and_returns_pcm() -> None:
    pcm = tone(0.5)
    v = Vendor([respond(json={"audioContent": base64.b64encode(wav_from_pcm(pcm)).decode()})])
    costs: list[tuple[str, float | None]] = []
    meter = SpeechMeter(billing(), UID, on_cost=lambda p, i: costs.append((p, i)))
    voice = GoogleVoice(v.client(), FakeTokens(), meter, PRICES, policy=FAST, sleep=no_sleep)
    out = await voice.speak("  नमस्ते,   मैं JARVIS हूँ। ", "hi-IN")
    assert out == pcm
    assert str(v.requests[0].url) == TTS_URL
    assert v.body() == {
        "input": {"text": "नमस्ते, मैं JARVIS हूँ।"},
        "voice": {"languageCode": "hi-IN", "name": "hi-IN-Chirp3-HD-Algieba"},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16_000},
    }
    used = (await meter.billing.allowance(["tts_chirp3-hd"])).used("tts_chirp3-hd")
    assert used == len("नमस्ते, मैं JARVIS हूँ।") and costs == [("voice", 0.0)]


async def test_voice_refuses_what_it_cannot_say_before_any_request() -> None:
    v = Vendor([respond(json={})])
    meter = SpeechMeter(billing(), UID)
    voice = GoogleVoice(v.client(), FakeTokens(), meter, PRICES, policy=FAST, sleep=no_sleep)
    with pytest.raises(NotOffered):
        await voice.speak("hello", "as-IN")  # Google has no Assamese voice
    with pytest.raises(SpeechRejected):
        await voice.speak("   ", "hi-IN")
    with pytest.raises(SpeechRejected):
        await voice.speak("x" * 1_001, "hi-IN")
    assert v.requests == []


async def test_an_unreadable_voice_answer_is_a_billed_failure() -> None:
    v = Vendor([respond(json={"audioContent": "!!not base64!!"})])
    meter = SpeechMeter(billing(), UID)
    voice = GoogleVoice(v.client(), FakeTokens(), meter, PRICES, policy=FAST, sleep=no_sleep)
    with pytest.raises(OptionUnavailable) as e:
        await voice.speak("hello", "en-IN")
    assert e.value.reason == "bad_answer" and e.value.maybe_billed
    assert (await meter.billing.allowance(["tts_chirp3-hd"])).used("tts_chirp3-hd") == 5
