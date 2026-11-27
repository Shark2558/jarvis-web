# tests/test_r52_v3_session.py -- R5.2 V3: the voice session end to end on MemoryKit (plan 3.3,
# 4, 5; brief "Costs", "Recognition"). Clips go to the kit only; Google hears the held-out lines
# free-only inside the free minutes, and beyond them only after his typed YES (402 needs_yes with
# the ₹ first, nothing stored); scoring chooses the laptop within the bar, learns the repeating
# mishearing, and his new words join R5's one list; "Delete my recordings" needs the laptop.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from r52_v3_fakes import (
    UID,
    FakeGoogle,
    FakeWords,
    budget_reached,
    google_down,
    normalise,
    pcm,
    sha,
    wav,
)

from jarvis.billing.service import FreeAllowanceUsed
from jarvis.localspeech.memory import MemoryKit
from jarvis.localspeech.protocol import JobKind, JobState, JobView, PromptKind, ScoreIn
from jarvis.voice.profile import ListenEngine, SessionState
from jarvis.voice.profile_ports import ProfileRefused
from jarvis.voice.profile_store import MemoryProfileStore
from jarvis.voice.session import SessionParts, StartIn, VoiceSessions
from jarvis.voice.session_prompts import scored
from jarvis.voice.session_store import CompareMode, MemorySessionStore, SessionDoc

NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)


class Rig:
    def __init__(self, *, kit: MemoryKit | None = None, minutes: int = 20, **google: Any) -> None:
        self.kit = MemoryKit() if kit is None else kit
        self.google = FakeGoogle(**google)
        self.words = FakeWords(["Zephyrine"])
        self.profiles = MemoryProfileStore()
        self.sessions = MemorySessionStore()
        self.s = VoiceSessions(
            SessionParts(
                kit=self.kit,
                profiles=self.profiles,
                sessions=self.sessions,
                google=self.google,
                words=self.words,
                normalise=normalise,
                compare_minutes=minutes,
                now=lambda: NOW,
            )
        )

    async def doc(self) -> SessionDoc:
        doc = await self.sessions.get(UID)
        assert doc is not None
        return doc

    async def record(self, doc: SessionDoc, *, only: int | None = None) -> None:
        """Every prompt read once: the laptop mishears "Jarvis", Google hears all, the browser
        drops the first word of every fourth line."""
        for i, p in enumerate(doc.prompts[:only]):
            data = pcm(i)
            self.kit.heard[sha(data)] = p.text.replace("Jarvis", "Java's")
            self.google.heard[sha(data)] = p.text
            browser = " ".join(p.text.split()[1:]) if i % 4 == 0 else p.text
            await self.s.put_clip(UID, p.id, wav(data), browser)


async def _refused(coro: Any) -> ProfileRefused:
    with pytest.raises(ProfileRefused) as info:
        await coro
    return info.value


async def test_no_kit_or_a_kit_that_is_down_starts_nothing() -> None:
    rig = Rig()
    rig.s.p.kit = None
    assert (await _refused(rig.s.start(UID, StartIn()))).code == "laptop_not_set_up"
    rig = Rig()
    rig.kit.down = "offline"
    got = await _refused(rig.s.start(UID, StartIn()))
    assert got.status == 503 and got.code == "laptop_unavailable" and "laptop" in got.words
    assert await rig.sessions.get(UID) is None


async def test_a_session_inside_the_free_minutes_starts_free() -> None:
    rig = Rig()
    doc = await rig.s.start(UID, StartIn(words=("Quillon",)))
    assert doc.compare.mode is CompareMode.FREE and doc.compare.cap_clips == 80
    assert doc.compare.minutes == 20 and doc.compare.inr_max == pytest.approx(45.72, abs=0.01)
    assert len(doc.prompts) == 120 and doc.typed == ("Quillon",)
    assert any("Quillon" in p.text for p in doc.prompts)
    assert (await rig.profiles.get(UID)).state is SessionState.RECORDING
    again = await rig.s.start(UID, StartIn())
    assert again.session_id == doc.session_id  # resumed, not replaced


async def test_beyond_the_free_minutes_the_rupee_question_comes_first() -> None:
    rig = Rig(free_left=100.0)
    got = await _refused(rig.s.start(UID, StartIn()))
    assert got.status == 402 and got.code == "needs_yes"
    assert "₹2.29 a minute" in got.words and "at most about ₹46" in got.words
    assert "about 20 minutes" in got.words and "YES" in got.words
    assert await rig.sessions.get(UID) is None and rig.kit.calls == ["health"]
    doc = await rig.s.start(UID, StartIn(yes=True))
    assert doc.compare.mode is CompareMode.YES and doc.compare.yes_at == NOW
    skip = await Rig(free_left=0).s.start(UID, StartIn(skip_google=True))
    assert skip.compare.mode is CompareMode.OFF
    assert (await Rig(is_ready=False).s.start(UID, StartIn())).compare.mode is (
        CompareMode.UNAVAILABLE
    )
    assert (await Rig(minutes=0).s.start(UID, StartIn())).compare.mode is CompareMode.OFF


