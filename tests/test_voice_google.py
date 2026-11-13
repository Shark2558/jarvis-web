# tests/test_voice_google.py — slice 9 D2/D3/D10: Google Cloud TTS v1 + STT v1 over httpx with an
# ADC bearer token: request shapes, 10 s timeouts, voice list cached 24 h, and error mapping
# (403 → api_disabled, 429 → busy, 400 → rejected, 5xx → upstream_error, timeouts → timeout).
from __future__ import annotations

import asyncio
import base64
import threading
from typing import Any

import httpx
import pytest
from google.auth import exceptions as gexc
from voice_fakes import FakeTokens, GoogleScript, google_error, pcm

from jarvis.voice.adc import NOT_CONFIGURED_TTL_S, SCOPE, AdcTokens
from jarvis.voice.google_cloud import (
    DEADLINE_S,
    HTTP_TIMEOUT,
    SHORT_CLIP_S,
    STT_URL,
    TTS_URL,
    VOICES_FAIL_TTL_S,
    VOICES_TTL_S,
    VOICES_URL,
    GoogleSTT,
    GoogleTTS,
)
from jarvis.voice.ports import VoiceBusy, VoiceRejected, VoiceUnavailable


class Tick:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# ---- TTS -------------------------------------------------------------------------------------


async def test_synthesize_sends_the_documented_request() -> None:
    g = GoogleScript()
    tts = GoogleTTS(g.client(), FakeTokens())
    audio = await tts.synthesize(
        "Good evening.", voice="en-GB-Studio-B", language="en-GB", rate=1.1
    )
    assert audio == b"ID3audio"
    req = g.requests[0]
    assert str(req.url) == TTS_URL and req.method == "POST"
    assert req.headers["Authorization"] == "Bearer test-token"
    assert g.body() == {
        "input": {"text": "Good evening."},
        "voice": {"languageCode": "en-GB", "name": "en-GB-Studio-B"},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.1},
    }
    assert HTTP_TIMEOUT == httpx.Timeout(10.0, connect=3.0)


async def test_voice_list_is_cached_for_a_day() -> None:
    g, tick = GoogleScript(), Tick()
    tts = GoogleTTS(g.client(), FakeTokens(), clock=tick)
    names = await tts.voices("en-GB")
    assert names == frozenset({"en-GB-Chirp3-HD-Algieba", "en-GB-Studio-B"})
    assert str(g.requests[0].url) == VOICES_URL + "?languageCode=en-GB"
    tick.t += VOICES_TTL_S - 1
    await tts.voices("en-GB")
    assert len(g.requests) == 1
    tick.t += 2
    await tts.voices("en-GB")
    assert len(g.requests) == 2


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        (lambda r: httpx.Response(503), VoiceUnavailable),
        (lambda r: google_error(429, "RATE_LIMIT_EXCEEDED", "RESOURCE_EXHAUSTED"), VoiceBusy),
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), VoiceUnavailable),
    ],
)
async def test_a_failed_voice_list_is_remembered_for_a_minute(answer: Any, kind: type) -> None:
    """Review item 5: every GET /v1/voice used to ask Google again while it was failing."""
    g, tick = GoogleScript(), Tick()
    g.routes["/v1/voices"] = answer
    tts = GoogleTTS(g.client(), FakeTokens(), clock=tick)
    with pytest.raises(kind):
        await tts.voices("en-GB")
    tick.t += VOICES_FAIL_TTL_S - 1
    with pytest.raises(kind):
        await tts.voices("en-GB")
    assert len(g.requests) == 1  # remembered: Google not asked again
    g.routes["/v1/voices"] = GoogleScript().routes["/v1/voices"]
    tick.t += 2
    assert await tts.voices("en-GB")
    assert len(g.requests) == 2 and VOICES_FAIL_TTL_S == 60.0


@pytest.mark.parametrize(
    ("resp", "kind", "reason"),
    [
        (
            google_error(403, "SERVICE_DISABLED", "PERMISSION_DENIED"),
            VoiceUnavailable,
            "api_disabled",
        ),
        (
            google_error(403, "IAM_PERMISSION_DENIED", "PERMISSION_DENIED"),
            VoiceUnavailable,
            "api_disabled",
        ),
        (google_error(429, "RATE_LIMIT_EXCEEDED", "RESOURCE_EXHAUSTED"), VoiceBusy, None),
        (google_error(400, "", "INVALID_ARGUMENT"), VoiceRejected, None),
        (google_error(500, "", "INTERNAL"), VoiceUnavailable, "upstream_error"),
        (httpx.Response(502, text="<html>bad gateway</html>"), VoiceUnavailable, "upstream_error"),
        (httpx.Response(200, json={"nope": 1}), VoiceUnavailable, "upstream_error"),
        (
            httpx.Response(200, json={"audioContent": "!!not base64!!"}),
            VoiceUnavailable,
            "upstream_error",
        ),
        (httpx.Response(200, text="not json"), VoiceUnavailable, "upstream_error"),
    ],
)
async def test_error_mapping(
    resp: httpx.Response, kind: type[Exception], reason: str | None
) -> None:
    g = GoogleScript()
    g.routes["/v1/text:synthesize"] = lambda r: resp
    with pytest.raises(kind) as e:
        await GoogleTTS(g.client(), FakeTokens()).synthesize(
            "hi", voice="en-GB-Studio-B", language="en-GB", rate=1.0
        )
    if reason:
        assert e.value.reason == reason  # type: ignore[attr-defined]
    assert "vendor text" not in str(e.value)


