# tests/test_r52_i0_protocol.py -- R5.2 I0 (docs/plans/r5-2-voice.md 3.1): the laptop speech kit's
# API. The paths the gate lets through, the audio format (R18's 16 kHz PCM16, reused), every
# request and reply model, the engine slots and their licences, and the kit's plain error body.
from __future__ import annotations

import ast
import base64
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.calls import models as cm
from jarvis.calls import protocol as calls_protocol
from jarvis.localspeech import protocol as p

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
SESSION = "vs_0123456789ab"
ONE_SECOND = b"\x01\x00" * p.SAMPLE_RATE


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_the_paths_sit_under_the_offline_rules_v1_base() -> None:
    # jarvis.offline.config.check_url gives "https://<machine>.<tailnet>.ts.net[:port]/v1": every
    # kit path is relative to that base, so the same URL rule (and PinnedTransport) applies.
    assert p.API_PREFIX == "/v1"
    assert p.HEALTH == "/health" and p.STT == "/stt" and p.TTS == "/tts"
    assert {m for m, _ in p.ROUTES} == {"GET", "POST"}
    assert ("GET", "/health") in p.ROUTES and ("GET", "/jobs/{job_id}") in p.ROUTES
    session = {path for _, path in p.ROUTES if path.startswith("/session/")}
    assert session == {"/session/clip", "/session/score", "/session/results", "/session/delete"}
    wake = {path for _, path in p.ROUTES if path.startswith("/wakeword/")}
    assert wake == {"/wakeword/train", "/wakeword/status", "/wakeword/model"}
    assert p.LOOPBACK_BASE == f"http://127.0.0.1:{p.GATE_PORT}/v1"
    assert len({p.GATE_PORT, p.SERVER_PORT, 11434, 11435}) == 4  # not the local brain's ports
    assert p.FUNNEL_PORT in (443, 8443, 10000)  # one of Tailscale Funnel's (offline.config)
    assert p.job_path("job_0123456789ab") == "/jobs/job_0123456789ab"
    with pytest.raises(ValueError):
        p.job_path("../health")


def test_the_key_header_is_a_bearer_and_a_short_key_is_refused() -> None:
    key = "k" * p.KEY_MIN_CHARS
    assert p.bearer(key) == {"Authorization": f"Bearer {key}"}
    with pytest.raises(ValueError):
        p.bearer("short")


def test_the_audio_format_is_r18s() -> None:
    assert p.SAMPLE_RATE == calls_protocol.SAMPLE_RATE == 16_000
    assert p.SAMPLE_BYTES == calls_protocol.SAMPLE_BYTES == 2
    assert p.pcm_seconds(len(ONE_SECOND)) == 1.0
    assert p.decode_pcm(p.encode_pcm(ONE_SECOND), max_s=p.STT_MAX_S) == ONE_SECOND


@pytest.mark.parametrize(
    "bad",
    [
        "not base64!",
        _b64(b"\x01"),  # an odd byte: not 16-bit samples
        _b64(b"\x00\x00" * 100),  # shorter than MIN_AUDIO_S
        _b64(b"\x00\x00" * (p.SAMPLE_RATE * (p.CLIP_MAX_S + 1))),  # longer than a clip may be
    ],
)
def test_bad_audio_is_refused_without_quoting_it(bad: str) -> None:
    with pytest.raises(ValidationError):
        p.ClipIn(session_id=SESSION, prompt_id="cmd_lights", audio=bad, kind=p.PromptKind.COMMAND)
    fields = {"session_id": SESSION, "prompt_id": "cmd_lights", "kind": "command", "audio": bad}
    raw = json.dumps(fields).encode()
    with pytest.raises(p.KitRefused) as refused:
        p.parse_request(p.ClipIn, raw)  # what the kit's server answers: plain words, no input
    assert refused.value.code == "bad_request" and bad not in str(refused.value)
    with pytest.raises(p.KitUnavailable) as broken:
        p.parse_reply(p.ClipStored, raw)  # a reply that is not the protocol's: never "stored"
    assert broken.value.reason == "protocol" and bad not in str(broken.value)


