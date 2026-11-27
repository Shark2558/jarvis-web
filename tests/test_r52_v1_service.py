# tests/test_r52_v1_service.py -- R5.2 V1: what the kit does per request, without HTTP. Busy while a
# long job trains, slow while a job runs, a broken engine put away (the cloud falls back), voices
# and MP3, resampled PCM, the score job over held-out clips only, delete stopping its job, and the
# wake-word seam (V4's trainer; the stub refuses).
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from kit_fakes import ENGLISH_ONLY, Engines, FakeMp3, FakeTrainer, make_service, pcm, sha

from jarvis.localspeech import protocol as p
from jarvis.localspeech.ports import NOT_BUILT, NoWakeword

SID = "vs_00000000000a"


def clip(
    prompt: str, audio: bytes, *, kind: p.PromptKind = p.PromptKind.COMMAND, held_out: bool = True
) -> p.ClipIn:
    return p.ClipIn(
        session_id=SID, prompt_id=prompt, audio=p.encode_pcm(audio), kind=kind, held_out=held_out
    )


async def test_health_reports_engines_memory_and_jobs(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, ready=ENGLISH_ONLY)
    health = await service.health()
    assert (health.gpu_free_mb, health.ram_free_mb, health.jobs_running, health.slow) == (
        3_000,
        8_000,
        0,
        False,
    )
    assert health.languages(p.Kind.STT) == ("en-IN",)
    indic = {e.slot: e for e in health.engines}[p.EngineSlot.INDIC_CONFORMER]
    assert not indic.ready and "Not installed" in indic.reason


async def test_listening_uses_the_asked_engine_and_the_owners_words(tmp_path: Path) -> None:
    service, engines = make_service(tmp_path)
    audio = pcm(2.0, 5)
    engines.heard[sha(audio)] = "  call Ananya  "
    req = p.SttRequest.of_pcm(
        audio, lang="en-IN", slot=p.EngineSlot.WHISPER_MEDIUM, phrases=("Ananya",)
    )
    heard = await service.stt(req)
    assert (heard.text, heard.slot, heard.seconds, heard.alternatives) == (
        "call Ananya",
        p.EngineSlot.WHISPER_MEDIUM,
        2.0,
        ("hello travis",),
    )
    hindi = await service.stt(p.SttRequest.of_pcm(audio, lang="hi-IN"))
    assert hindi.slot is p.EngineSlot.INDIC_CONFORMER


async def test_a_language_without_an_engine_is_refused(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, ready=ENGLISH_ONLY)
    with pytest.raises(p.KitRefused) as no_engine:
        await service.stt(p.SttRequest.of_pcm(pcm(), lang="ml-IN"))
    assert no_engine.value.code == "engine_not_ready"
    with pytest.raises(p.KitRefused) as wrong_slot:
        await service.stt(p.SttRequest.of_pcm(pcm(), lang="ml-IN", slot=p.EngineSlot.WHISPER_SMALL))
    assert wrong_slot.value.code == "unsupported_language"


