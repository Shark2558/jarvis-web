# tests/test_r52_i0_profile.py -- R5.2 I0: the voice profile (docs/plans/r5-2-voice.md 3.3, D7):
# the console's listening engines, the session's results, the learned corrections (never touching
# numbers, money or codes), the listening order, the eval bars and the profile store.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jarvis.localspeech.protocol import EngineSlot, PromptKind
from jarvis.storage.docs import DocTx, MemoryDocs
from jarvis.voice import profile as vp
from jarvis.voice.profile_store import DocProfileStore, MemoryProfileStore
from jarvis.voice.settings import PHRASE_ITEMS

UID = "u_0123456789abcdef"
NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)


def test_the_listening_engines_and_their_laptop_slots() -> None:
    assert vp.ListenEngine.WHISPER_SMALL.slot is EngineSlot.WHISPER_SMALL
    assert vp.ListenEngine.WHISPER_MEDIUM.slot is EngineSlot.WHISPER_MEDIUM
    assert vp.ListenEngine.GOOGLE.slot is None and not vp.ListenEngine.BROWSER.on_laptop
    assert vp.engine_of_slot(EngineSlot.WHISPER_MEDIUM) is vp.ListenEngine.WHISPER_MEDIUM
    with pytest.raises(ValueError):
        vp.engine_of_slot(EngineSlot.KOKORO)  # a voice, not a listening engine
    assert set(vp.LAPTOP_ENGINES) == {e for e in vp.ListenEngine if e.on_laptop}


@pytest.mark.parametrize(
    ("chosen", "laptop_ready", "order"),
    [
        (None, True, ("laptop-whisper-small", "google", "browser")),  # 7a: laptop before Google
        (None, False, ("google", "browser")),  # as today
        ("laptop-whisper-medium", True, ("laptop-whisper-medium", "google", "browser")),
        ("laptop-whisper-medium", False, ("google", "browser")),  # laptop off: fall back
        ("google", True, ("google", "browser")),  # he chose Google: the laptop doesn't listen
        ("browser", True, ("browser", "google")),  # D7: best -> Google -> browser, once each
    ],
)
def test_the_listening_order_is_d7(
    chosen: str | None, laptop_ready: bool, order: tuple[str, ...]
) -> None:
    profile = vp.VoiceProfile(chosen=vp.ListenEngine(chosen) if chosen else None)
    assert vp.listening_order(profile, laptop_ready=laptop_ready) == order


def test_corrections_apply_as_whole_words_case_kept_out_of_numbers() -> None:
    fixes = (
        vp.Correction(heard="java's", meant="JARVIS"),
        vp.Correction(heard="hey java", meant="Hey JARVIS"),
    )
    assert (
        vp.apply_corrections("Hey Java, call Java's desk", fixes) == "Hey JARVIS, call JARVIS desk"
    )
    assert vp.apply_corrections("javascript is not java's", fixes) == "javascript is not JARVIS"
    assert vp.apply_corrections("pay 500 to java's", fixes) == "pay 500 to JARVIS"
    assert vp.apply_corrections("nothing to fix", ()) == "nothing to fix"


@pytest.mark.parametrize(
    ("heard", "meant"),
    [
        ("for", "four"),  # a number word: money and codes are never "corrected"
        ("two", "to"),
        ("rupee", "Rupi"),  # money words too
        ("oh", "Joe"),  # "one oh four" is a code
        ("otp", "OTB"),
        ("a1", "A one"),  # digits
        ("x", "ex"),  # too short to be safe
        ("ok", "₹"),  # a currency sign
        ("one two three four", "x"),  # at most three words heard
    ],
)
def test_a_correction_that_could_touch_numbers_money_or_codes_is_refused(
    heard: str, meant: str
) -> None:
    with pytest.raises(ValidationError):
        vp.Correction(heard=heard, meant=meant)


