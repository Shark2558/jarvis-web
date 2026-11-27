# src/jarvis/calls/langcheck/runner.py
"""The language check (R18 B; plan 5.3): the gate every call language passes, per option.

`plan` first, always: which language × option pairs would run and their ₹ (no request is sent).
Free first: the laptop and Azure F0 are ₹0 (F0 cannot bill: a pair it has no allowance left for
does not run), Google is ₹0 inside the shared free allowance left this month (planned use counted
across the languages) and priced past it, Bhashini's price is unknown unless set (run only with
`accept_unknown`), Sarvam runs only when the owner turned it on, at its ₹. `run` refuses
(`CheckRefused`, plain words) a plan whose ₹ is above what the owner accepted (`accept_inr`, ₹0
by default): inside the free allowances nothing needs accepting.

For each language, `run` then:

1. fetches ~20 FLEURS clips (`fleurs`; no network: that language is not checked, said plainly)
   and turns each into phone-quality audio (`speech.phoneline`: 8 kHz, G.711 mu-law);
2. hearing: each option that hears the language transcribes every clip, scored for key facts and
   character error rate (`scoring`);
3. voice: each option that speaks it says the 10 call sentences (`sentences`), each through the
   phone line and heard back by a DIFFERENT hearing option, the first whose own hearing passed
   (else the first that heard anything; the same option only when no other exists, and the
   result says so), scored for key facts;
4. speed: reply starts = the option's own hearing of those short call-like turns (timed; a FLEURS
   clip is 10-15 s, a turn far shorter) + the desk's end-of-turn wait (END_OF_TURN_S) + the
   brain's first sentence (`BrainProbe`, else BRAIN_ESTIMATE_S, said so in `versions`) + the
   voice's time for the sentence;
5. writes one `LanguageResult` per language and option (`CallStore.put_language_result`), with
   the owner's earlier score of a sample kept, and `passed` / `why_failed` from `select.verdict`.

An option counts as a unit (its own hearing, voice and speed), as the language table shows it.
Requests go one at a time (F0 takes one at a time; the free allowances are spent slowly) and one
check runs at a time. A request that fails counts as a miss; MAX_ERRORS in a row, a used-up free
tier or a paid option switched off end that option's part. Nothing logs audio or transcripts.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol

from jarvis.calls.langcheck.fleurs import CLIPS, SOURCE, Clip, ClipSource, FleursUnavailable
from jarvis.calls.langcheck.scoring import (
    ClipScore,
    hearing_verdict,
    human_verdict,
    score_clip,
    speed_verdict,
    voice_verdict,
)
from jarvis.calls.langcheck.select import latest, verdict
from jarvis.calls.langcheck.sentences import ENGLISH_SENTENCES, Sentence, SentenceSource
from jarvis.calls.models import LanguageResult, SpeechOption
from jarvis.calls.ports import CallStore, Hearing, Voice
from jarvis.calls.prices import PriceUnknown, SpeechPrice
from jarvis.calls.speech.build import SpeechOptions
from jarvis.calls.speech.catalogue import (
    AZURE,
    GOOGLE,
    LANGUAGES,
    OPTION_ORDER,
    SARVAM,
    hears,
    speaks,
)
from jarvis.calls.speech.errors import AllowanceUsedUp, NotOffered, PaidOptionOff, SpeechError
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.speech.phoneline import phone_line
from jarvis.calls.speech.translate import TranslationRefused
from jarvis.logging import get_logger
from jarvis.voice.catalogue import STT_KEY, TTS_KEYS

log = get_logger(__name__)

END_OF_TURN_S = 0.3  # the desk's voice detector: silence before a turn ends
BRAIN_ESTIMATE_S = 0.6  # the fast tier's first sentence, when no probe measured it
AVG_CLIP_S = 12.0  # FLEURS test clips: ~10-15 s
AVG_SENTENCE_S = 3.5
AVG_SENTENCE_CHARS = 60
HEAR_SHARE = 0.5  # in a call they speak about half the time (only then is audio sent)
VOICE_CHARS_PER_MINUTE = 150
MAX_ERRORS = 3
_STOP = (AllowanceUsedUp, PaidOptionOff, NotOffered)
ENGINES: Mapping[str, str] = {
    "laptop": "the call desk's models",
    GOOGLE: "Speech-to-Text v1 latest_short; Chirp 3: HD Algieba",
    AZURE: "short-audio REST; neural voices (F0)",
    "bhashini": "ULCA pipeline (MeitY)",
    SARVAM: "saaras:v4; bulbul:v3 shubh",
}


class CheckRefused(RuntimeError):
    """The check did not run (its ₹ not accepted, or one is already running): plain words."""


class BrainProbe(Protocol):
    async def reply_seconds(self, lang: str) -> float: ...


@dataclass(frozen=True)
class PairPlan:
    lang: str
    option: str
    hear: bool
    speak: bool
    hear_seconds: float = 0.0
    voice_chars: int = 0
    inr: float | None = 0.0  # None: price unknown
    runs: bool = True
    why: str = ""  # why it does not run


@dataclass(frozen=True)
class CheckPlan:
    pairs: tuple[PairPlan, ...]

    @property
    def running(self) -> tuple[PairPlan, ...]:
        return tuple(p for p in self.pairs if p.runs)

    @property
    def total_inr(self) -> float:
        return round(sum(p.inr or 0.0 for p in self.running), 2)

    @property
    def unknown(self) -> tuple[PairPlan, ...]:
        return tuple(p for p in self.running if p.inr is None)


@dataclass
class CheckReport:
    results: list[LanguageResult] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # "lang option" -> why


def call_minute_inr(price: SpeechPrice) -> float | None:
    """A call minute's speech past any free allowance (None: unknown, never ₹0)."""
    try:
        return round(
            price.inr_per_minute() * HEAR_SHARE + price.inr_per_chars(VOICE_CHARS_PER_MINUTE), 4
        )
    except PriceUnknown:
        return None


