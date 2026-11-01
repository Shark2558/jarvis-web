# tests/test_voice_api.py — slice 9 §3: /v1/voice (owner-only, CSRF on cookie writes, exact shapes,
# error codes, limits), the spending gate, ₹ in /v1/usage, the voice channel on /v1/chat, and that
# text / transcripts never reach the logs.
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from voice_fakes import FakeSTT, FakeTokens, FakeTTS, wav

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.api.voice import MAX_AUDIO_BYTES
from jarvis.billing import BudgetPatch
from jarvis.config import AuthMode, Settings
from jarvis.core.prompts import VOICE_RULE_HEADING, build_system_prompt
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.voice.catalogue import DEFAULT_VOICE
from jarvis.voice.ports import VoiceBusy, VoiceRejected, VoiceUnavailable
from jarvis.voice.service import VoiceEngines

UID = "owner"  # dev / token mode: no owners configured
WAV = {"Content-Type": "audio/wav"}
VIEW_KEYS = {"cloud", "settings", "voices", "wit_levels", "allowance", "month", "language"}
PATH = f"jarvis_usage/{UID}_"


class Rig:
    def __init__(self) -> None:
        self.tts = FakeTTS()
        self.stt = FakeSTT()
        self.tokens = FakeTokens()
        self.provider = MockProvider()

    def engines(self) -> VoiceEngines:
        return VoiceEngines(tts=self.tts, stt=self.stt, tokens=self.tokens)


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def _client(s: Settings, rig: Rig) -> AsyncIterator[AsyncClient]:
    app = create_app(
        s, provider=rig.provider, store=InMemorySessionStore(), voice_engines=rig.engines()
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
async def vc(settings: Settings, rig: Rig) -> AsyncIterator[AsyncClient]:
    async for c in _client(settings, rig):
        yield c


async def _limit(c: AsyncClient, inr: int) -> None:
    await c.app.state.billing.budgets.update(UID, BudgetPatch(monthly_limit_inr=inr))  # type: ignore[attr-defined]


async def _use_allowance(c: AsyncClient, key: str, amount: float, inr: float = 0.0) -> None:
    """Pretend this month already used `amount` of `key` (and spent `inr`)."""
    billing = c.app.state.billing  # type: ignore[attr-defined]
    month = billing.meter.month_of(billing.clock())
    from billing_fakes import put_raw

    await put_raw(
        billing.meter._d,
        f"jarvis_usage/{UID}_{month}",
        {"inr_total": inr, "units": {key: amount}},
    )


# ---- GET /v1/voice ---------------------------------------------------------------------------


async def test_view_shape_and_defaults(vc: AsyncClient) -> None:
    r = await vc.get("/v1/voice")
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == VIEW_KEYS
    assert j["cloud"] == {"tts": "ready", "stt": "ready", "reason": None}
    assert j["settings"] == {"voice": DEFAULT_VOICE, "rate": 1.0, "wit": "film"}
    assert [v["id"] for v in j["voices"]][0] == DEFAULT_VOICE and len(j["voices"]) == 6
    assert set(j["voices"][0]) == {"id", "label", "style", "type", "available"}
    assert all(v["available"] for v in j["voices"])
    assert [w["id"] for w in j["wit_levels"]] == ["measured", "film", "extra"]
    assert set(j["wit_levels"][0]) == {"id", "label", "description"}
    tts = j["allowance"]["tts"]
    assert tts["type"] == "chirp3-hd" and tts["used_chars"] == 0 and tts["free_chars"] == 1_000_000
    assert tts["by_type"] == {
        "chirp3-hd": {"used": 0, "free": 1_000_000},
        "studio": {"used": 0, "free": 1_000_000},
    }
    assert j["allowance"]["stt"] == {"used_seconds": 0, "free_seconds": 3_600}
    assert j["month"]["voice_inr"] == 0 and len(j["month"]["month"]) == 7
    assert j["language"] == "en-IN"
    assert "$" not in r.text


async def test_view_marks_voices_google_does_not_list(vc: AsyncClient, rig: Rig) -> None:
    rig.tts.known = frozenset({DEFAULT_VOICE})
    j = (await vc.get("/v1/voice")).json()
    avail = {v["id"]: v["available"] for v in j["voices"]}
    assert avail[DEFAULT_VOICE] is True and avail["en-GB-Studio-B"] is False


async def test_cloud_off_reports_off(settings: Settings, rig: Rig) -> None:
    async for c in _client(settings.model_copy(update={"voice_cloud": False}), rig):
        j = (await c.get("/v1/voice")).json()
        assert j["cloud"] == {"tts": "off", "stt": "off", "reason": None}
        assert not any(v["available"] for v in j["voices"])
        r = await c.post("/v1/voice/speak", json={"text": "Hello."})
        assert r.status_code == 503 and r.json()["reason"] == "not_configured"
        assert rig.tts.calls == []


async def test_no_credentials_reports_not_configured(vc: AsyncClient, rig: Rig) -> None:
    rig.tokens.missing = True
    j = (await vc.get("/v1/voice")).json()
    assert j["cloud"] == {"tts": "unavailable", "stt": "unavailable", "reason": "not_configured"}


async def test_api_disabled_is_remembered_and_skips_google(vc: AsyncClient, rig: Rig) -> None:
    rig.tts.voices_fail = VoiceUnavailable("api_disabled")
    j = (await vc.get("/v1/voice")).json()
    assert j["cloud"] == {"tts": "unavailable", "stt": "ready", "reason": "api_disabled"}
    r = await vc.post("/v1/voice/speak", json={"text": "Hello."})
    assert r.status_code == 503
    assert r.json() == {
        "error": "voice_unavailable",
        "detail": r.json()["detail"],
        "reason": "api_disabled",
    }
    assert "gcloud services enable" in r.json()["detail"]
    assert rig.tts.calls == []  # remembered: Google isn't asked again for 10 minutes


async def test_view_works_with_a_unit_counter_and_voice_spend(vc: AsyncClient) -> None:
    await _use_allowance(vc, "tts_chirp3-hd", 1234)
    j = (await vc.get("/v1/voice")).json()
    assert j["allowance"]["tts"]["used_chars"] == 1234


# ---- PUT /v1/voice/settings -------------------------------------------------------------------


async def test_put_settings_round_trip(vc: AsyncClient) -> None:
    r = await vc.put("/v1/voice/settings", json={"wit": "extra", "rate": 1.2})
    assert r.status_code == 200 and r.json() == {
        "voice": DEFAULT_VOICE,
        "rate": 1.2,
        "wit": "extra",
    }
    r = await vc.put("/v1/voice/settings", json={"voice": "en-GB-Studio-B", "user_id": "x"})
    assert r.json()["voice"] == "en-GB-Studio-B" and r.json()["wit"] == "extra"
    j = (await vc.get("/v1/voice")).json()
    assert j["settings"]["voice"] == "en-GB-Studio-B" and j["allowance"]["tts"]["type"] == "studio"


@pytest.mark.parametrize(
    "body", [{"voice": "en-US-Neural2-J"}, {"wit": "slapstick"}, {"rate": 2.0}, {"rate": 0.5}]
)
async def test_put_settings_rejects_bad_values(vc: AsyncClient, body: dict[str, Any]) -> None:
    r = await vc.put("/v1/voice/settings", json=body)
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"


# ---- POST /v1/voice/speak --------------------------------------------------------------------


async def test_speak_returns_mp3_with_headers(vc: AsyncClient, rig: Rig) -> None:
    r = await vc.post("/v1/voice/speak", json={"text": "**Good** evening, see https://x.io."})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content.startswith(b"ID3")
    spoken = "Good evening, see the link on screen."
    assert r.headers["x-jarvis-chars"] == str(len(spoken))
    assert r.headers["x-jarvis-cost-inr"] == "0.0000"
    assert r.headers["cache-control"] == "no-store"
    assert rig.tts.calls == [
        {"text": spoken, "voice": DEFAULT_VOICE, "language": "en-GB", "rate": 1.0}
    ]


async def test_speak_uses_saved_settings_and_overrides(vc: AsyncClient, rig: Rig) -> None:
    await vc.put("/v1/voice/settings", json={"voice": "en-GB-Chirp3-HD-Charon", "rate": 0.9})
    await vc.post("/v1/voice/speak", json={"text": "One."})
    await vc.post("/v1/voice/speak", json={"text": "Two.", "voice": "en-GB-Studio-B", "rate": 1.25})
    assert [(c["voice"], c["rate"]) for c in rig.tts.calls] == [
        ("en-GB-Chirp3-HD-Charon", 0.9),
        ("en-GB-Studio-B", 1.25),
    ]


async def test_preview_reads_the_fixed_sample_line(vc: AsyncClient, rig: Rig) -> None:
    r = await vc.post("/v1/voice/speak", json={"preview": True, "voice": "en-GB-Studio-B"})
    assert r.status_code == 200
    call = rig.tts.calls[0]
    assert call["voice"] == "en-GB-Studio-B"
    assert call["text"].startswith("Good evening, Sir. Systems are running smoothly")
    r = await vc.post("/v1/voice/speak", json={"preview": True, "text": "ignored"})
    assert "ignored" not in rig.tts.calls[1]["text"]


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"text": "```\ncode only\n```"}, "nothing_to_say"),
        ({"text": "   "}, "nothing_to_say"),
        ({}, "input_rejected"),
        ({"text": ""}, "input_rejected"),
        ({"text": "x" * 1_201}, "input_rejected"),
        ({"text": "Hi.", "voice": "en-US-Wavenet-A"}, "input_rejected"),
        ({"text": "Hi.", "rate": 1.3}, "input_rejected"),
    ],
)
async def test_speak_rejects(vc: AsyncClient, rig: Rig, body: dict[str, Any], code: str) -> None:
    r = await vc.post("/v1/voice/speak", json=body)
    assert r.status_code == 422 and r.json()["error"] == code, r.text
    assert rig.tts.calls == []