async def test_clips_go_to_the_laptop_and_google_hears_only_the_held_out_lines() -> None:
    rig = Rig()
    doc = await rig.s.start(UID, StartIn())
    await rig.record(doc, only=12)
    doc = await rig.doc()
    first12 = doc.prompts[:12]
    held = [p for p in first12 if scored(p)]
    assert rig.kit.clip_count(doc.session_id) == 12 and len(doc.done) == 12
    assert rig.google.calls == [True] * len(held)  # free-only, never priced
    assert set(doc.google) == {p.id for p in held} == set(doc.browser)
    assert not any(p.kind is PromptKind.WAKE for p in first12 if p.id in doc.google)
    assert doc.compare.clips == len(held) and doc.compare.seconds == 15 * len(held)
    profile = await rig.profiles.get(UID)
    assert profile.clips == 12 and profile.compare_seconds == 15 * len(held)


async def test_free_minutes_running_out_ask_before_the_clip_is_stored() -> None:
    rig = Rig()
    doc = await rig.s.start(UID, StartIn())
    rig.google.free_left = 5.0
    line = next(p for p in doc.prompts if scored(p))
    got = await _refused(rig.s.put_clip(UID, line.id, wav(pcm(1))))
    assert got.status == 402 and got.code == "needs_yes"
    assert rig.kit.clip_count(doc.session_id) == 0
    assert (await rig.doc()).compare.mode is CompareMode.NEEDS_YES
    yes = await rig.s.start(UID, StartIn(yes=True))
    assert yes.compare.mode is CompareMode.YES and yes.compare.inr_max == pytest.approx(45.72, 0.01)
    await rig.s.put_clip(UID, line.id, wav(pcm(1)))
    assert rig.google.calls == [False]  # priced now, after his YES
    wake = next(p for p in doc.prompts if p.kind is PromptKind.WAKE)
    await rig.s.put_clip(UID, wake.id, wav(pcm(2)))  # a wake clip never asks
    assert rig.kit.clip_count(doc.session_id) == 2


async def test_google_refusing_mid_call_keeps_the_clip_and_changes_the_mode() -> None:
    rig = Rig(free_used_after=1)
    doc = await rig.s.start(UID, StartIn())
    lines = [p for p in doc.prompts if scored(p)]
    await rig.s.put_clip(UID, lines[0].id, wav(pcm(0)))
    done = await rig.s.put_clip(UID, lines[1].id, wav(pcm(1)))
    assert done.compare is CompareMode.NEEDS_YES and rig.kit.clip_count(doc.session_id) == 2
    assert lines[1].id not in (await rig.doc()).google
    skip = await rig.s.start(UID, StartIn(skip_google=True))
    assert skip.compare.mode is CompareMode.OFF
    rig2 = Rig(free_left=0)
    await rig2.s.start(UID, StartIn(yes=True))
    rig2.google.fail = budget_reached()
    doc2 = await rig2.doc()
    first = next(p for p in doc2.prompts if scored(p))
    assert (await rig2.s.put_clip(UID, first.id, wav(pcm(3)))).compare is CompareMode.LIMIT
    rig2.google.fail = None
    second = [p for p in doc2.prompts if scored(p)][1]
    await rig2.s.put_clip(UID, second.id, wav(pcm(4)))
    assert len(rig2.google.calls) == 1  # no more Google after the limit


async def test_google_down_skips_that_clip_only_and_the_cap_holds() -> None:
    rig = Rig(minutes=1, fail=google_down())
    doc = await rig.s.start(UID, StartIn())
    assert doc.compare.cap_clips == 4
    lines = [p for p in doc.prompts if scored(p)]
    await rig.s.put_clip(UID, lines[0].id, wav(pcm(0)))
    assert (await rig.doc()).compare.mode is CompareMode.FREE and not (await rig.doc()).google
    rig.google.fail = None
    for i, p in enumerate(lines[1:8], 1):
        await rig.s.put_clip(UID, p.id, wav(pcm(i)))
    assert len(rig.google.calls) == 5 and len((await rig.doc()).google) == 4


@pytest.mark.parametrize(
    ("audio", "code"),
    [(b"not a wav", "bad_audio"), (wav(pcm(1, seconds=21)), "bad_audio")],
)
async def test_bad_clips_and_unknown_prompts_are_refused(audio: bytes, code: str) -> None:
    rig = Rig()
    assert (await _refused(rig.s.put_clip(UID, "b1_comm_01", audio))).code == "no_session"
    doc = await rig.s.start(UID, StartIn())
    assert (await _refused(rig.s.put_clip(UID, doc.prompts[0].id, audio))).code == code
    got = await _refused(rig.s.put_clip(UID, "b9_nope_01", wav(pcm(1))))
    assert got.status == 404 and rig.kit.clip_count(doc.session_id) == 0


