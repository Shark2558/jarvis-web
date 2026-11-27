# tests/test_calls_speech_sarvam_bhashini.py — R18 B: Sarvam (paid: refused unless the owner
# turned it on; ₹30 an hour of hearing, ₹30 per 10,000 characters of voice, metered exactly) and
# Bhashini (optional: the ULCA pipeline's config call cached, its callback checked, its price
# unknown unless set and then never reported as ₹0).
from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable

import httpx
import pytest
from calls_speech_fakes import UID, Vendor, billing, no_sleep, respond, tone
from pydantic import SecretStr

from jarvis.calls.speech.audio import wav_from_pcm
from jarvis.calls.speech.bhashini import (
    CONFIG_URL,
    PIPELINE_ID,
    BhashiniHearing,
    BhashiniPipeline,
    BhashiniVoice,
)
from jarvis.calls.speech.errors import (
    NotOffered,
    OptionUnavailable,
    PaidOptionOff,
    SpeechRejected,
)
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.speech.rest import RetryPolicy
from jarvis.calls.speech.sarvam import (
    STT_URL,
    TTS_URL,
    SarvamHearing,
    SarvamVoice,
)

KEY = SecretStr("sarvam-test-key")
FAST = RetryPolicy(attempts=2, base_s=0.01, max_s=0.01, deadline_s=5.0)
HOUR, PER_10K = 30.0, 30.0


async def on() -> bool:
    return True


async def off() -> bool:
    return False


Costs = list[tuple[str, float | None]]


def meter(costs: Costs | None = None) -> SpeechMeter:
    def sink(part: str, inr: float | None) -> None:
        if costs is not None:
            costs.append((part, inr))

    return SpeechMeter(billing(), UID, on_cost=sink)


def sarvam_hearing(
    v: Vendor, m: SpeechMeter, enabled: Callable[[], Awaitable[bool]] = on
) -> SarvamHearing:
    return SarvamHearing(
        v.client(), KEY, m, enabled=enabled, inr_per_hour=HOUR, policy=FAST, sleep=no_sleep
    )


# ---- Sarvam ------------------------------------------------------------------------------------


async def test_sarvam_off_is_refused_before_any_request_or_rupee() -> None:
    v = Vendor([respond(json={"transcript": "x"})])
    m = meter()
    with pytest.raises(PaidOptionOff) as e:
        await sarvam_hearing(v, m, off).transcribe(tone(1.0), ["hi-IN"])
    assert "paid option and is off" in str(e.value)
    voice = SarvamVoice(v.client(), KEY, m, enabled=off, inr_per_10k_chars=PER_10K)
    with pytest.raises(PaidOptionOff):
        await voice.speak("नमस्ते", "hi-IN")
    assert v.requests == [] and (await m.billing.month(UID)).inr_total == 0


async def test_sarvam_hearing_one_language_and_its_rupees() -> None:
    answer = {"request_id": "r1", "transcript": "हाँ, कल दस बजे", "language_code": "hi-IN"}
    v = Vendor([respond(json=answer)])
    costs: Costs = []
    heard = await sarvam_hearing(v, meter(costs)).transcribe(tone(12.0), ["hi-IN"])
    assert (heard.lang, heard.text) == ("hi-IN", "हाँ, कल दस बजे")
    req = v.requests[0]
    assert str(req.url) == STT_URL and req.headers["api-subscription-key"] == "sarvam-test-key"
    body = req.content.decode("latin-1")
    assert 'name="language_code"' in body and "hi-IN" in body and 'name="file"' in body
    assert costs == [("hearing", pytest.approx(12 * HOUR / 3600, abs=1e-5))]


async def test_sarvam_detects_among_several_languages() -> None:
    answer = {"transcript": "ஆம்", "language_code": "ta-IN", "language_probability": 0.83}
    v = Vendor([respond(json=answer)])
    heard = await sarvam_hearing(v, meter()).transcribe(tone(1.0), ["en-IN", "ta-IN", "hi-IN"])
    assert (heard.lang, heard.confidence) == ("ta-IN", 0.83)
    assert "unknown" in v.requests[0].content.decode("latin-1")


async def test_sarvam_voice_16khz_wav_read_and_metered_per_character() -> None:
    pcm = tone(0.4)
    v = Vendor([respond(json={"audios": [base64.b64encode(wav_from_pcm(pcm)).decode()]})])
    costs: Costs = []
    voice = SarvamVoice(
        v.client(), KEY, meter(costs), enabled=on, inr_per_10k_chars=PER_10K, policy=FAST
    )
    out = await voice.speak("ನಮಸ್ಕಾರ", "kn-IN")
    assert out == pcm
    sent = json.loads(v.requests[0].content)
    assert str(v.requests[0].url) == TTS_URL
    assert sent == {
        "text": "ನಮಸ್ಕಾರ",
        "language_code": "kn-IN",
        "speaker": "shubh",
        "model": "bulbul:v3",
        "speech_sample_rate": 16_000,
    }
    assert costs == [("voice", pytest.approx(len("ನಮಸ್ಕಾರ") * PER_10K / 10_000, abs=1e-6))]


