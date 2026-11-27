# tests/test_r52_v3_privacy.py -- R5.2 V3: the voice profile, the session's recordings and the
# wake-word files made from them on the privacy dashboard (plan 5 "Privacy"). No audio is ever
# exported; deleting the recordings needs the laptop (else nothing claims to be gone); the
# wake-word row deletes the recordings with them and says so.
from __future__ import annotations

import json

import pytest
from r52_v3_fakes import UID, FakeGoogle, FakeWords, normalise, pcm, sha, wav

from jarvis.localspeech.memory import MemoryKit
from jarvis.localspeech.protocol import KitUnavailable, WakeArtifact, WakeTrainIn
from jarvis.voice.profile import ListenEngine
from jarvis.voice.profile_store import MemoryProfileStore
from jarvis.voice.session import SessionParts, StartIn, VoiceSessions
from jarvis.voice.session_privacy import SOURCE_IDS, voice_session_sources
from jarvis.voice.session_store import MemorySessionStore


async def _scored() -> tuple[VoiceSessions, MemoryKit, str]:
    kit, google = MemoryKit(), FakeGoogle()
    s = VoiceSessions(
        SessionParts(
            kit=kit,
            profiles=MemoryProfileStore(),
            sessions=MemorySessionStore(),
            google=google,
            words=FakeWords(),
            normalise=normalise,
        )
    )
    doc = await s.start(UID, StartIn())
    for i, p in enumerate(doc.prompts):
        data = pcm(i)
        kit.heard[sha(data)] = google.heard[sha(data)] = p.text.replace("Jarvis", "Java's")
        browser = " ".join(p.text.split()[1:]) if i % 4 == 0 else p.text
        await s.put_clip(UID, p.id, wav(data), browser)
    await s.score(UID)
    return s, kit, doc.session_id


async def test_three_rows_with_counts_and_no_audio_in_the_export() -> None:
    s, kit, _ = await _scored()
    profile, recordings, wake = voice_session_sources(s)
    assert (profile.id, recordings.id, wake.id) == SOURCE_IDS
    pv, rv, wv = [await x.describe(UID) for x in (profile, recordings, wake)]
    assert pv.count and pv.count >= 4 and pv.delete == "simple"  # 3 engines, chosen, corrections
    assert rv.count == 120 and rv.delete == "confirm" and "laptop" in rv.where
    assert wv.count == 0 and wv.delete == "none" and not wv.export
    exported = json.dumps([await profile.export(UID), await recordings.export(UID)])
    assert "audio" not in exported and "pcm" not in exported.casefold()
    assert '"recordings_on_laptop": 120' in exported and "browser_heard" in exported
    assert (await profile.export(UID))["voice_profile"]["chosen"] == ListenEngine.WHISPER_SMALL


async def test_deleting_the_recordings_keeps_the_profile_and_needs_the_laptop() -> None:
    s, kit, session_id = await _scored()
    _, recordings, _ = voice_session_sources(s)
    kit.down = "offline"
    with pytest.raises(Exception):  # noqa: B017 - the dashboard turns any failure into its words
        await recordings.delete(UID)
    assert kit.clip_count(session_id) == 120
    kit.down = None
    assert await recordings.delete(UID) == 120 and kit.clip_count(session_id) == 0
    assert (await recordings.describe(UID)).delete == "none"
    assert (await s.profile(UID)).chosen is ListenEngine.WHISPER_SMALL


async def test_the_wake_word_files_row_counts_the_laptops_files_and_deletes_both() -> None:
    s, kit, session_id = await _scored()
    await kit.wakeword_train(WakeTrainIn(artifact=WakeArtifact.VERIFIER, session_id=session_id))
    _, _, wake = voice_session_sources(s)
    view = await wake.describe(UID)
    assert view.count == 1 and view.delete == "confirm" and "also deletes" in view.note
    assert await wake.delete(UID) == 1
    assert kit.clip_count(session_id) == 0 and (await wake.describe(UID)).count == 0
    kit.down = "offline"
    with pytest.raises(KitUnavailable):  # "Couldn't check right now" on the dashboard
        await wake.describe(UID)


async def test_deleting_the_profile_goes_back_to_the_usual_order() -> None:
    s, _, _ = await _scored()
    profile, _, _ = voice_session_sources(s)
    assert await profile.delete(UID) >= 4
    view = await profile.describe(UID)
    assert view.count == 0 and view.delete == "none"
    assert (await s.profile(UID)).chosen is None