async def test_the_whole_session_chooses_the_laptop_learns_and_joins_his_words() -> None:
    rig = Rig()
    doc = await rig.s.start(UID, StartIn(words=("Quillon",)))
    await rig.record(doc)
    scored_doc = await rig.s.score(UID)
    assert scored_doc.state is SessionState.DONE and scored_doc.words_added == ("Quillon",)
    assert rig.words.words == ["Zephyrine", "Quillon"]
    profile = await rig.profiles.get(UID)
    engines = [s.engine for s in profile.ranking]
    assert engines[0] is ListenEngine.GOOGLE and set(engines) == {
        ListenEngine.GOOGLE,
        ListenEngine.WHISPER_SMALL,
        ListenEngine.BROWSER,
    }
    assert profile.chosen is ListenEngine.WHISPER_SMALL  # within 2 points of Google
    assert [(c.heard, c.meant) for c in profile.corrections] == [("java's", "Jarvis")]
    assert profile.state is SessionState.DONE and profile.measured_at == NOW
    assert "score" in rig.kit.calls and "results" in rig.kit.calls


async def test_too_few_lines_and_a_failed_or_slow_job() -> None:
    rig = Rig()
    doc = await rig.s.start(UID, StartIn())
    await rig.record(doc, only=8)
    assert (await _refused(rig.s.score(UID))).code == "too_few"

    class SlowKit(MemoryKit):
        state = JobState.RUNNING

        async def score(self, req: ScoreIn) -> JobView:
            await super().score(req)
            return JobView(job_id="job_" + "a" * 12, kind=JobKind.SCORE, state=self.state)

        async def job(self, job_id: str) -> JobView:
            return JobView(job_id=job_id, kind=JobKind.SCORE, state=self.state, progress=0.5)

    slow = Rig(kit=SlowKit())
    doc = await slow.s.start(UID, StartIn())
    await slow.record(doc)
    assert (await slow.s.score(UID)).state is SessionState.SCORING
    got, job = await slow.s.poll(UID)
    assert got is not None and got.state is SessionState.SCORING and job and job.progress == 0.5
    SlowKit.state = JobState.FAILED
    got, _ = await slow.s.poll(UID)
    assert got is not None and got.state is SessionState.FAILED and got.reason
    assert (await slow.profiles.get(UID)).state is SessionState.FAILED
    SlowKit.state = JobState.DONE
    assert (await slow.s.recheck(UID)).state is SessionState.DONE


async def test_check_again_and_delete_my_recordings() -> None:
    rig = Rig()
    doc = await rig.s.start(UID, StartIn())
    await rig.record(doc)
    await rig.s.score(UID)
    assert (await rig.s.recheck(UID)).state is SessionState.DONE
    rig.kit.down = "offline"
    assert (await _refused(rig.s.delete_recordings(UID))).status == 503
    assert await rig.sessions.get(UID) is not None  # nothing deleted while the laptop is away
    rig.kit.down = None
    gone = await rig.s.delete_recordings(UID)
    assert gone.clips == 120 and rig.kit.clip_count(doc.session_id) == 0
    assert await rig.sessions.get(UID) is None
    profile = await rig.profiles.get(UID)
    assert profile.clips == 0 and profile.session_id is None and profile.state is SessionState.DONE
    assert profile.chosen is ListenEngine.WHISPER_SMALL  # the results stay
    assert (await _refused(rig.s.recheck(UID))).code == "no_recordings"


async def test_a_new_session_replaces_the_last_ones_recordings() -> None:
    rig = Rig()
    first = await rig.s.start(UID, StartIn())
    await rig.record(first, only=5)
    second = await rig.s.start(UID, StartIn(restart=True))
    assert second.session_id != first.session_id
    assert rig.kit.clip_count(first.session_id) == 0 and second.done == ()


async def test_he_changes_the_engine_switches_corrections_and_forgets_one() -> None:
    rig = Rig()
    doc = await rig.s.start(UID, StartIn())
    await rig.record(doc)
    await rig.s.score(UID)
    got = await _refused(rig.s.change_profile(UID, chosen=ListenEngine.WHISPER_MEDIUM))
    assert got.code == "not_ranked"
    p = await rig.s.change_profile(UID, chosen=ListenEngine.GOOGLE, corrections_on=False)
    assert p.chosen is ListenEngine.GOOGLE and not p.corrections_on
    p = await rig.s.change_profile(UID, forget="Java's")
    assert p.corrections == ()


async def test_the_laptop_health_is_cached_and_never_raises() -> None:
    rig = Rig()
    assert await rig.s.laptop_ready() is True
    rig.kit.down = "offline"
    assert await rig.s.laptop_ready() is True  # cached
    rig.s._health = None
    assert await rig.s.laptop_ready() is False
    rig.s.p.kit = None
    assert await rig.s.laptop_ready() is False
    google = FakeGoogle(fail=FreeAllowanceUsed())
    assert google.ready()
