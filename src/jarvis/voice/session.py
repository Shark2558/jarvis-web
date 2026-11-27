# src/jarvis/voice/session.py
"""The 20-minute voice session (R5.2 row 81; docs/plans/r5-2-voice.md 3.3, D4, D7; Layers 2, 7).

    start      the ₹ question first (below), then ~120 prompts in 4 blocks (`session_prompts`);
               a new session replaces the last one's recordings on the laptop
    put_clip   a WAV from the console -> PCM16 -> the laptop kit (`KitClient.put_clip`: stored
               there only, encrypted); a held-out line also goes to Google with his words, and the
               browser's transcript is kept. The cloud keeps no audio.
    score      the laptop engines hear the held-out clips (`KitClient.score`, a job, polled)
    results    every engine scored (`session_score`), the best chosen, repeating mishearings
               become corrections, new words join his "words to recognise" (R5's
               `VoiceSettings.phrases`, at most 50: the one list); the voice profile keeps it all
    recheck    "Check again": the laptop hears the same clips again (a newer kit, medium Whisper)
    delete     "Delete my recordings" on the laptop (optionally the wake-word files made from
               them) and the session's transcripts here; the results stay

The ₹ question and Google's part: `jarvis.voice.session_compare`. Transcripts, audio and his words
are never logged.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

from jarvis.calls.models import ENGLISH
from jarvis.localspeech.protocol import (
    CLIP_MAX_S,
    PHRASE_CHARS,
    ClipIn,
    Deleted,
    DeleteIn,
    EngineSlot,
    HeardRow,
    JobState,
    JobView,
    Kind,
    KitClient,
    KitError,
    KitRefused,
    KitUnavailable,
    ScoreIn,
    encode_pcm,
    new_session_id,
)
from jarvis.logging import get_logger
from jarvis.voice.ports import BadAudio
from jarvis.voice.profile import (
    RANKING_MAX,
    Correction,
    ListenEngine,
    SessionState,
    VoiceProfile,
    engine_of_slot,
)
from jarvis.voice.profile_ports import ProfileRefused, ProfileStore
from jarvis.voice.session_compare import (
    STEP_S,
    Comparison,
    GoogleEar,
    GoogleHeard,
    needs_yes,
    with_,
)
from jarvis.voice.session_prompts import build_prompts, scored
from jarvis.voice.session_score import (
    MIN_PROMPTS,
    Heard,
    Normalise,
    choose,
    learn_corrections,
    new_words,
    score_engines,
)
from jarvis.voice.session_store import HEARD_CHARS, Compare, CompareMode, SessionDoc, SessionStore
from jarvis.voice.wav import parse_wav

log = get_logger(__name__)

LAPTOP_SLOTS: Final = (EngineSlot.WHISPER_SMALL, EngineSlot.WHISPER_MEDIUM)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")
NO_KIT = (
    "The voice session needs the laptop speech kit, and it isn't set up on this server yet "
    "(JARVIS_LOCAL_SPEECH_URL and its key)."
)
OUTDATED = "The laptop speech kit is a different version from JARVIS's: update the kit first."
NO_ENGINE = "The laptop speech kit has no English listening engine ready yet."
NO_SESSION = "There is no voice session in progress. Start one first."
NO_PROMPT = "That prompt is not part of this session."
TOO_FEW = (
    f"Record at least {MIN_PROMPTS} of the comparison lines first (the ones marked for the "
    "comparison), so the engines can be compared fairly."
)
NO_RECORDINGS = (
    "Your recordings are no longer on the laptop, so there is nothing to check again. Record a "
    "new session instead."
)
NOT_ENOUGH = "Not enough was heard to compare the engines. Record more of the comparison lines."
SCORE_FAILED = "The laptop couldn't score the recordings. Try Check again."
WORDS_DOWN = "JARVIS couldn't read your words to recognise just now. Try again in a minute."
LOST = "The laptop no longer has this session's recordings. Start a new session."
TOO_LONG = f"Each recording may last at most {CLIP_MAX_S} seconds."
NOT_AUDIO = "Send the recording as a base64 WAV."
NOT_RANKED = "Choose one of the engines the session compared."


class OwnWords(Protocol):
    """His "words to recognise" (R5's `VoiceSettings.phrases`, at most 50)."""

    async def read(self, uid: str) -> tuple[str, ...]: ...  # raises when it can't be read

    async def add(self, uid: str, words: tuple[str, ...]) -> tuple[str, ...]: ...  # those added


@dataclass(frozen=True)
class StartIn:
    yes: bool = False  # he typed YES to the ₹ question
    skip_google: bool = False  # compare without Google
    restart: bool = False  # a session in progress is replaced (its recordings deleted)
    words: tuple[str, ...] = ()  # new names and places, already cleaned


@dataclass(frozen=True)
class ClipDone:
    prompt_id: str
    seconds: float
    clips: int
    done: int
    total: int
    next: str | None
    compare: CompareMode


def _kit_error(exc: KitError) -> ProfileRefused:
    if isinstance(exc, KitUnavailable):
        return ProfileRefused(503, "laptop_unavailable", str(exc))
    if isinstance(exc, KitRefused) and exc.code == "not_found":
        return ProfileRefused(409, "laptop_lost", LOST)
    if isinstance(exc, KitRefused) and exc.code in ("busy", "engine_not_ready"):
        return ProfileRefused(503, "laptop_busy", exc.words)
    return ProfileRefused(422, "laptop_refused", str(exc))


def clean_heard(raw: object) -> str | None:
    """What the browser heard, as kept: plain text, at most `HEARD_CHARS` (None: not given)."""
    if not isinstance(raw, str):
        return None
    return " ".join(_CONTROL.sub(" ", raw).split())[:HEARD_CHARS]


def decode_wav(audio: object) -> bytes:
    if not isinstance(audio, str):
        raise ProfileRefused(422, "bad_audio", NOT_AUDIO)
    try:
        return base64.b64decode(audio, validate=True)
    except (binascii.Error, ValueError):
        raise ProfileRefused(422, "bad_audio", NOT_AUDIO) from None


@dataclass
class SessionParts:
    kit: KitClient | None  # None: no laptop kit configured here
    profiles: ProfileStore
    sessions: SessionStore
    google: GoogleEar | None
    words: OwnWords
    normalise: Normalise  # R18's `jarvis.calls.langcheck.scoring.normalise`
    compare_minutes: int = 20
    health_s: float = 30.0
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


class VoiceSessions:
    def __init__(self, parts: SessionParts) -> None:
        self.p = parts
        self.compare = Comparison(parts.google, minutes=parts.compare_minutes, now=parts.now)
        self._locks: dict[str, asyncio.Lock] = {}
        self._health: tuple[float, bool] | None = None

    def _lock(self, uid: str) -> asyncio.Lock:
        return self._locks.setdefault(uid, asyncio.Lock())

    def _kit(self) -> KitClient:
        if self.p.kit is None:
            raise ProfileRefused(503, "laptop_not_set_up", NO_KIT)
        return self.p.kit

    # ---- reading -----------------------------------------------------------------------------
    async def profile(self, uid: str) -> VoiceProfile:
        return await self.p.profiles.get(uid)

    async def current(self, uid: str) -> SessionDoc | None:
        return await self.p.sessions.get(uid)

    async def laptop_ready(self) -> bool:
        """The kit healthy for listening (cached `health_s`); never raises."""
        if self.p.kit is None:
            return False
        now = asyncio.get_running_loop().time()
        if self._health is not None and now - self._health[0] < self.p.health_s:
            return self._health[1]
        try:
            h = await self.p.kit.health()
            ok = h.compatible and not h.slow and h.engine_for(Kind.STT, ENGLISH) is not None
        except KitError:
            ok = False
        self._health = (now, ok)
        return ok

    async def wakeword_files(self) -> int:
        """The wake-word files trained from his recordings that the laptop holds (0 without a
        kit). A kit that can't answer raises: the dashboard then says it couldn't check."""
        if self.p.kit is None:
            return 0
        status = await self.p.kit.wakeword_status()
        return (status.verifier is not None) + (status.owned is not None)

    async def preview(self, uid: str) -> Compare:
        """What the comparison would be if he started now (no question asked)."""
        count = sum(scored(p) for p in build_prompts().prompts)
        return await self.compare.plan(count, yes=False, skip=False, ask=False)

    # ---- start ---------------------------------------------------------------------------------
    async def _healthy(self, kit: KitClient) -> None:
        try:
            h = await kit.health()
        except KitError as exc:
            raise _kit_error(exc) from None
        if not h.compatible:
            raise ProfileRefused(503, "laptop_outdated", OUTDATED)
        if h.engine_for(Kind.STT, ENGLISH) is None:
            raise ProfileRefused(503, "laptop_no_engine", NO_ENGINE)

    async def _answer(self, uid: str, doc: SessionDoc, req: StartIn) -> SessionDoc:
        """A session in progress: his answer to the mid-session ₹ question, if any."""
        if doc.state is not SessionState.RECORDING:
            return doc
        new = self.compare.answer(doc.compare, yes=req.yes, skip=req.skip_google)
        if new is None:
            return doc
        saved = await self.p.sessions.update(uid, lambda d: with_(d, compare=new))
        return saved or doc

    async def start(self, uid: str, req: StartIn) -> SessionDoc:
        async with self._lock(uid):
            kit = self._kit()
            await self._healthy(kit)
            cur = await self.p.sessions.get(uid)
            busy = (SessionState.RECORDING, SessionState.SCORING)
            if cur is not None and cur.state in busy and not req.restart:
                return await self._answer(uid, cur, req)
            try:
                own = await self.p.words.read(uid)
            except Exception:  # noqa: BLE001 - say so, start nothing
                log.warning("voice session: words unreadable")
                raise ProfileRefused(503, "words_unreadable", WORDS_DOWN) from None
            plan = build_prompts([*own, *req.words])
            count = sum(scored(p) for p in plan.prompts)
            compare = await self.compare.plan(count, yes=req.yes, skip=req.skip_google, ask=True)
            if cur is not None:
                await self._forget_clips(kit, cur.session_id)
            listed = {o.casefold() for o in own}
            doc = SessionDoc(
                session_id=new_session_id(),
                started_at=self.p.now(),
                prompts=plan.prompts,
                keys=plan.keys,
                own=tuple(sorted(plan.own)),
                typed=tuple(w for w in req.words if w.casefold() not in listed),
                compare=compare,
            )
            await self.p.sessions.save(uid, doc)
            await self.p.profiles.update(
                uid,
                lambda p: with_(
                    p,
                    state=SessionState.RECORDING,
                    session_id=doc.session_id,
                    clips=0,
                    compare_seconds=0.0,
                ),
            )
            log.info("voice session started", extra={"compare": compare.mode.value})
            return doc

    async def _forget_clips(self, kit: KitClient, session_id: str) -> None:
        try:
            await kit.delete(DeleteIn(session_id=session_id))
        except KitRefused as exc:
            if exc.code != "not_found":
                raise _kit_error(exc) from None
        except KitError as exc:
            raise _kit_error(exc) from None

    # ---- one clip ------------------------------------------------------------------------------
    async def _recording(self, uid: str) -> SessionDoc:
        doc = await self.p.sessions.get(uid)
        if doc is None or doc.state is not SessionState.RECORDING:
            raise ProfileRefused(409, "no_session", NO_SESSION)
        return doc

    async def _ask_first(self, uid: str, doc: SessionDoc) -> None:
        """Before Google could hear (and maybe price) a clip: the ₹ question, nothing stored."""
        asked = await self.compare.check(doc.compare)
        if asked is not None:
            await self.p.sessions.update(uid, lambda d: with_(d, compare=asked))
            raise needs_yes(asked)

    async def put_clip(
        self, uid: str, prompt_id: str, wav: bytes, browser_heard: object = None
    ) -> ClipDone:
        async with self._lock(uid):
            doc = await self._recording(uid)
            prompt = doc.prompt(prompt_id)
            if prompt is None:
                raise ProfileRefused(404, "no_such_prompt", NO_PROMPT)
            try:
                audio = parse_wav(wav)
            except BadAudio as exc:
                raise ProfileRefused(422, "bad_audio", str(exc)) from None
            if audio.seconds > CLIP_MAX_S:
                raise ProfileRefused(422, "bad_audio", TOO_LONG)
            compare = scored(prompt) and self.compare.hears(doc.compare)
            if compare:
                await self._ask_first(uid, doc)
            clip = ClipIn(
                session_id=doc.session_id,
                prompt_id=prompt_id,
                audio=encode_pcm(audio.pcm),
                kind=prompt.kind,
                held_out=prompt.held_out,
            )
            try:
                stored = await self._kit().put_clip(clip)
            except KitError as exc:
                raise _kit_error(exc) from None
            heard: GoogleHeard | None = None
            mode = doc.compare.mode
            if compare:
                heard, mode = await self.compare.hear(uid, wav, doc.compare.mode)
            said = clean_heard(browser_heard) if scored(prompt) else None
            new = await self.p.sessions.update(
                uid, lambda d: self._kept(d, prompt_id, compare, heard, mode, said)
            )
            new = new or doc
            await self.p.profiles.update(
                uid,
                lambda p: with_(p, clips=stored.clips, compare_seconds=new.compare.seconds),
            )
        return ClipDone(
            prompt_id=prompt_id,
            seconds=round(audio.seconds, 2),
            clips=stored.clips,
            done=len(new.done),
            total=len(new.prompts),
            next=new.next_prompt(),
            compare=new.compare.mode,
        )

    @staticmethod
    def _kept(
        d: SessionDoc,
        pid: str,
        compared: bool,
        heard: GoogleHeard | None,
        mode: CompareMode,
        said: str | None,
    ) -> SessionDoc:
        google, ms, browser = dict(d.google), dict(d.google_ms), dict(d.browser)
        google.pop(pid, None)
        ms.pop(pid, None)
        browser.pop(pid, None)
        cmp = d.compare
        if compared and heard is not None:
            google[pid] = heard.text[:HEARD_CHARS]
            if heard.ms is not None:
                ms[pid] = max(0, heard.ms)
            cmp = with_(cmp, clips=cmp.clips + 1, seconds=cmp.seconds + STEP_S)
        if said is not None:
            browser[pid] = said
        done = d.done if pid in d.done else (*d.done, pid)
        return with_(
            d,
            done=done,
            google=google,
            google_ms=ms,
            browser=browser,
            compare=with_(cmp, mode=mode),
        )

    # ---- scoring -------------------------------------------------------------------------------
    async def _phrases(self, uid: str) -> tuple[str, ...]:
        try:
            own = await self.p.words.read(uid)
        except Exception:  # noqa: BLE001 - scoring works without his words
            log.warning("voice session: words unreadable for scoring")
            return ()
        return tuple(w for w in own if 1 <= len(w) <= PHRASE_CHARS)[:50]

    async def _run_score(self, uid: str, doc: SessionDoc) -> SessionDoc:
        kit = self._kit()
        try:
            health = await kit.health()
            ready = {e.slot for e in health.engines if e.ready and ENGLISH in e.languages}
            slots = tuple(s for s in LAPTOP_SLOTS if s in ready)
            if not slots:
                raise ProfileRefused(503, "laptop_no_engine", NO_ENGINE)
            job = await kit.score(
                ScoreIn(session_id=doc.session_id, slots=slots, phrases=await self._phrases(uid))
            )
        except KitError as exc:
            raise _kit_error(exc) from None
        scoring = await self.p.sessions.update(
            uid, lambda d: with_(d, state=SessionState.SCORING, job_id=job.job_id, reason="")
        )
        await self.p.profiles.update(uid, lambda p: with_(p, state=SessionState.SCORING))
        doc = scoring or doc
        return await self._finish(uid, doc, job) if job.finished else doc

    async def score(self, uid: str) -> SessionDoc:
        async with self._lock(uid):
            doc = await self._recording(uid)
            heard = sum(1 for pid in doc.done if (p := doc.prompt(pid)) and scored(p))
            if heard < MIN_PROMPTS:
                raise ProfileRefused(409, "too_few", TOO_FEW)
            return await self._run_score(uid, doc)

    async def recheck(self, uid: str) -> SessionDoc:
        async with self._lock(uid):
            doc = await self.p.sessions.get(uid)
            profile = await self.p.profiles.get(uid)
            if doc is None or profile.clips == 0 or doc.state is SessionState.SCORING:
                if doc is not None and doc.state is SessionState.SCORING:
                    return doc
                raise ProfileRefused(409, "no_recordings", NO_RECORDINGS)
            return await self._run_score(uid, doc)

    async def poll(self, uid: str) -> tuple[SessionDoc | None, JobView | None]:
        """The session and, while the laptop scores it, its job (finished: the results)."""
        async with self._lock(uid):
            doc = await self.p.sessions.get(uid)
            if doc is None or doc.state is not SessionState.SCORING or doc.job_id is None:
                return doc, None
            try:
                job = await self._kit().job(doc.job_id)
            except KitRefused as exc:
                if exc.code != "not_found":
                    raise _kit_error(exc) from None
                return await self._failed(uid, doc, LOST), None
            except KitError as exc:
                raise _kit_error(exc) from None
            if not job.finished:
                return doc, job
            return await self._finish(uid, doc, job), job

    async def _failed(self, uid: str, doc: SessionDoc, words: str) -> SessionDoc:
        failed = await self.p.sessions.update(
            uid, lambda d: with_(d, state=SessionState.FAILED, reason=words, job_id=None)
        )
        await self.p.profiles.update(
            uid,
            lambda p: with_(p, state=SessionState.DONE if p.ranking else SessionState.FAILED),
        )
        return failed or doc

    def _heard(self, doc: SessionDoc, rows: Sequence[HeardRow]) -> list[Heard]:
        ids = {p.id for p in doc.prompts if scored(p)}
        heard: list[Heard] = []
        for r in rows:
            if r.prompt_id in ids and r.slot in LAPTOP_SLOTS:
                heard.append(Heard(engine_of_slot(r.slot), r.prompt_id, r.text, r.elapsed_ms))
        for pid, text in doc.browser.items():
            heard.append(Heard(ListenEngine.BROWSER, pid, text))
        for pid, text in doc.google.items():
            heard.append(Heard(ListenEngine.GOOGLE, pid, text, doc.google_ms.get(pid)))
        return heard

    async def _finish(self, uid: str, doc: SessionDoc, job: JobView) -> SessionDoc:
        if job.state is not JobState.DONE:
            return await self._failed(uid, doc, job.words or SCORE_FAILED)
        try:
            rows = (await self._kit().results(doc.session_id)).rows
        except KitError as exc:
            raise _kit_error(exc) from None
        heard = self._heard(doc, rows)
        ranking = score_engines(doc.prompts, doc.keys, heard, self.p.normalise)[:RANKING_MAX]
        chosen = choose(ranking)
        if chosen is None:
            return await self._failed(uid, doc, NOT_ENOUGH)
        corrections = learn_corrections(doc.prompts, [h for h in heard if h.engine is chosen])
        added = await self._join_words(uid, doc, corrections)
        at = self.p.now()
        await self.p.profiles.update(
            uid,
            lambda p: with_(
                p,
                state=SessionState.DONE,
                session_id=doc.session_id,
                chosen=chosen,
                ranking=ranking,
                corrections=corrections,
                measured_at=at,
                compare_seconds=doc.compare.seconds,
            ),
        )
        done = await self.p.sessions.update(
            uid,
            lambda d: with_(
                d, state=SessionState.DONE, scored_at=at, words_added=added, reason="", job_id=None
            ),
        )
        log.info(
            "voice session scored",
            extra={
                "engines": len(ranking),
                "chosen": chosen.value,
                "corrections": len(corrections),
            },
        )
        return done or doc

    async def _join_words(
        self, uid: str, doc: SessionDoc, corrections: tuple[Correction, ...]
    ) -> tuple[str, ...]:
        try:
            existing = await self.p.words.read(uid)
            fresh = new_words(corrections, doc.prompts, doc.typed, existing)
            return await self.p.words.add(uid, fresh) if fresh else ()
        except Exception:  # noqa: BLE001 - the results stand without the new words
            log.warning("voice session: new words not added")
            return ()

    # ---- his changes ---------------------------------------------------------------------------
    async def change_profile(
        self,
        uid: str,
        *,
        chosen: ListenEngine | None = None,
        corrections_on: bool | None = None,
        forget: str | None = None,
    ) -> VoiceProfile:
        """He picks another engine (one that was ranked, when there is a ranking), switches the
        corrections off or on, or forgets one correction (by what was heard)."""

        def change(p: VoiceProfile) -> VoiceProfile:
            changes: dict[str, object] = {}
            if chosen is not None:
                if p.ranking and chosen not in {s.engine for s in p.ranking}:
                    raise ProfileRefused(422, "not_ranked", NOT_RANKED)
                changes["chosen"] = chosen
            if corrections_on is not None:
                changes["corrections_on"] = corrections_on
            if forget is not None:
                key = " ".join(forget.split()).casefold()
                changes["corrections"] = tuple(c for c in p.corrections if c.heard != key)
            return with_(p, **changes) if changes else p

        return await self.p.profiles.update(uid, change)

    # ---- deleting --------------------------------------------------------------------------------
    @property
    def kit_set_up(self) -> bool:
        return self.p.kit is not None

    async def delete_recordings(self, uid: str, *, wakeword: bool = False) -> Deleted:
        """Every recording on the laptop (and, if asked, the wake-word files made from them), and
        the session's transcripts here. A kit that is set up must answer first: nothing is deleted
        while it can't be reached, so nothing claims to be gone that isn't. With no kit set up
        (the owner's decision, 28 Nov 2026) only the transcripts here go: the laptop's recordings
        are out of reach, so none is claimed gone and their count stays."""
        async with self._lock(uid):
            if self.p.kit is None:
                deleted, clips = Deleted(clips=0), None
            else:
                try:
                    deleted = await self.p.kit.delete(DeleteIn(session_id=None, wakeword=wakeword))
                except KitError as exc:
                    raise _kit_error(exc) from None
                clips = 0
            await self.p.sessions.delete(uid)
            await self.p.profiles.update(
                uid,
                lambda p: with_(
                    p,
                    clips=p.clips if clips is None else clips,
                    session_id=None,
                    state=SessionState.DONE if p.ranking else SessionState.NONE,
                ),
            )
            log.info(
                "voice recordings deleted",
                extra={"clips": deleted.clips, "laptop": clips is not None},
            )
            return deleted


__all__ = [
    "LAPTOP_SLOTS",
    "ClipDone",
    "GoogleEar",
    "GoogleHeard",
    "OwnWords",
    "SessionParts",
    "StartIn",
    "VoiceSessions",
    "clean_heard",
    "decode_wav",
]
