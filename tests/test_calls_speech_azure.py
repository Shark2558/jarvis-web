# tests/test_calls_speech_azure.py — R18 B: Azure Speech free tier F0 over REST: short-audio
# recognition and neural voices (raw 16 kHz PCM), its monthly allowance held before each request
# and given back when Azure surely did not count it, "used up" said plainly (F0 cannot bill), the
# key only in its header and never logged.
from __future__ import annotations

import logging

import httpx
import pytest
from calls_speech_fakes import UID, Vendor, billing, no_sleep, respond, tone
from pydantic import SecretStr

from jarvis.calls.speech.audio import pcm_from_wav
from jarvis.calls.speech.azure import AzureHearing, AzureVoice, stt_url, tts_url
from jarvis.calls.speech.errors import (
    AllowanceUsedUp,
    NotOffered,
    OptionUnavailable,
    SpeechRejected,
)
from jarvis.calls.speech.meter import FreeAllowance, SpeechMeter
from jarvis.calls.speech.rest import RetryPolicy

KEY = SecretStr("azure-test-key-0123456789")
FAST = RetryPolicy(attempts=2, base_s=0.01, max_s=0.01, deadline_s=5.0)
STT_FREE = FreeAllowance("azure_stt_seconds", 100.0, "hearing")
TTS_FREE = FreeAllowance("azure_tts_chars", 2_000.0, "voice")


def ok_stt(text: str = "नमस्ते", conf: float = 0.91) -> httpx.Response:
    nbest = [{"Confidence": conf, "Lexical": text, "ITN": text, "Display": text + "।"}]
    return httpx.Response(200, json={"RecognitionStatus": "Success", "NBest": nbest})


def hearing(v: Vendor, free: FreeAllowance = STT_FREE) -> tuple[AzureHearing, SpeechMeter]:
    m = SpeechMeter(billing(), UID)
    h = AzureHearing(
        v.client(), KEY, "centralindia", m, allowance=free, policy=FAST, sleep=no_sleep
    )
    return h, m


async def used(m: SpeechMeter, key: str) -> float:
    return (await m.billing.allowance([key])).used(key)


async def test_short_audio_recognition_request_and_answer() -> None:
    v = Vendor([lambda r: ok_stt()])
    h, m = hearing(v)
    heard = await h.transcribe(tone(2.4), ["hi-IN", "en-IN"])
    assert (heard.lang, heard.text, heard.confidence) == ("hi-IN", "नमस्ते।", 0.91)
    req = v.requests[0]
    assert str(req.url).startswith(stt_url("centralindia"))
    assert req.url.params["language"] == "hi-IN" and req.url.params["format"] == "detailed"
    assert req.headers["Ocp-Apim-Subscription-Key"] == KEY.get_secret_value()
    assert req.headers["Content-Type"] == "audio/wav; codecs=audio/pcm; samplerate=16000"
    assert pcm_from_wav(req.content) == tone(2.4)
    assert await used(m, "azure_stt_seconds") == 3.0
    assert (await m.billing.month(UID)).inr_total == 0


@pytest.mark.parametrize("status", ["NoMatch", "InitialSilenceTimeout", "BabbleTimeout"])
async def test_nothing_recognised_is_an_empty_heard(status: str) -> None:
    v = Vendor([respond(json={"RecognitionStatus": status})])
    h, _ = hearing(v)
    heard = await h.transcribe(tone(1.0), ["ta-IN"])
    assert (heard.text, heard.confidence, heard.lang) == ("", 0.0, "ta-IN")


async def test_an_azure_error_status_is_unavailable_and_keeps_the_hold() -> None:
    v = Vendor([respond(json={"RecognitionStatus": "Error"})])
    h, m = hearing(v)
    with pytest.raises(OptionUnavailable) as e:
        await h.transcribe(tone(1.0), ["ta-IN"])
    assert e.value.maybe_billed and await used(m, "azure_stt_seconds") == 1.0