async def test_speaking_resamples_to_16_khz_and_checks_the_voice(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    service, _ = make_service(tmp_path, engines=Engines(tts_rate=24_000))
    spoken = await service.tts(
        p.TtsRequest(lang="en-IN", text="Good morning, sir.", voice="bm_lewis")
    )
    assert spoken.sample_rate == 16_000 and spoken.voice == "bm_lewis"
    assert len(spoken.audio_bytes()) == pytest.approx(2 * 16_000 * 18 * 0.05, rel=0.01)
    with pytest.raises(p.KitRefused) as unknown:
        await service.tts(p.TtsRequest(lang="en-IN", text="Hello.", voice="af_heart"))
    assert unknown.value.code == "bad_request"


async def test_mp3_keeps_the_engines_rate_when_mp3_allows_it(tmp_path: Path) -> None:
    mp3 = FakeMp3()
    service, _ = make_service(tmp_path, mp3=mp3, engines=Engines(tts_rate=24_000))
    spoken = await service.tts(p.TtsRequest(lang="en-IN", text="Hello.", format=p.AudioFormat.MP3))
    assert spoken.sample_rate == 24_000 and mp3.rates == [24_000]
    assert spoken.first_audio_ms == 120 and spoken.seconds == pytest.approx(0.3)


async def test_a_broken_engine_is_put_away_and_refused_as_not_ready(tmp_path: Path) -> None:
    service, engines = make_service(tmp_path)
    service.slots.stt(p.EngineSlot.WHISPER_SMALL)
    broken = engines.made[p.EngineSlot.WHISPER_SMALL]
    broken.broken = True  # type: ignore[union-attr]
    with pytest.raises(p.KitRefused) as refused:
        await service.stt(p.SttRequest.of_pcm(pcm(), lang="en-IN"))
    assert refused.value.code == "engine_not_ready" and "secret" not in refused.value.words
    assert broken.closed and p.EngineSlot.WHISPER_SMALL not in service.slots.loaded()
    assert (await service.stt(p.SttRequest.of_pcm(pcm(), lang="en-IN"))).text == "hello jarvis"


async def test_scoring_hears_only_the_held_out_clips_with_every_asked_engine(
    tmp_path: Path,
) -> None:
    service, engines = make_service(tmp_path)
    a, b, c = pcm(1.0, 1), pcm(1.0, 2), pcm(1.0, 3)
    engines.heard[sha(a)] = "open the calendar"
    await service.put_clip(clip("cmd_a", a))
    await service.put_clip(clip("cmd_b", b))
    await service.put_clip(clip("cmd_c", c, held_out=False))  # trained on, never scored
    slots = (p.EngineSlot.WHISPER_SMALL, p.EngineSlot.WHISPER_MEDIUM)
    job = await service.score(p.ScoreIn(session_id=SID, slots=slots, phrases=("calendar",)))
    done = await service.runner.wait(job.job_id)
    assert done.state is p.JobState.DONE and done.progress == 1.0 and "2 recordings" in done.words
    heard = await service.results(p.ResultsIn(session_id=SID))
    assert [(r.prompt_id, r.slot) for r in heard.rows] == [
        ("cmd_a", slots[0]),
        ("cmd_b", slots[0]),
        ("cmd_a", slots[1]),
        ("cmd_b", slots[1]),
    ]
    assert heard.rows[0].text == "open the calendar"


async def test_scoring_needs_recordings_and_ready_engines(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, ready=ENGLISH_ONLY - {p.EngineSlot.WHISPER_MEDIUM})
    with pytest.raises(p.KitRefused) as empty:
        await service.score(p.ScoreIn(session_id=SID, slots=(p.EngineSlot.WHISPER_SMALL,)))
    assert empty.value.code == "not_found"
    await service.put_clip(clip("cmd_a", pcm()))
    with pytest.raises(p.KitRefused) as not_ready:
        await service.score(p.ScoreIn(session_id=SID, slots=(p.EngineSlot.WHISPER_MEDIUM,)))
    assert not_ready.value.code == "engine_not_ready"


async def test_training_makes_the_kit_busy_and_slow_and_delete_stops_it(tmp_path: Path) -> None:
    trainer = FakeTrainer(block=True)
    service, _ = make_service(tmp_path, trainer=trainer)
    await service.put_clip(clip("wake_1", pcm(1.0, 4), kind=p.PromptKind.WAKE, held_out=False))
    await service.put_clip(clip("cmd_1", pcm(1.0, 5)))
    job = await service.wake_train(p.WakeTrainIn(artifact=p.WakeArtifact.VERIFIER, session_id=SID))
    await asyncio.sleep(0.05)
    assert (await service.health()).slow and (await service.health()).jobs_running == 1
    with pytest.raises(p.KitRefused) as busy:
        await service.stt(p.SttRequest.of_pcm(pcm(), lang="en-IN"))
    assert busy.value.code == "busy"
    with pytest.raises(p.KitRefused) as second:
        await service.score(p.ScoreIn(session_id=SID, slots=(p.EngineSlot.WHISPER_SMALL,)))
    assert second.value.code == "busy"
    deleted = await service.delete(p.DeleteIn(session_id=None, wakeword=True))
    stopped = await service.runner.wait(job.job_id)
    assert stopped.state is p.JobState.CANCELLED and deleted.clips == 2
    assert trainer.given == [1]  # the wake clip only
    assert not (await service.health()).slow


async def test_the_trained_file_comes_back_from_the_trainer(tmp_path: Path) -> None:
    trainer = FakeTrainer()
    service, _ = make_service(tmp_path, trainer=trainer)
    with pytest.raises(p.KitRefused) as none:
        await service.wake_train(p.WakeTrainIn(artifact=p.WakeArtifact.OWNED, session_id=SID))
    assert none.value.code == "not_found"
    await service.put_clip(clip("wake_1", pcm(1.0, 4), kind=p.PromptKind.WAKE))
    job = await service.wake_train(p.WakeTrainIn(artifact=p.WakeArtifact.OWNED, session_id=SID))
    assert job.kind is p.JobKind.OWNED
    await service.runner.wait(job.job_id)
    status = await service.wake_status()
    assert status.owned is not None and status.verifier is None
    assert [j.kind for j in status.jobs] == [p.JobKind.OWNED]
    model = await service.wake_model(p.WakeModelIn(artifact=p.WakeArtifact.OWNED))
    assert model.sha256 == status.owned.sha256
    gone = await service.delete(p.DeleteIn(session_id=SID, wakeword=True))
    assert (gone.clips, gone.wakeword_files) == (1, 1)


async def test_the_stub_refuses_every_wake_word_request(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    assert isinstance(service.wakeword, NoWakeword)
    await service.put_clip(clip("wake_1", pcm(1.0, 4), kind=p.PromptKind.WAKE))
    with pytest.raises(p.KitRefused) as refused:
        await service.wake_train(p.WakeTrainIn(artifact=p.WakeArtifact.VERIFIER, session_id=SID))
    assert (refused.value.code, refused.value.words) == ("engine_not_ready", NOT_BUILT)
    assert (await service.wake_status()) == p.WakeStatus()
    with pytest.raises(p.KitRefused):
        await service.wake_model(p.WakeModelIn(artifact=p.WakeArtifact.VERIFIER))
    assert (await service.delete(p.DeleteIn(wakeword=True))).wakeword_files == 0