def test_a_good_body_parses() -> None:
    clip = p.ClipIn(
        session_id=SESSION,
        prompt_id="cmd_lights",
        audio=p.encode_pcm(ONE_SECOND),
        kind=p.PromptKind.COMMAND,
    )
    assert p.parse_request(p.ClipIn, clip.model_dump_json().encode()) == clip
    stored = p.ClipStored(session_id=SESSION, prompt_id="cmd_lights", seconds=1.0, clips=1)
    assert p.parse_reply(p.ClipStored, stored.model_dump_json()) == stored
    with pytest.raises(p.KitRefused):
        p.parse_request(p.ClipIn, b"x" * (p.BODY_MAX + 1))  # too large before parsing


def test_stt_request_and_reply() -> None:
    req = p.SttRequest.of_pcm(ONE_SECOND, lang=cm.ENGLISH, phrases=("Mark XXV",))
    assert req.pcm() == ONE_SECOND and req.slot is None
    assert p.SttRequest.model_validate_json(req.model_dump_json()) == req
    with pytest.raises(ValidationError):
        p.SttRequest.of_pcm(ONE_SECOND, lang="xx-YY")  # not one of R18's languages
    with pytest.raises(ValidationError):
        p.SttRequest.of_pcm(ONE_SECOND, lang=cm.ENGLISH, slot=p.EngineSlot.KOKORO)  # a voice
    with pytest.raises(ValidationError):
        p.SttRequest.of_pcm(ONE_SECOND, lang=cm.ENGLISH, phrases=("w",) * (p.PHRASES_MAX + 1))
    with pytest.raises(ValidationError):
        p.SttRequest.model_validate({**req.model_dump(), "extra": 1})  # requests are strict
    out = p.SttResult(
        lang=cm.ENGLISH,
        text="turn on the lights",
        confidence=0.91,
        seconds=1.0,
        slot=p.EngineSlot.WHISPER_SMALL,
        elapsed_ms=180,
    )
    # the fields R18's Heard needs, by the same names (V2's calls bridge maps them 1:1)
    heard = cm.Heard(lang=out.lang, text=out.text, confidence=out.confidence, seconds=out.seconds)
    assert heard.text == out.text
    newer = p.SttResult.model_validate({**out.model_dump(), "from_a_newer_kit": True})
    assert newer == out  # replies ignore what a newer kit adds
    with pytest.raises(ValidationError):
        p.SttResult.model_validate({**out.model_dump(), "alternatives": ["a", "b", "c"]})


def test_tts_request_and_reply() -> None:
    req = p.TtsRequest(lang=cm.ENGLISH, text="Good evening.", format=p.AudioFormat.MP3)
    assert req.voice is None and req.rate == 1.0 and req.slot is None
    for bad in (
        {"text": ""},
        {"text": "x" * (p.TTS_MAX_CHARS + 1)},
        {"rate": 3.0},
        {"voice": "Not A Voice!"},
        {"slot": p.EngineSlot.WHISPER_SMALL},  # a listening engine cannot speak
    ):
        with pytest.raises(ValidationError):
            p.TtsRequest.model_validate({**req.model_dump(), **bad})
    out = p.TtsResult(
        format=p.AudioFormat.PCM16,
        audio=p.encode_pcm(ONE_SECOND),
        sample_rate=p.SAMPLE_RATE,
        seconds=1.0,
        slot=p.EngineSlot.KOKORO,
        voice=p.DEFAULT_ENGLISH_VOICE,
        first_audio_ms=420,
        elapsed_ms=600,
    )
    assert out.audio_bytes() == ONE_SECOND
    with pytest.raises(ValidationError):
        p.TtsResult.model_validate({**out.model_dump(), "sample_rate": 8_000})  # PCM is 16 kHz