async def test_speak_caps_at_600_speakable_chars(vc: AsyncClient, rig: Rig) -> None:
    r = await vc.post("/v1/voice/speak", json={"text": "A short sentence here. " * 50})
    assert r.status_code == 200 and int(r.headers["x-jarvis-chars"]) <= 600
    assert len(rig.tts.calls[0]["text"]) <= 600


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (VoiceUnavailable("timeout"), 503, "voice_unavailable"),
        (VoiceUnavailable("upstream_error"), 503, "voice_unavailable"),
        (VoiceBusy(), 429, "voice_busy"),
        (VoiceRejected("Google rejected that voice or text."), 422, "input_rejected"),
    ],
)
async def test_speak_engine_errors(
    vc: AsyncClient, rig: Rig, exc: Exception, status: int, code: str
) -> None:
    rig.tts.fail = exc
    r = await vc.post("/v1/voice/speak", json={"text": "Hello."})
    assert r.status_code == status and r.json()["error"] == code
    if status == 429:
        assert r.headers["retry-after"] == "10"
    # transient failures are not remembered
    rig.tts.fail = None
    assert (await vc.post("/v1/voice/speak", json={"text": "Hello."})).status_code == 200


async def test_speak_is_limited_to_60_a_minute(vc: AsyncClient) -> None:
    for _ in range(60):
        assert (await vc.post("/v1/voice/speak", json={"text": "Hi."})).status_code == 200
    r = await vc.post("/v1/voice/speak", json={"text": "Hi."})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1


