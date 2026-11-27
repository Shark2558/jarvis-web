# tests/test_r52_review_delete_here.py -- R5.2 review row 18, the owner's decision of 28 Nov 2026:
# with no laptop speech kit set up, "Delete my recordings" still clears the comparison's words
# here (Firestore). The safe default: the laptop's recordings can't be reached, so none is
# claimed gone and their count stays; a kit that is set up but down still refuses, nothing deleted.
from __future__ import annotations

import pytest
from r52_v3_fakes import UID, FakeGoogle, FakeWords, normalise, pcm, sha, wav

from jarvis.localspeech.memory import MemoryKit
from jarvis.voice.profile import SessionState
from jarvis.voice.profile_ports import ProfileRefused
from jarvis.voice.profile_store import MemoryProfileStore
from jarvis.voice.session import SessionParts, StartIn, VoiceSessions
from jarvis.voice.session_api import SessionApi
from jarvis.voice.session_privacy import voice_session_sources
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
        await s.put_clip(UID, p.id, wav(data), p.text)
    await s.score(UID)
    return s, kit, doc.session_id


async def test_with_no_kit_set_up_the_comparisons_words_here_are_deleted() -> None:
    s, kit, session_id = await _scored()
    assert await s.current(UID) is not None
    before = await s.profile(UID)
    s.p.kit = None  # the kit's address or key taken off this server
    gone = await s.delete_recordings(UID)
    assert gone.clips == 0 and gone.wakeword_files == 0  # nothing claimed gone on the laptop
    assert await s.current(UID) is None  # the comparison's words, gone from Firestore
    profile = await s.profile(UID)
    assert profile.clips == 120  # the laptop's recordings are still counted
    assert profile.session_id is None and profile.state is SessionState.DONE
    assert profile.ranking == before.ranking and profile.chosen == before.chosen  # results stay
    assert kit.clip_count(session_id) == 120  # never reached


async def test_a_kit_that_is_set_up_but_down_still_deletes_nothing() -> None:
    s, kit, _ = await _scored()
    kit.down = "offline"
    with pytest.raises(ProfileRefused) as info:
        await s.delete_recordings(UID)
    assert info.value.status == 503 and await s.current(UID) is not None


async def test_the_privacy_row_with_no_kit_deletes_the_words_and_counts_what_is_left() -> None:
    s, _, _ = await _scored()
    s.p.kit = None
    _, recordings, wake = voice_session_sources(s)
    assert await recordings.delete(UID) == 0
    view = await recordings.describe(UID)
    assert view.count == 120  # the dashboard reports them as left, never a clean success
    assert "comparison_lines" not in (await recordings.export(UID) or {})
    assert await wake.delete(UID) == 0 and await s.current(UID) is None


async def test_the_answer_with_no_kit_says_what_went_and_what_stays() -> None:
    s, _, _ = await _scored()
    s.p.kit = None
    got = await SessionApi(s).delete_recordings(UID)
    assert got["clips"] == 0 and got["wakeword_files"] == 0
    words = str(got["words"]).casefold()
    assert "comparison" in words and "deleted" in words
    assert "laptop" in words and "deleted 0" not in words and "stay" in words