def test_every_engine_has_one_kind_and_the_defaults_cover_english_and_indian_languages() -> None:
    assert set(p.SLOT_KIND) == set(p.EngineSlot)
    assert p.SLOT_KIND[p.EngineSlot.WHISPER_SMALL] is p.Kind.STT
    assert p.SLOT_KIND[p.EngineSlot.KOKORO] is p.Kind.TTS
    assert p.default_slots(p.Kind.STT, cm.ENGLISH) == (p.EngineSlot.WHISPER_SMALL,)
    assert p.default_slots(p.Kind.TTS, cm.ENGLISH) == (p.EngineSlot.KOKORO, p.EngineSlot.PIPER)
    assert p.default_slots(p.Kind.STT, "ml-IN") == (p.EngineSlot.INDIC_CONFORMER,)
    assert p.default_slots(p.Kind.TTS, "ml-IN") == (p.EngineSlot.INDIC_PARLER, p.EngineSlot.PIPER)
    assert {"MIT", "Apache-2.0"} <= p.PERMISSIVE_LICENCES
    assert not {"CC-BY-NC-SA-4.0", "CC-BY-NC-4.0", "unknown"} & p.PERMISSIVE_LICENCES


def _engine(slot: p.EngineSlot, **over: object) -> p.EngineHealth:
    base: dict[str, object] = {
        "slot": slot,
        "kind": p.SLOT_KIND[slot],
        "languages": (cm.ENGLISH,),
        "model": "small-int8",
        "licence": "MIT",
        "ready": True,
        "loaded": False,
        "device": p.Device.CUDA,
    }
    return p.EngineHealth.model_validate(base | over)


def test_health_names_a_ready_engine_per_kind_and_language() -> None:
    health = p.KitHealth(
        protocol=p.PROTOCOL,
        kit_version="1.0.0",
        device=p.Device.CUDA,
        gpu_free_mb=3_000,
        ram_free_mb=8_000,
        engines=(
            _engine(p.EngineSlot.WHISPER_SMALL),
            _engine(p.EngineSlot.KOKORO, ready=False, reason="Downloading the voice."),
            _engine(p.EngineSlot.PIPER, licence="CC0-1.0"),
            _engine(p.EngineSlot.INDIC_CONFORMER, languages=("ml-IN", "hi-IN")),
        ),
    )
    assert health.compatible
    assert health.engine_for(p.Kind.STT, cm.ENGLISH) is p.EngineSlot.WHISPER_SMALL
    assert health.engine_for(p.Kind.TTS, cm.ENGLISH) is p.EngineSlot.PIPER  # Kokoro not ready
    assert health.engine_for(p.Kind.STT, "hi-IN") is p.EngineSlot.INDIC_CONFORMER
    assert health.engine_for(p.Kind.TTS, "hi-IN") is None
    assert health.languages(p.Kind.STT) == ("en-IN", "hi-IN", "ml-IN")
    assert not health.model_copy(update={"protocol": p.PROTOCOL + 1}).compatible
    with pytest.raises(ValidationError):
        _engine(p.EngineSlot.WHISPER_SMALL, licence="CC-BY-NC-4.0")  # unclear: left out
    with pytest.raises(ValidationError):
        _engine(p.EngineSlot.WHISPER_SMALL, kind=p.Kind.TTS)  # a slot has one kind
    with pytest.raises(ValidationError):
        p.KitHealth.model_validate({**health.model_dump(), "kit_version": "latest"})