# ---- spending --------------------------------------------------------------------------------


async def test_free_speech_still_works_at_the_limit(vc: AsyncClient, rig: Rig) -> None:
    await _use_allowance(vc, "tts_chirp3-hd", 1_000_000 - 100, inr=600)
    await _limit(vc, 500)
    r = await vc.post("/v1/voice/speak", json={"text": "Within the allowance."})
    assert r.status_code == 200 and r.headers["x-jarvis-cost-inr"] == "0.0000"


async def test_priced_speech_is_refused_at_the_limit(vc: AsyncClient, rig: Rig) -> None:
    await _use_allowance(vc, "tts_chirp3-hd", 1_000_000, inr=600)
    await _limit(vc, 500)
    r = await vc.post("/v1/voice/speak", json={"text": "Over the allowance."})
    assert r.status_code == 402 and r.json()["error"] == "budget_reached"
    assert "₹500" in r.json()["detail"] and "$" not in r.text
    assert rig.tts.calls == []


async def test_priced_speech_is_metered_in_rupees_and_shows_in_usage(vc: AsyncClient) -> None:
    await _use_allowance(vc, "tts_studio", 1_000_000)
    text = "Priced sentence. " * 30
    r = await vc.post("/v1/voice/speak", json={"text": text, "voice": "en-GB-Studio-B"})
    chars = int(r.headers["x-jarvis-chars"])
    cost = float(r.headers["x-jarvis-cost-inr"])
    assert cost == pytest.approx(chars * 160 / 1_000_000 * 95.24, rel=1e-3)
    usage = (await vc.get("/v1/usage")).json()
    assert usage["used_inr"] == pytest.approx(cost, abs=0.01)
    entry = next(b for b in usage["by_brain"] if b["brain"] == "voice")
    assert entry["label"] == "Voice"
    j = (await vc.get("/v1/voice")).json()
    assert j["month"]["voice_inr"] == pytest.approx(cost, abs=0.01)
    assert j["allowance"]["tts"]["by_type"]["studio"]["used"] == 1_000_000 + chars