async def test_sarvam_does_not_offer_urdu_or_long_audio() -> None:
    v = Vendor([respond(json={})])
    with pytest.raises(NotOffered):
        await sarvam_hearing(v, meter()).transcribe(tone(1.0), ["ur-IN"])
    with pytest.raises(SpeechRejected):
        await sarvam_hearing(v, meter()).transcribe(tone(31.0), ["hi-IN"])
    assert v.requests == []


# ---- Bhashini ----------------------------------------------------------------------------------

CALLBACK = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"


def config_answer(task: str = "asr", callback: str = CALLBACK) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "pipelineResponseConfig": [
                {"taskType": task, "config": [{"serviceId": f"svc-{task}", "language": {}}]}
            ],
            "pipelineInferenceAPIEndPoint": {
                "callbackUrl": callback,
                "inferenceApiKey": {"name": "Authorization", "value": "inference-secret"},
            },
        },
    )


def pipeline(v: Vendor) -> BhashiniPipeline:
    return BhashiniPipeline(
        v.client(), "user-1", SecretStr("ulca-key"), policy=FAST, sleep=no_sleep
    )


async def test_bhashini_hearing_config_then_compute_and_price_unknown() -> None:
    asr = {"pipelineResponse": [{"taskType": "asr", "output": [{"source": "ନମସ୍କାର"}]}]}
    v = Vendor([lambda r: config_answer(), respond(json=asr)])
    costs: Costs = []
    h = BhashiniHearing(pipeline(v), meter(costs), inr_per_minute=None)
    heard = await h.transcribe(tone(1.5), ["or-IN"])
    assert (heard.lang, heard.text) == ("or-IN", "ନମସ୍କାର")
    cfg, compute = v.requests
    assert str(cfg.url) == CONFIG_URL
    assert cfg.headers["userID"] == "user-1" and cfg.headers["ulcaApiKey"] == "ulca-key"
    assert json.loads(cfg.content)["pipelineRequestConfig"] == {"pipelineId": PIPELINE_ID}
    assert str(compute.url) == CALLBACK and compute.headers["Authorization"] == "inference-secret"
    task = json.loads(compute.content)["pipelineTasks"][0]
    assert task["config"]["language"] == {"sourceLanguage": "or"}
    assert task["config"]["serviceId"] == "svc-asr" and task["config"]["samplingRate"] == 16_000
    assert costs == [("hearing", None)]  # unknown: never ₹0


async def test_bhashini_config_is_cached_per_task_and_language() -> None:
    asr = {"pipelineResponse": [{"output": [{"source": "x"}]}]}
    v = Vendor([lambda r: config_answer(), respond(json=asr)])
    h = BhashiniHearing(pipeline(v), meter(), inr_per_minute=0.0)
    await h.transcribe(tone(1.0), ["hi-IN"])
    v.answers = [respond(json=asr)]
    await h.transcribe(tone(1.0), ["hi-IN"])
    assert [str(r.url) for r in v.requests].count(CONFIG_URL) == 1


async def test_bhashini_refuses_a_callback_outside_its_own_domains() -> None:
    v = Vendor([lambda r: config_answer(callback="https://evil.example/collect")])
    h = BhashiniHearing(pipeline(v), meter(), inr_per_minute=None)
    with pytest.raises(OptionUnavailable) as e:
        await h.transcribe(tone(1.0), ["hi-IN"])
    assert e.value.reason == "bad_answer" and len(v.requests) == 1


async def test_bhashini_voice_reads_its_wav() -> None:
    pcm = tone(0.3)
    tts = {
        "pipelineResponse": [
            {"audio": [{"audioContent": base64.b64encode(wav_from_pcm(pcm)).decode()}]}
        ]
    }
    v = Vendor([lambda r: config_answer("tts"), respond(json=tts)])
    voice = BhashiniVoice(pipeline(v), meter())
    assert await voice.speak("नमस्ते", "mai-IN") == pcm
    task = json.loads(v.requests[1].content)["pipelineTasks"][0]
    assert task["taskType"] == "tts" and task["config"]["gender"] == "male"
    assert json.loads(v.requests[1].content)["inputData"] == {"input": [{"source": "नमस्ते"}]}
    with pytest.raises(NotOffered):
        await voice.speak("hello", "en-IN")