async def test_a_clean_refusal_gives_the_held_seconds_back() -> None:
    v = Vendor([respond(401)])
    h, m = hearing(v)
    with pytest.raises(OptionUnavailable) as e:
        await h.transcribe(tone(4.0), ["ta-IN"])
    assert e.value.reason == "auth" and await used(m, "azure_stt_seconds") == 0.0


async def test_the_allowance_used_up_stops_before_any_request() -> None:
    v = Vendor([lambda r: ok_stt()])
    h, m = hearing(v, FreeAllowance("azure_stt_seconds", 5.0, "hearing"))
    await h.transcribe(tone(4.0), ["hi-IN"])
    with pytest.raises(AllowanceUsedUp) as e:
        await h.transcribe(tone(2.0), ["hi-IN"])
    assert len(v.requests) == 1 and "used up" in str(e.value)


async def test_azure_s_own_quota_answer_is_used_up_not_a_bad_key() -> None:
    v = Vendor(
        [respond(403, text="Out of call volume quota. Quota will be replenished in 3 days.")]
    )
    h, m = hearing(v)
    with pytest.raises(AllowanceUsedUp):
        await h.transcribe(tone(1.0), ["hi-IN"])
    assert await used(m, "azure_stt_seconds") == 0.0
    v = Vendor([respond(403, text="Access denied due to invalid subscription key.")])
    h, _ = hearing(v)
    with pytest.raises(OptionUnavailable) as e:
        await h.transcribe(tone(1.0), ["hi-IN"])
    assert e.value.reason == "auth"


async def test_audio_longer_than_azure_s_short_audio_limit_is_refused() -> None:
    v = Vendor([lambda r: ok_stt()])
    h, _ = hearing(v)
    with pytest.raises(SpeechRejected):
        await h.transcribe(tone(61.0), ["hi-IN"])
    assert v.requests == []


async def test_a_language_azure_does_not_list_is_not_sent() -> None:
    v = Vendor([lambda r: ok_stt()])
    h, _ = hearing(v)
    with pytest.raises(NotOffered):
        await h.transcribe(tone(1.0), ["kok-IN"])
    assert v.requests == []


async def test_neural_voice_ssml_escaped_raw_16khz_pcm(caplog: pytest.LogCaptureFixture) -> None:
    pcm = tone(0.3)
    v = Vendor([respond(content=pcm)])
    m = SpeechMeter(billing(), UID)
    voice = AzureVoice(
        v.client(), KEY, "centralindia", m, allowance=TTS_FREE, policy=FAST, sleep=no_sleep
    )
    with caplog.at_level(logging.DEBUG):
        out = await voice.speak("Pickup <10:30> & drop", "or-IN")
    assert out == pcm
    req = v.requests[0]
    assert str(req.url) == tts_url("centralindia")
    assert req.headers["X-Microsoft-OutputFormat"] == "raw-16khz-16bit-mono-pcm"
    assert req.headers["Content-Type"] == "application/ssml+xml"
    ssml = req.content.decode("utf-8")
    assert '<voice name="or-IN-SukantNeural">' in ssml and 'xml:lang="or-IN"' in ssml
    assert "Pickup &lt;10:30&gt; &amp; drop" in ssml
    assert await used(m, "azure_tts_chars") == len(ssml)  # the whole request: the safe side
    assert KEY.get_secret_value() not in caplog.text


async def test_voice_used_up_and_unknown_language() -> None:
    v = Vendor([respond(content=b"\x00\x00")])
    m = SpeechMeter(billing(), UID)
    tiny = FreeAllowance("azure_tts_chars", 50.0, "voice")
    voice = AzureVoice(v.client(), KEY, "centralindia", m, allowance=tiny, policy=FAST)
    with pytest.raises(AllowanceUsedUp):
        await voice.speak("a sentence that is long enough to pass fifty characters", "hi-IN")
    with pytest.raises(NotOffered):
        await voice.speak("hello", "ks-IN")
    assert v.requests == []