async def test_401_drops_the_cached_token() -> None:
    g, tokens = GoogleScript(), FakeTokens()
    g.routes["/v1/text:synthesize"] = lambda r: httpx.Response(401)
    with pytest.raises(VoiceUnavailable) as e:
        await GoogleTTS(g.client(), tokens).synthesize("hi", voice="v", language="en-GB", rate=1)
    assert e.value.reason == "upstream_error" and tokens.invalidated == 1


@pytest.mark.parametrize(
    ("exc", "reason", "maybe_billed"),
    [
        (httpx.ReadTimeout("slow"), "timeout", True),  # sent; no answer in time
        (httpx.WriteTimeout("slow"), "timeout", True),  # partly sent
        (httpx.ConnectTimeout("slow"), "timeout", False),  # never connected
        (httpx.PoolTimeout("busy"), "timeout", False),  # never left the pool
        (httpx.ConnectError("down"), "upstream_error", False),
        (httpx.ReadError("reset"), "upstream_error", True),  # cut off mid-answer
        (httpx.RemoteProtocolError("closed"), "upstream_error", True),
    ],
)
async def test_timeouts_and_network_errors(exc: Exception, reason: str, maybe_billed: bool) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        raise exc

    g = GoogleScript()
    g.routes["/v1/text:synthesize"] = handler
    with pytest.raises(VoiceUnavailable) as e:
        await GoogleTTS(g.client(), FakeTokens()).synthesize(
            "hi", voice="v", language="en-GB", rate=1
        )
    assert (e.value.reason, e.value.maybe_billed) == (reason, maybe_billed)


@pytest.mark.parametrize(
    ("resp", "maybe_billed"),
    [
        (google_error(500, "", "INTERNAL"), False),  # a clean error answer: not billed
        (google_error(403, "SERVICE_DISABLED"), False),
        (httpx.Response(200, json={"nope": 1}), True),  # Google answered 200: it may bill
        (httpx.Response(200, text="not json"), True),
        (httpx.Response(200, json={"audioContent": "!!not base64!!"}), True),
    ],
)
async def test_only_answered_or_cut_off_calls_may_be_billed(
    resp: httpx.Response, maybe_billed: bool
) -> None:
    g = GoogleScript()
    g.routes["/v1/text:synthesize"] = lambda r: resp
    with pytest.raises(VoiceUnavailable) as e:
        await GoogleTTS(g.client(), FakeTokens()).synthesize(
            "hi", voice="v", language="en-GB", rate=1
        )
    assert e.value.maybe_billed is maybe_billed


async def test_one_total_deadline_covers_credentials_and_the_request() -> None:
    """Review item 7: the 10 s httpx timeout was per phase, and the credential lookup sat
    outside it. Now one deadline (≤ ~12 s) covers both."""
    assert DEADLINE_S <= 12.0
    assert HTTP_TIMEOUT.connect == 3.0 and HTTP_TIMEOUT.read == 10.0
    g = GoogleScript()
    slow_tokens = FakeTokens(delay=5.0)
    with pytest.raises(VoiceUnavailable) as e:
        await asyncio.wait_for(
            GoogleTTS(g.client(), slow_tokens, deadline_s=0.05).synthesize(
                "hi", voice="v", language="en-GB", rate=1
            ),
            2.0,
        )
    assert (e.value.reason, e.value.maybe_billed) == ("timeout", False) and g.requests == []

    async def slow_answer(r: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5.0)
        return httpx.Response(200, json={"audioContent": ""})

    g.routes["/v1/text:synthesize"] = slow_answer  # type: ignore[assignment]
    with pytest.raises(VoiceUnavailable) as e:
        await asyncio.wait_for(
            GoogleTTS(g.client(), FakeTokens(), deadline_s=0.05).synthesize(
                "hi", voice="v", language="en-GB", rate=1
            ),
            2.0,
        )
    assert (e.value.reason, e.value.maybe_billed) == ("timeout", True)