# ---- POST /v1/voice/transcribe ---------------------------------------------------------------


async def test_transcribe_returns_the_contract(vc: AsyncClient, rig: Rig) -> None:
    r = await vc.post("/v1/voice/transcribe", content=wav(1.2), headers=WAV)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "text": "what's on my calendar today",
        "confidence": 0.93,
        "seconds": 1.2,
        "cost_inr": 0.0,
        "language": "en-IN",
        "no_speech": False,
    }
    call = rig.stt.calls[0]
    assert call["rate"] == 16_000 and call["language"] == "en-IN"
    assert call["phrases"] == ("JARVIS", "Jarvis", "Sir")
    j = (await vc.get("/v1/voice")).json()
    assert j["allowance"]["stt"]["used_seconds"] == 2  # ceil(1.2 s) as billed


async def test_transcribe_reports_no_speech(vc: AsyncClient, rig: Rig) -> None:
    rig.stt.text, rig.stt.confidence = "", None
    j = (await vc.post("/v1/voice/transcribe", content=wav(0.5), headers=WAV)).json()
    assert j["no_speech"] is True and j["text"] == "" and j["confidence"] is None


@pytest.mark.parametrize(
    ("blob", "ctype"),
    [
        (wav(1), "audio/mpeg"),
        (wav(1), "application/json"),
        (wav(1, channels=2), "audio/wav"),
        (wav(1, rate=44_100), "audio/wav"),
        (wav(0.1), "audio/wav"),
        (b"ID3not a wav", "audio/wav"),
    ],
)
async def test_transcribe_rejects_bad_audio(
    vc: AsyncClient, rig: Rig, blob: bytes, ctype: str
) -> None:
    r = await vc.post("/v1/voice/transcribe", content=blob, headers={"Content-Type": ctype})
    assert r.status_code == 422 and r.json()["error"] == "bad_audio"
    assert rig.stt.calls == []


async def test_transcribe_refuses_oversize_from_content_length(vc: AsyncClient, rig: Rig) -> None:
    async def never() -> AsyncIterator[bytes]:
        raise AssertionError("the body must not be read")
        yield b""  # pragma: no cover

    headers = {**WAV, "Content-Length": str(MAX_AUDIO_BYTES + 1)}
    r = await vc.post("/v1/voice/transcribe", content=never(), headers=headers)
    assert r.status_code == 413 and r.json()["error"] == "too_large"


async def test_transcribe_refuses_an_oversize_chunked_upload(vc: AsyncClient, rig: Rig) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"\x00" * 800_000

    r = await vc.post("/v1/voice/transcribe", content=chunks(), headers=WAV)
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert rig.stt.calls == []


async def test_transcribe_spending_gate(vc: AsyncClient, rig: Rig) -> None:
    await _use_allowance(vc, "stt_seconds", 3_600 - 2, inr=600)
    await _limit(vc, 500)
    ok = await vc.post("/v1/voice/transcribe", content=wav(1.5), headers=WAV)  # 2 s: still free
    assert ok.status_code == 200
    r = await vc.post("/v1/voice/transcribe", content=wav(1.5), headers=WAV)
    assert r.status_code == 402 and r.json()["error"] == "budget_reached"
    assert len(rig.stt.calls) == 1


async def test_transcribe_engine_down(vc: AsyncClient, rig: Rig) -> None:
    rig.stt.fail = VoiceUnavailable("api_disabled")
    r = await vc.post("/v1/voice/transcribe", content=wav(1), headers=WAV)
    assert r.status_code == 503 and r.json()["reason"] == "api_disabled"
    j = (await vc.get("/v1/voice")).json()
    assert j["cloud"]["stt"] == "unavailable" and j["cloud"]["tts"] == "ready"


