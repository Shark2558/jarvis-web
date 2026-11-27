# tests/test_r52_i0_memory_kit.py -- R5.2 I0: `MemoryKit`, the deterministic in-memory laptop
# speech kit V2, V3 and V4 test against (and the CI mock evals use) until the real kit and its
# client exist. It keeps the `KitClient` contract: plain errors, clips per session, jobs, deletes.
from __future__ import annotations

import hashlib

import pytest

from jarvis.calls.models import ENGLISH
from jarvis.localspeech import protocol as p
from jarvis.localspeech.memory import MemoryKit

SESSION = "vs_0123456789ab"
ONE_SECOND = b"\x01\x00" * p.SAMPLE_RATE


def _clip(prompt_id: str, *, kind: p.PromptKind = p.PromptKind.COMMAND) -> p.ClipIn:
    return p.ClipIn(
        session_id=SESSION, prompt_id=prompt_id, audio=p.encode_pcm(ONE_SECOND), kind=kind
    )


async def test_health_listening_and_speaking() -> None:
    kit: p.KitClient = MemoryKit(heard={hashlib.sha256(ONE_SECOND).hexdigest(): "lights on"})
    health = await kit.health()
    assert health.compatible and health.engine_for(p.Kind.STT, ENGLISH) is not None
    out = await kit.stt(p.SttRequest.of_pcm(ONE_SECOND, lang=ENGLISH))
    assert (out.text, out.seconds, out.slot) == ("lights on", 1.0, p.EngineSlot.WHISPER_SMALL)
    other = await kit.stt(p.SttRequest.of_pcm(b"\x02\x00" * 8_000, lang=ENGLISH))
    assert other.text == MemoryKit.DEFAULT_TEXT and other.seconds == 0.5
    voice = await kit.tts(p.TtsRequest(lang=ENGLISH, text="Good evening."))
    assert voice.format is p.AudioFormat.PCM16 and len(voice.audio_bytes()) % 2 == 0
    mp3 = await kit.tts(p.TtsRequest(lang=ENGLISH, text="Hello.", format=p.AudioFormat.MP3))
    assert mp3.audio_bytes().startswith(b"ID3")


async def test_a_language_without_an_engine_is_refused() -> None:
    kit = MemoryKit()
    with pytest.raises(p.KitRefused) as refused:
        await kit.tts(p.TtsRequest(lang="as-IN", text="x"))
    assert refused.value.code == "unsupported_language"


async def test_down_wrong_key_and_slow_raise_plain_errors() -> None:
    kit = MemoryKit()
    kit.down = "offline"
    with pytest.raises(p.KitUnavailable) as down:
        await kit.health()
    assert down.value.reason == "offline"
    kit.down = "unauthorized"
    with pytest.raises(p.KitUnavailable) as key:
        await kit.stt(p.SttRequest.of_pcm(ONE_SECOND, lang=ENGLISH))
    assert key.value.reason == "unauthorized"
    kit.down = None
    kit.slow = True
    assert (await kit.health()).slow


async def test_a_session_stores_scores_and_deletes_on_the_kit() -> None:
    kit = MemoryKit()
    await kit.put_clip(_clip("cmd_lights"))
    stored = await kit.put_clip(_clip("wake_far_01", kind=p.PromptKind.WAKE))
    assert stored.clips == 2 and kit.clip_count(SESSION) == 2
    job = await kit.score(p.ScoreIn(session_id=SESSION, slots=(p.EngineSlot.WHISPER_SMALL,)))
    assert (await kit.job(job.job_id)).state is p.JobState.DONE
    heard = await kit.results(SESSION)
    assert {r.prompt_id for r in heard.rows} == {"cmd_lights", "wake_far_01"}
    with pytest.raises(p.KitRefused) as missing:
        await kit.job("job_ffffffffffff")
    assert missing.value.code == "not_found"
    gone = await kit.delete(p.DeleteIn())
    assert gone.clips == 2 and kit.clip_count(SESSION) == 0
    assert "audio" not in " ".join(kit.calls)  # the log names calls, never what was in them


async def test_wake_word_training_makes_an_artifact_with_its_hash() -> None:
    kit = MemoryKit()
    await kit.put_clip(_clip("wake_near_01", kind=p.PromptKind.WAKE))
    job = await kit.wakeword_train(
        p.WakeTrainIn(artifact=p.WakeArtifact.VERIFIER, session_id=SESSION)
    )
    assert job.kind is p.JobKind.VERIFIER and job.finished
    status = await kit.wakeword_status()
    assert status.verifier is not None and status.owned is None
    model = await kit.wakeword_model(p.WakeArtifact.VERIFIER)
    assert hashlib.sha256(model.data_bytes()).hexdigest() == model.sha256 == status.verifier.sha256
    with pytest.raises(p.KitRefused):
        await kit.wakeword_model(p.WakeArtifact.OWNED)  # not trained yet
    with pytest.raises(p.KitRefused):
        await kit.wakeword_train(
            p.WakeTrainIn(artifact=p.WakeArtifact.OWNED, session_id="vs_ffffffffffff")
        )  # no clips in that session
    await kit.delete(p.DeleteIn(wakeword=True))
    assert (await kit.wakeword_status()).verifier is None