def test_session_and_job_models() -> None:
    sid = p.new_session_id()
    assert p.SESSION_ID_RE.fullmatch(sid) and sid != p.new_session_id()
    clip = p.ClipIn(
        session_id=SESSION,
        prompt_id="wake_far_03",
        audio=p.encode_pcm(ONE_SECOND),
        kind=p.PromptKind.WAKE,
        held_out=True,
    )
    assert clip.pcm() == ONE_SECOND
    for bad in ({"session_id": "vs_nope"}, {"prompt_id": "Bad Id"}, {"prompt_id": "../x"}):
        with pytest.raises(ValidationError):
            p.ClipIn.model_validate({**clip.model_dump(), **bad})
    score = p.ScoreIn(session_id=SESSION, slots=(p.EngineSlot.WHISPER_SMALL,))
    with pytest.raises(ValidationError):
        p.ScoreIn(session_id=SESSION, slots=(p.EngineSlot.KOKORO,))  # only listening engines
    with pytest.raises(ValidationError):
        p.ScoreIn(session_id=SESSION, slots=())
    with pytest.raises(ValidationError):  # each word to recognise is 1 to 40 characters
        p.ScoreIn(session_id=SESSION, slots=(p.EngineSlot.WHISPER_SMALL,), phrases=("x" * 41,))
    assert score.phrases == ()
    job = p.JobView(job_id="job_0123456789ab", kind=p.JobKind.SCORE, state=p.JobState.RUNNING)
    assert not job.finished and job.model_copy(update={"state": p.JobState.DONE}).finished
    assert p.DeleteIn().session_id is None  # None: every recording on the laptop
    row = p.HeardRow(prompt_id="cmd_lights", slot=p.EngineSlot.WHISPER_SMALL, text="x")
    assert p.SessionHeard(session_id=SESSION, rows=(row,)).rows[0].elapsed_ms == 0


def test_wake_word_artifacts_carry_their_hash_and_licence() -> None:
    data = b'{"weights": [0.1, -0.2], "bias": 0.3}'
    model = p.WakeModel(
        artifact=p.WakeArtifact.VERIFIER,
        data=_b64(data),
        format="json",
        sha256=hashlib.sha256(data).hexdigest(),
        licence=p.OWNER_LICENCE,
        manifest="verifier trained on the owner's session clips",
    )
    assert model.data_bytes() == data
    with pytest.raises(ValidationError):
        p.WakeModel.model_validate({**model.model_dump(), "sha256": "0" * 64})  # wrong hash
    with pytest.raises(ValidationError):
        p.WakeModel.model_validate({**model.model_dump(), "licence": "CC-BY-NC-SA-4.0"})
    status = p.WakeStatus()
    assert status.verifier is None and status.owned is None and status.jobs == ()


def test_the_error_body_and_the_client_errors_never_quote_input() -> None:
    body = p.KitErrorBody(error="bad_audio", detail="Send 16 kHz mono PCM16.")
    assert body.error == "bad_audio"
    with pytest.raises(ValidationError):
        p.KitErrorBody(error="anything", detail="x")  # type: ignore[arg-type]
    down = p.KitUnavailable("offline")
    assert down.reason == "offline" and "laptop" in str(down).lower()
    for reason in p.UNAVAILABLE_REASONS:
        assert str(p.KitUnavailable(reason))  # plain words for every reason
    refused = p.KitRefused("unsupported_language", "That language has no engine on the laptop.")
    assert refused.code == "unsupported_language" and isinstance(refused, p.KitError)


def test_the_protocol_is_kit_safe() -> None:
    """The kit on the laptop imports this module: stdlib, Pydantic and R18's pure models only."""
    tree = ast.parse((SRC / "localspeech" / "protocol.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    jarvis = {m for m in found if m.startswith("jarvis")}
    assert jarvis <= {"jarvis.calls.models", "jarvis.calls.protocol"}
    tops = {m.split(".")[0] for m in found}
    assert tops <= {"__future__", "base64", "binascii", "re", "secrets", "enum", "typing", "jarvis",
                    "pydantic", "collections", "dataclasses", "hashlib"}  # fmt: skip
    init = (SRC / "localspeech" / "__init__.py").read_text(encoding="utf-8")
    assert "import" not in init  # importing the protocol stays light