@dataclass
class _Free:
    """Free units left this month, as the plan spends them language by language."""

    left: dict[str, float] = field(default_factory=dict)

    def take(self, key: str, need: float) -> float:
        """The part of `need` the allowance does not cover (priced or, for F0, not possible)."""
        have = self.left.get(key, 0.0)
        used = min(have, need)
        self.left[key] = have - used
        return need - used


class LanguageCheck:
    def __init__(
        self,
        *,
        speech: SpeechOptions,
        store: CallStore,
        clips: ClipSource,
        sentences: SentenceSource,
        meter: SpeechMeter,
        prices: Mapping[SpeechOption, SpeechPrice],
        sarvam_on: bool,
        probe: BrainProbe | None = None,
        clock: Callable[[], float] = time.perf_counter,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.speech = speech
        self.store = store
        self.clips = clips
        self.sentences = sentences
        self.meter = meter
        self.prices = prices
        self.sarvam_on = sarvam_on
        self.probe = probe
        self._clock = clock
        self._now = now
        self._lock = asyncio.Lock()

    # ---- the plan and its ₹ ----------------------------------------------------------------------

    async def _free(self) -> _Free:
        g, a = self.prices[SpeechOption.GOOGLE], self.prices[SpeechOption.AZURE]
        keys = {
            STT_KEY: (GOOGLE, float(g.hear_free_seconds)),
            TTS_KEYS["chirp3-hd"]: (GOOGLE, float(g.voice_free_chars)),
            "azure_stt_seconds": (AZURE, float(a.hear_free_seconds)),
            "azure_tts_chars": (AZURE, float(a.voice_free_chars)),
        }
        free = _Free()
        for key, (option, units) in keys.items():
            free.left[key] = await self.meter.left(option, key, units)
        return free

    def _pair(self, lang: str, option: str) -> PairPlan | None:
        hear = hears(option, lang)
        speak = speaks(option, lang)
        if not hear and not speak:
            return None
        if option == SARVAM and not self.sarvam_on:
            return PairPlan(lang, option, hear, speak, runs=False, why=str(PaidOptionOff(SARVAM)))
        if option not in self.speech.hearing and option not in self.speech.voices:
            why = self.speech.missing.get(option, "not set up")
            return PairPlan(lang, option, hear, speak, runs=False, why=why)
        hear = hear and option in self.speech.hearing
        speak = speak and option in self.speech.voices
        seconds = (CLIPS * AVG_CLIP_S + len(ENGLISH_SENTENCES) * AVG_SENTENCE_S) if hear else 0.0
        chars = len(ENGLISH_SENTENCES) * AVG_SENTENCE_CHARS if speak else 0
        return PairPlan(lang, option, hear, speak, seconds, chars)

    def _language_plan(
        self, lang: str, options: Sequence[str] | None, free: _Free
    ) -> list[PairPlan]:
        """One language's pairs, priced. A hearing option may judge every other option's voice:
        each is counted on its hearing seconds (the upper bound, the safe side for the ₹)."""
        pairs = [
            p
            for option in OPTION_ORDER
            if options is None or option in options
            if (p := self._pair(lang, option)) is not None
        ]
        voices = sum(1 for p in pairs if p.runs and p.speak)
        judged = len(ENGLISH_SENTENCES) * AVG_SENTENCE_S
        return [
            self._priced(
                replace(p, hear_seconds=p.hear_seconds + judged * (voices - p.speak)), free
            )
            if p.runs and p.hear
            else (self._priced(p, free) if p.runs else p)
            for p in pairs
        ]

    def _priced(self, p: PairPlan, free: _Free) -> PairPlan:
        price = self.prices[SpeechOption(p.option)]
        if p.option == GOOGLE:
            seconds = free.take(STT_KEY, p.hear_seconds)
            chars = free.take(TTS_KEYS["chirp3-hd"], float(p.voice_chars))
        elif p.option == AZURE:
            short_s = free.take("azure_stt_seconds", p.hear_seconds)
            short_c = free.take("azure_tts_chars", float(p.voice_chars))
            if short_s or short_c:
                why = "Azure's free allowance left this month is not enough for this check"
                return replace(p, runs=False, why=why)
            return p
        else:
            seconds, chars = p.hear_seconds, float(p.voice_chars)
        if not price.can_bill:
            return p
        try:
            inr = (seconds / 60) * price.inr_per_minute() if seconds else 0.0
            inr += price.inr_per_chars(round(chars)) if chars else 0.0
        except PriceUnknown:
            return replace(p, inr=None)
        return replace(p, inr=round(inr, 2))

    async def plan(self, langs: Sequence[str], options: Sequence[str] | None = None) -> CheckPlan:
        unknown = [x for x in langs if x not in LANGUAGES]
        if unknown or not langs:
            raise ValueError("unknown call language" if unknown else "no language to check")
        free = await self._free()
        pairs = [
            p for lang in dict.fromkeys(langs) for p in self._language_plan(lang, options, free)
        ]
        return CheckPlan(tuple(pairs))

    # ---- the run ---------------------------------------------------------------------------------

    async def run(
        self, plan: CheckPlan, *, accept_inr: float = 0.0, accept_unknown: bool = False
    ) -> CheckReport:
        if plan.total_inr > accept_inr + 0.005:
            raise CheckRefused(
                f"This check would cost about ₹{plan.total_inr:.2f}. Confirm that amount to run "
                "it, or check the free options only."
            )
        if self._lock.locked():
            raise CheckRefused("A language check is already running.")
        async with self._lock:
            report = CheckReport()
            for p in plan.pairs:
                if not p.runs:
                    report.skipped[f"{p.lang} {p.option}"] = p.why
                elif p.inr is None and not accept_unknown:
                    report.skipped[f"{p.lang} {p.option}"] = "its price is not known"
            todo = [p for p in plan.running if p.inr is not None or accept_unknown]
            for lang in dict.fromkeys(p.lang for p in todo):
                pairs = [p for p in todo if p.lang == lang]
                report.results.extend(await self._language(lang, pairs))
            return report

    async def _inputs(self, lang: str, pairs: Sequence[PairPlan]) -> _Inputs:
        try:
            clean = await self.clips.clips(lang)
            clips, clips_why = [Clip(c.lang, c.text, phone_line(c.pcm)) for c in clean], None
        except FleursUnavailable as exc:
            clips, clips_why = [], str(exc)
        try:
            sentences, sent_why = await self.sentences.sentences(lang), None
        except TranslationRefused as exc:
            sentences, sent_why = [], f"the call sentences could not be translated ({exc})"
        brain_s, brain_note = await self._brain_s(lang)
        before = latest(await self.store.language_results())
        return _Inputs(
            tuple(clips), clips_why, tuple(sentences), sent_why, brain_s, brain_note,
            tuple(pairs), before,
        )  # fmt: skip

    async def _brain_s(self, lang: str) -> tuple[float, str]:
        if self.probe is None:
            return BRAIN_ESTIMATE_S, f"fast tier, estimated {BRAIN_ESTIMATE_S} s"
        try:
            return await self.probe.reply_seconds(lang), "fast tier, measured"
        except Exception as exc:  # noqa: BLE001 — a probe failure only costs the measurement
            log.warning("brain probe failed", extra={"why": type(exc).__name__})
            return BRAIN_ESTIMATE_S, f"fast tier, estimated {BRAIN_ESTIMATE_S} s"

    async def _language(self, lang: str, pairs: Sequence[PairPlan]) -> list[LanguageResult]:
        x = await self._inputs(lang, pairs)
        notes: dict[str, list[str]] = {p.option: [] for p in pairs}
        heard = {p.option: await self._hearing_part(p, x, notes[p.option]) for p in pairs}
        judges = _judges(pairs, heard)
        out = []
        for p in pairs:
            versions = {"engine": ENGINES.get(p.option, p.option), "brain": x.brain_note}
            versions["clips"] = SOURCE
            spoke = await self._voice_part(p, x, judges, heard[p.option], notes[p.option], versions)
            r = self._result(p, x, heard[p.option], spoke, notes[p.option], versions)
            await self.store.put_language_result(r)
            out.append(r)
            log.info("language checked", extra={"lang": lang, "option": p.option, "ok": r.passed})
        return out

    async def _hear(self, hearing: Hearing, lang: str, clips: Sequence[Clip]) -> _Part:
        part = _Part()
        for clip in clips:
            t0 = self._clock()
            try:
                heard = await hearing.transcribe(clip.pcm, [lang])
            except SpeechError as exc:
                part.miss(score_clip(clip.text, ""), str(exc))
                if isinstance(exc, _STOP) or part.in_a_row >= MAX_ERRORS:
                    break
                continue
            part.hit(score_clip(clip.text, heard.text), self._clock() - t0)
        return part

    async def _timed(self, hearing: Hearing, pcm: bytes, lang: str) -> tuple[str, float] | None:
        t0 = self._clock()
        try:
            heard = await hearing.transcribe(pcm, [lang])
        except SpeechError:
            return None
        return heard.text, self._clock() - t0

    async def _speak(
        self, voice: Voice, judge: Hearing, own: Hearing | None, lang: str, x: _Inputs
    ) -> _Part:
        """Each sentence spoken, phone-simulated, heard back by `judge` (scored) and, for the
        speed, by the option's `own` hearing (timed on a short call-like turn)."""
        part = _Part()
        for s in x.sentences:
            t0 = self._clock()
            try:
                pcm = phone_line(await voice.speak(s.text, lang))
            except SpeechError as exc:
                part.miss(score_clip(s.text, "", s.facts), str(exc))
                if isinstance(exc, _STOP) or part.in_a_row >= MAX_ERRORS:
                    break
                continue
            took = self._clock() - t0
            judged = await self._timed(judge, pcm, lang)
            if judged is None:  # the judge's failure, not the voice's: not counted
                part.notes.append("a sentence could not be heard back")
                continue
            part.hit(score_clip(s.text, judged[0], s.facts), took)
            mine = judged if own is judge else (await self._timed(own, pcm, lang) if own else None)
            if mine is not None:
                part.hear_times.append(mine[1])
        return part

    async def _hearing_part(self, p: PairPlan, x: _Inputs, notes: list[str]) -> _Part:
        hearing = self.speech.hearing.get(p.option) if p.hear else None
        if not p.hear:
            notes.append(f"{p.option} does not hear this language")
        elif x.clips_why:
            notes.append(x.clips_why)
        if hearing is None or not x.clips:
            return _Part()
        return await self._hear(hearing, p.lang, x.clips)

    async def _voice_part(
        self,
        p: PairPlan,
        x: _Inputs,
        judges: Sequence[str],
        heard: _Part,
        notes: list[str],
        versions: dict[str, str],
    ) -> _Part:
        voice = self.speech.voices.get(p.option) if p.speak else None
        # its own hearing times its replies' turns, if it heard anything at all (not used up)
        works = bool(heard.times) or not heard.scores
        own = self.speech.hearing.get(p.option) if p.hear and works else None
        name = next((j for j in judges if j != p.option), p.option if own else None)
        judge = self.speech.hearing.get(name) if name else None
        if not p.speak:
            notes.append(f"{p.option} has no voice for this language")
        elif x.sent_why:
            notes.append(x.sent_why)
        elif judge is None:
            notes.append("no hearing option to hear the voice back")
        if voice is None or judge is None or x.sent_why:
            return _Part()
        same = " (the same option: no other hears this language)" if name == p.option else ""
        versions["heard_back_by"] = f"{name}{same}"
        return await self._speak(voice, judge, own, p.lang, x)

    def _result(
        self,
        p: PairPlan,
        x: _Inputs,
        heard: _Part,
        spoke: _Part,
        notes: list[str],
        versions: dict[str, str],
    ) -> LanguageResult:
        hv, vv = hearing_verdict(heard.scores), voice_verdict(spoke.scores)
        if heard.scores and hv.facts_rate is None:
            notes.append("hearing: " + hv.why)
        notes += [*heard.notes[:2], *spoke.notes[:2]]
        sv = speed_verdict(_speeds(spoke.hear_times, spoke.times, x.brain_s))
        prev = x.before.get((p.lang, p.option))
        result = LanguageResult(
            lang=p.lang,
            option=SpeechOption(p.option),
            checked_at=self._now(),
            hear_facts=hv.facts_rate if heard.scores else None,
            cer=hv.cer if heard.scores else None,
            speak_facts=vv.facts_rate if spoke.scores else None,
            human_score=prev.human_score if prev else None,
            native_heard=prev.native_heard if prev else False,
            p50_ms=round(sv.p50 * 1000) if sv.p50 is not None else None,
            p90_ms=round(sv.p90 * 1000) if sv.p90 is not None else None,
            brain_ok=prev.brain_ok if prev else None,
            needs_balanced=prev.needs_balanced if prev else False,
            inr_per_minute=call_minute_inr(self.prices[SpeechOption(p.option)]),
            versions=versions,
        )
        passed, reasons = verdict(result)
        why = () if passed else tuple(dict.fromkeys([*notes, *reasons]))
        return result.model_copy(update={"passed": passed, "why_failed": why})

    # ---- the owner's score of a sample -----------------------------------------------------------

    async def score(self, lang: str, option: str, scores: Sequence[int]) -> LanguageResult:
        """The owner (or a native speaker he asked) scored samples heard over a real call."""
        if human_verdict(scores) is None:
            raise ValueError("Score at least one sample, 1 to 5.")
        r = latest(await self.store.language_results()).get((lang, option))
        if r is None:
            raise LookupError("That language and option have not been checked yet.")
        scored = r.model_copy(
            update={"human_score": round(sum(scores) / len(scores), 2), "native_heard": True}
        )
        passed, reasons = verdict(scored)
        kept = scored.model_copy(update={"passed": passed, "why_failed": () if passed else reasons})
        await self.store.put_language_result(kept)
        return kept


@dataclass(frozen=True)
class _Inputs:
    """One language's test material, shared by its options."""

    clips: tuple[Clip, ...]
    clips_why: str | None
    sentences: tuple[Sentence, ...]
    sent_why: str | None
    brain_s: float
    brain_note: str
    pairs: tuple[PairPlan, ...]
    before: Mapping[tuple[str, str], LanguageResult]


@dataclass
class _Part:
    scores: list[ClipScore] = field(default_factory=list)
    times: list[float] = field(default_factory=list)  # the request's own time
    hear_times: list[float] = field(default_factory=list)  # voice part: own hearing, short turns
    notes: list[str] = field(default_factory=list)
    in_a_row: int = 0

    def hit(self, score: ClipScore, seconds: float) -> None:
        self.scores.append(score)
        self.times.append(seconds)
        self.in_a_row = 0

    def miss(self, score: ClipScore, why: str) -> None:
        self.scores.append(score)
        self.in_a_row += 1
        if why not in self.notes:
            self.notes.append(why)


def _judges(pairs: Sequence[PairPlan], heard: Mapping[str, _Part]) -> list[str]:
    """The hearing options that may judge a voice: those whose hearing passed first, then those
    that heard anything, then (no clips to check them on) any that hears the language; each group
    in the check's order. One whose every request failed never judges."""
    passed = [p.option for p in pairs if heard[p.option].scores and _hearing_ok(heard[p.option])]
    some = [p.option for p in pairs if heard[p.option].times and p.option not in passed]
    untried = [p.option for p in pairs if p.hear and not heard[p.option].scores]
    return passed + some + untried


def _hearing_ok(part: _Part) -> bool:
    return hearing_verdict(part.scores).passed


def _speeds(hear: Sequence[float], voice: Sequence[float], brain_s: float) -> list[float]:
    """Reply starts: each hearing time with a voice time (cycled), the turn's wait, the brain."""
    if not hear or not voice:
        return []
    n = max(len(hear), len(voice))
    return [hear[i % len(hear)] + END_OF_TURN_S + brain_s + voice[i % len(voice)] for i in range(n)]


__all__ = [
    "BRAIN_ESTIMATE_S",
    "END_OF_TURN_S",
    "MAX_ERRORS",
    "BrainProbe",
    "CheckPlan",
    "CheckRefused",
    "CheckReport",
    "LanguageCheck",
    "PairPlan",
    "call_minute_inr",
]