def test_the_profile_model_and_its_limits() -> None:
    blank = vp.VoiceProfile()
    assert blank.state is vp.SessionState.NONE and blank.chosen is None and blank.best() is None
    scores = (
        vp.EngineScore(engine=vp.ListenEngine.GOOGLE, wer=0.09, commands=0.96, prompts=30),
        vp.EngineScore(engine=vp.ListenEngine.WHISPER_SMALL, wer=0.07, commands=0.97, prompts=30),
    )
    done = vp.VoiceProfile(
        state=vp.SessionState.DONE,
        session_id="vs_0123456789ab",
        chosen=vp.ListenEngine.WHISPER_SMALL,
        ranking=scores,
        measured_at=NOW,
    )
    best = done.best()
    assert best is not None and best.wer == 0.07
    with pytest.raises(ValidationError):
        vp.VoiceProfile(chosen=vp.ListenEngine.GOOGLE, ranking=scores[1:])  # chosen unscored
    with pytest.raises(ValidationError):
        vp.VoiceProfile(corrections=(vp.Correction(heard="java's", meant="JARVIS"),) * 2)
    with pytest.raises(ValidationError):
        vp.EngineScore(engine=vp.ListenEngine.GOOGLE, wer=-0.1, commands=1, prompts=1)
    prompt = vp.Prompt(
        id="wake_far_01", block=4, kind=PromptKind.WAKE, text="Hey Jarvis", how="far"
    )
    assert prompt.held_out is False
    with pytest.raises(ValidationError):
        vp.Prompt(id="cmd_x", block=5, kind=PromptKind.COMMAND, text="x")  # 4 blocks
    assert vp.WORDS_MAX == PHRASE_ITEMS  # new words join R5's "words to recognise"


def test_the_session_and_the_eval_bars_are_the_plans() -> None:
    assert (vp.SESSION_MINUTES, vp.BLOCKS, vp.BLOCK_MINUTES) == (20, 4, 5)
    assert (vp.PROMPTS_TARGET, vp.WAKE_PROMPTS) == (120, 30)
    b = vp.BARS
    assert (b.wer_margin_points, b.commands_min) == (2.0, 0.95)
    assert (b.false_wakes_per_hour_max, b.wake_miss_max, b.other_speaker_reject_min) == (
        0.5,
        0.05,
        0.90,
    )
    assert (b.speaker_eer_max, b.first_audio_gpu_s, b.first_audio_cpu_s) == (0.05, 0.7, 1.5)
    assert b.stt_realtime_factor_min == 3.0 and b.tv_audio_hours == 2.0
    assert b.recognition_ok(chosen_wer=0.09, best_cloud_wer=0.07, commands=0.95)
    assert not b.recognition_ok(chosen_wer=0.10, best_cloud_wer=0.07, commands=0.99)
    assert not b.recognition_ok(chosen_wer=0.05, best_cloud_wer=0.07, commands=0.94)


def test_spoken_by_the_owner_is_a_label_never_an_approval() -> None:
    assert vp.SPOKEN_BY_HEADER == "x-jarvis-spoken-by" and vp.SPOKEN_BY_OWNER == "owner"
    assert "never" in (vp.__doc__ or "").lower() and "approv" in (vp.__doc__ or "").lower()


async def test_the_doc_store_round_trips_and_a_bad_document_reads_as_the_default() -> None:
    docs = MemoryDocs()
    store = DocProfileStore(docs, prefix="t_")
    assert await store.get(UID) == vp.VoiceProfile()
    chosen = vp.VoiceProfile(state=vp.SessionState.RECORDING, session_id="vs_0123456789ab", clips=3)
    await store.save(UID, chosen)
    assert await DocProfileStore(docs, prefix="t_").get(UID) == chosen  # a fresh cache reads it
    bumped = await store.update(UID, lambda cur: cur.model_copy(update={"clips": cur.clips + 1}))
    assert bumped.clips == 4
    raw = await docs.get(f"t_voice_profile/{UID}")
    assert raw is not None and raw["clips"] == 4 and raw["user_id"] == UID and "updated_at" in raw

    async def corrupt(tx: DocTx) -> None:
        tx.set(f"t_voice_profile/{UID}", {"state": "nonsense", "clips": -4})

    await docs.transaction(corrupt)
    assert await DocProfileStore(docs, prefix="t_").get(UID) == vp.VoiceProfile()
    assert await store.delete(UID) is True and await store.delete(UID) is False
    assert await DocProfileStore(docs, prefix="t_").get(UID) == vp.VoiceProfile()
    with pytest.raises(ValueError):
        await store.get("../other")


async def test_the_memory_store_keeps_the_same_contract() -> None:
    store = MemoryProfileStore()
    assert await store.get(UID) == vp.VoiceProfile()
    await store.save(UID, vp.VoiceProfile(clips=2))
    got = await store.update(UID, lambda cur: cur.model_copy(update={"clips": 5}))
    assert got.clips == 5 and (await store.get(UID)).clips == 5
    assert await store.delete(UID) and not await store.delete(UID)