async def test_the_runtime_client_uses_the_connect_and_read_timeouts() -> None:
    from jarvis.voice.service import google_engines

    engines = google_engines()
    try:
        assert engines.http is not None and engines.http.timeout == HTTP_TIMEOUT
    finally:
        assert engines.http is not None
        await engines.http.aclose()
        assert engines.tokens is not None
        engines.tokens.close()  # type: ignore[attr-defined]


async def test_missing_credentials_never_reach_the_network() -> None:
    g = GoogleScript()
    with pytest.raises(VoiceUnavailable) as e:
        await GoogleTTS(g.client(), FakeTokens(missing=True)).synthesize(
            "hi", voice="v", language="en-GB", rate=1
        )
    assert e.value.reason == "not_configured" and g.requests == []


# ---- STT -------------------------------------------------------------------------------------


async def test_recognize_sends_the_documented_request() -> None:
    g = GoogleScript()
    stt = GoogleSTT(g.client(), FakeTokens())
    audio = pcm(0.5)
    t = await stt.recognize(audio, sample_rate=16_000, language="en-IN", phrases=("JARVIS", "Sir"))
    assert (t.text, t.confidence, t.billed_seconds, t.language) == (
        "hello jarvis",
        0.9,
        2.0,
        "en-in",
    )
    assert str(g.requests[0].url) == STT_URL
    body = g.body()
    assert base64.b64decode(body["audio"]["content"]) == audio
    assert body["config"] == {
        "encoding": "LINEAR16",
        "sampleRateHertz": 16_000,
        "audioChannelCount": 1,
        "languageCode": "en-IN",
        "model": "latest_short",
        "enableAutomaticPunctuation": True,
        "maxAlternatives": 3,  # R11.1 D9 (it was 1)
        "speechContexts": [{"phrases": ["JARVIS", "Sir"]}],
    }


@pytest.mark.parametrize(
    ("seconds", "model"), [(0.5, "latest_short"), (15.0, "latest_short"), (15.5, "latest_long")]
)
async def test_recognize_picks_the_model_by_clip_length(seconds: float, model: str) -> None:
    """Review item 14: latest_short is meant for short utterances; up to 60 s → latest_long
    (both support en-IN with automatic punctuation)."""
    g = GoogleScript()
    audio = b"\x00\x00" * int(16_000 * seconds)
    await GoogleSTT(g.client(), FakeTokens()).recognize(
        audio, sample_rate=16_000, language="en-IN", phrases=()
    )
    assert g.body()["config"]["model"] == model and SHORT_CLIP_S == 15.0


async def test_recognize_joins_results_and_reads_no_speech() -> None:
    g = GoogleScript()
    g.routes["/v1/speech:recognize"] = lambda r: httpx.Response(
        200,
        json={
            "results": [
                {"alternatives": [{"transcript": "remind me", "confidence": 0.8}]},
                {"alternatives": [{"transcript": " at six", "confidence": 0.6}]},
            ],
            "totalBilledTime": "3.500s",
        },
    )
    stt = GoogleSTT(g.client(), FakeTokens())
    t = await stt.recognize(pcm(0.5), sample_rate=16_000, language="en-IN", phrases=())
    assert t.text == "remind me at six" and t.confidence == 0.8 and t.billed_seconds == 3.5
    g.routes["/v1/speech:recognize"] = lambda r: httpx.Response(200, json={})
    t = await stt.recognize(pcm(0.5), sample_rate=16_000, language="en-IN", phrases=())
    assert (t.text, t.confidence, t.billed_seconds) == ("", None, None)


async def test_recognize_maps_errors_like_tts() -> None:
    g = GoogleScript()
    g.routes["/v1/speech:recognize"] = lambda r: google_error(403, "SERVICE_DISABLED")
    with pytest.raises(VoiceUnavailable) as e:
        await GoogleSTT(g.client(), FakeTokens()).recognize(
            pcm(0.5), sample_rate=16_000, language="en-IN", phrases=()
        )
    assert e.value.reason == "api_disabled"


# ---- ADC -------------------------------------------------------------------------------------


class Creds:
    def __init__(self, *, quota: str | None = None, fail: Exception | None = None) -> None:
        self.token: str | None = None
        self.valid = False
        self.quota_project_id = quota
        self.fail = fail
        self.refreshes = 0
        self.threads: list[str] = []
        self.requests: list[Any] = []

    def refresh(self, request: Any) -> None:
        self.threads.append(threading.current_thread().name)
        self.requests.append(request)
        self.refreshes += 1
        if self.fail is not None:
            raise self.fail
        self.token, self.valid = f"tok{self.refreshes}", True