async def test_transcribe_is_limited_to_30_a_minute(vc: AsyncClient) -> None:
    clip = wav(0.4)
    for _ in range(30):
        assert (await vc.post("/v1/voice/transcribe", content=clip, headers=WAV)).status_code == 200
    r = await vc.post("/v1/voice/transcribe", content=clip, headers=WAV)
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


# ---- chat channel and wit ---------------------------------------------------------------------


async def test_chat_voice_channel_and_wit_from_settings(vc: AsyncClient, rig: Rig) -> None:
    await vc.put("/v1/voice/settings", json={"wit": "measured"})
    r = await vc.post("/v1/chat", json={"message": "hello", "channel": "voice"})
    assert r.status_code == 200, r.text
    system = rig.provider.calls[-1].system
    assert system.startswith(build_system_prompt(honorific="Sir", wit="measured"))
    assert VOICE_RULE_HEADING in system
    r = await vc.post("/v1/chat/stream", json={"message": "hello", "channel": "voice"})
    assert r.status_code == 200 and VOICE_RULE_HEADING in rig.provider.calls[-1].system
    await vc.post("/v1/chat", json={"message": "hello"})
    assert VOICE_RULE_HEADING not in rig.provider.calls[-1].system
    r = await vc.post("/v1/chat", json={"message": "hello", "channel": "telepathy"})
    assert r.status_code == 422


# ---- privacy and access ----------------------------------------------------------------------


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage() + " " + json.dumps(record.__dict__, default=str))


@pytest.fixture
def records() -> Iterator[_Records]:
    h = _Records()
    root = logging.getLogger()
    root.addHandler(h)
    yield h
    root.removeHandler(h)


async def test_text_and_transcripts_never_reach_the_logs(
    vc: AsyncClient, rig: Rig, records: _Records
) -> None:
    rig.stt.text = "MANGO-SECRET transcript"
    await vc.post("/v1/voice/speak", json={"text": "PINEAPPLE-SECRET phrase."})
    rig.tts.fail = VoiceUnavailable("upstream_error")
    await vc.post("/v1/voice/speak", json={"text": "PAPAYA-SECRET phrase."})
    await vc.post("/v1/voice/transcribe", content=wav(0.5), headers=WAV)
    logged = "\n".join(records.lines)
    assert records.lines  # the handler did see the voice logs
    assert "voice: spoke" in logged and "voice: transcribed" in logged
    for secret in ("PINEAPPLE", "PAPAYA", "MANGO"):
        assert secret not in logged


OWNER = "akash@example.com"
CSRF = {"X-Requested-With": "JARVIS"}


@pytest.fixture
async def gc(settings: Settings, rig: Rig) -> AsyncIterator[AsyncClient]:
    s = settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    )
    async for c in _client(s, rig):
        yield c


async def test_owner_only_and_csrf_on_cookie_writes(gc: AsyncClient, rig: Rig) -> None:
    assert (await gc.get("/v1/voice")).status_code == 401
    assert (await gc.post("/v1/voice/speak", json={"text": "Hi."})).status_code == 401

    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": OWNER}}

    gc.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await gc.get("/auth/callback?code=a&state=b")).status_code in (302, 307)
    assert (await gc.get("/v1/voice")).status_code == 200
    for path, kw in (
        ("/v1/voice/speak", {"json": {"text": "Hi."}}),
        ("/v1/voice/transcribe", {"content": wav(0.5), "headers": WAV}),
    ):
        r = await gc.post(path, **kw)  # type: ignore[arg-type]
        assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = await gc.put("/v1/voice/settings", json={"wit": "extra"})
    assert r.status_code == 403
    ok = await gc.post("/v1/voice/speak", json={"text": "Hi."}, headers=CSRF)
    assert ok.status_code == 200
    ok = await gc.post("/v1/voice/transcribe", content=wav(0.5), headers={**WAV, **CSRF})
    assert ok.status_code == 200
    # the signed-in owner's settings live under their id, not "owner"
    await gc.put("/v1/voice/settings", json={"wit": "extra"}, headers=CSRF)
    store = gc.app.state.voice.store  # type: ignore[attr-defined]
    assert (await store.get(user_id_for_email(OWNER))).wit == "extra"
    assert (await store.get("owner")).wit == "film"