async def test_adc_refreshes_off_the_event_loop_and_reuses_a_valid_token() -> None:
    creds = Creds(quota="my-project")
    scopes: list[Any] = []

    def discover(s: Any) -> Any:
        scopes.append(s)
        return creds

    tokens = AdcTokens(discover=discover)
    h = await tokens.headers()
    assert h == {"Authorization": "Bearer tok1", "x-goog-user-project": "my-project"}
    assert scopes == [[SCOPE]]
    assert creds.threads and creds.threads[0] != threading.current_thread().name
    await tokens.headers()
    assert creds.refreshes == 1  # still valid: no refresh
    tokens.invalidate()
    assert (await tokens.headers())["Authorization"] == "Bearer tok2"


async def test_adc_without_credentials_is_not_configured_and_cached() -> None:
    tick, calls = Tick(), []

    def discover(s: Any) -> Any:
        calls.append(1)
        raise gexc.DefaultCredentialsError("no ADC")

    tokens = AdcTokens(discover=discover, clock=tick)
    for _ in range(3):
        with pytest.raises(VoiceUnavailable) as e:
            await tokens.headers()
        assert e.value.reason == "not_configured"
    assert len(calls) == 1 and tokens.not_configured
    tick.t += NOT_CONFIGURED_TTL_S + 1
    assert not tokens.not_configured
    with pytest.raises(VoiceUnavailable):
        await tokens.headers()
    assert len(calls) == 2


async def test_adc_refresh_failures_are_upstream_errors_and_timeouts_time_out() -> None:
    tokens = AdcTokens(discover=lambda s: Creds(fail=gexc.RefreshError("metadata down")))
    with pytest.raises(VoiceUnavailable) as e:
        await tokens.headers()
    assert e.value.reason == "upstream_error" and not tokens.not_configured

    gate = threading.Event()

    class SlowCreds(Creds):
        def refresh(self, request: Any) -> None:
            gate.wait(2)
            super().refresh(request)

    tokens = AdcTokens(discover=lambda s: SlowCreds(), timeout_s=0.05)
    with pytest.raises(VoiceUnavailable) as e:
        await tokens.headers()
    assert e.value.reason == "timeout" and not tokens.not_configured  # transient
    gate.set()


async def test_adc_slow_discovery_means_no_credentials_here() -> None:
    """Off Google Cloud, google-auth probes the metadata server for ~10 s before giving up; on
    Cloud Run it answers at once. A slow lookup is therefore "not configured", remembered."""
    gate, calls = threading.Event(), []

    def slow(s: Any) -> Any:
        calls.append(1)
        gate.wait(2)
        return Creds()

    tokens = AdcTokens(discover=slow, discovery_timeout_s=0.05)
    for _ in range(2):
        with pytest.raises(VoiceUnavailable) as e:
            await tokens.headers()
        assert e.value.reason == "not_configured"
    assert tokens.not_configured and len(calls) == 1
    gate.set()


async def test_adc_concurrent_callers_share_one_refresh() -> None:
    creds = Creds()
    tokens = AdcTokens(discover=lambda s: creds)
    hs = await asyncio.gather(*(tokens.headers() for _ in range(5)))
    assert creds.refreshes == 1 and {h["Authorization"] for h in hs} == {"Bearer tok1"}


# ---- review item 6: one reused transport, one refresh in flight --------------------------------


class Session_:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class Transport:
    """Stands in for google.auth's Request (which owns a requests.Session)."""

    made = 0

    def __init__(self) -> None:
        Transport.made += 1
        self.session = Session_()


async def test_adc_reuses_one_transport_and_closes_it() -> None:
    Transport.made = 0
    creds = Creds()
    tokens = AdcTokens(discover=lambda s: creds, transport=Transport)
    await tokens.headers()
    tokens.invalidate()
    await tokens.headers()
    assert creds.refreshes == 2 and Transport.made == 1
    assert creds.requests[0] is creds.requests[1]
    tokens.close()
    assert creds.requests[0].session.closed == 1
    tokens.close()  # idempotent


async def test_adc_a_timed_out_refresh_is_awaited_by_the_next_caller_not_restarted() -> None:
    gate = threading.Event()

    class SlowCreds(Creds):
        def refresh(self, request: Any) -> None:
            gate.wait(2)
            super().refresh(request)

    creds = SlowCreds()
    tokens = AdcTokens(discover=lambda s: creds, timeout_s=0.05)
    for _ in range(3):
        with pytest.raises(VoiceUnavailable) as e:
            await tokens.headers()
        assert e.value.reason == "timeout"
    gate.set()
    for _ in range(100):  # the one refresh thread finishes on its own
        if creds.refreshes:
            break
        await asyncio.sleep(0.01)
    h = await tokens.headers()
    assert h["Authorization"] == "Bearer tok1"
    assert creds.refreshes == 1 and len(creds.threads) == 1  # never two refreshes at once
