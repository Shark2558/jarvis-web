# src/jarvis/calls/join_speech.py
"""R18 I1: the call's speech and its rupees, joined (docs/plans/r18-integration/I1-NOTES.md).

**Metering in exactly one place.** B's adapters meter every hearing and voice through
`jarvis.billing` themselves (`speech.meter.SpeechMeter`: Google's shared free allowance gated and
charged, Azure F0's free tier held and never billed, Sarvam and Bhashini in rupees). A2's engine
also asks `Spend.speech` after each hearing and voice, to hold the call to its ₹ cap. So:

- one `CallTally` per call is the SpeechMeter's `on_cost` sink: what B charged, by part;
- `CallSpend.speech` hands the engine what the tally holds, and records NOTHING in billing (B
  already did; A2's own `BillingSpend.speech` is not used, or every Google second would count
  twice). A use whose price JARVIS does not know (B reports None, Bhashini) is counted for the
  call at Google's paid rate: never ₹0, though billing holds no rupees for it;
- `CallSpend.model` and `allowed` are A2's `BillingSpend` (the brain, captions, summary and line
  translations: the only place their ₹ is recorded).

**Which speech.** `SpeechChoices` reads the language table (the latest result per language and
option, `langcheck.select.choose`) for an owner before a call starts; `CallSpeech` (A2's
`SpeechKit`) serves that choice, and English before its first check (the Workshop's decision)
the first cloud option that is set up, Google first. A language with no option gets a stand-in
that refuses (`SpeechUnavailable`), which the engine treats as a failed line.

**The language check** (`LanguageCheckJob`): the estimate answers at once; a run (minutes) goes
to a background task, one at a time, and its progress is read from the results it writes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from jarvis.calls.engine_ports import Kind
from jarvis.calls.hub import BillingSpend
from jarvis.calls.langcheck.api import CheckRequest, handle_score, plan_view
from jarvis.calls.langcheck.runner import CheckPlan, LanguageCheck
from jarvis.calls.langcheck.select import choose, latest
from jarvis.calls.models import ENGLISH, CallSettings, SpeechOption
from jarvis.calls.ports import (
    CallsRefused,
    CallStore,
    Hearing,
    LanguageDetector,
    SpeechUnavailable,
    Voice,
)
from jarvis.calls.prices import PriceUnknown, SpeechPrice
from jarvis.calls.speech.build import SpeechOptions
from jarvis.calls.speech.catalogue import AZURE, GOOGLE, SARVAM, hears, speaks
from jarvis.calls.speech.detect import detector_for
from jarvis.llm.base import Completion
from jarvis.logging import get_logger

log = get_logger(__name__)

CLOUD_FALLBACK = (GOOGLE, AZURE)  # English before its check, and a voice for "unsupported"
NATIVE_DETECT = frozenset({GOOGLE, SARVAM})  # they detect inside `transcribe` (alternatives)
PART = {"hear": "hearing", "voice": "voice"}


# ---- the rupees of one call --------------------------------------------------------------------
class CallTally:
    """B's `SpeechMeter.on_cost` for one call: the ₹ each part cost, until the engine takes it."""

    def __init__(self) -> None:
        self._inr: dict[str, float] = {"hearing": 0.0, "voice": 0.0}
        self._unknown: dict[str, int] = {"hearing": 0, "voice": 0}

    def __call__(self, part: str, inr: float | None) -> None:
        key = part if part in self._inr else "hearing"
        if inr is None:
            self._unknown[key] += 1
        elif inr > 0:
            self._inr[key] += inr

    def take(self, part: str) -> tuple[float, int]:
        inr, unknown = self._inr.get(part, 0.0), self._unknown.get(part, 0)
        self._inr[part], self._unknown[part] = 0.0, 0
        return inr, unknown


PriceTable = Callable[[float], Mapping[SpeechOption, SpeechPrice]]


class CallSpend:
    """A2's `Spend` for one call (see the module docstring: speech is never recorded here)."""

    def __init__(self, base: BillingSpend, tally: CallTally, prices: PriceTable, rate: Any) -> None:
        self._base, self._tally, self._prices, self._rate = base, tally, prices, rate

    async def model(self, uid: str, brain_id: str, completion: Completion) -> float:
        return await self._base.model(uid, brain_id, completion)

    async def allowed(self, uid: str) -> bool:
        return await self._base.allowed(uid)

    async def speech(self, uid: str, option: str, kind: Kind, units: float) -> float:
        inr, unknown = self._tally.take(PART[kind])
        if unknown and units > 0:
            inr += await self._stand_in(kind, units)
        return round(inr, 6)

    async def _stand_in(self, kind: Kind, units: float) -> float:
        """A use B could not price, counted for the call's cap at Google's paid rate."""
        try:
            google = self._prices(float(await self._rate()))[SpeechOption.GOOGLE]
            per = google.inr_per_minute() / 60 if kind == "hear" else google.inr_per_chars(1)
        except (PriceUnknown, KeyError, ValueError):
            return 0.0
        return per * units


# ---- which option speaks and hears each language ------------------------------------------------
class SpeechChoices:
    """The language table's choice per language for each owner, read before a call."""

    def __init__(self, store: CallStore) -> None:
        self._store = store
        self._chosen: dict[str, dict[str, str]] = {}
        self._balanced: dict[str, frozenset[str]] = {}
        self._languages: dict[str, tuple[str, ...]] = {}

    async def refresh(self, uid: str, languages: Sequence[str] | None = None) -> None:
        """Before a call: its languages (None: his defaults, for an answered call)."""
        try:
            settings = await self._store.settings(uid)
            results = latest(await self._store.language_results())
        except Exception as exc:  # noqa: BLE001 - the call goes on with the last table read
            log.warning("language table unreadable", extra={"error": type(exc).__name__})
            self._languages[uid] = tuple(languages or (ENGLISH,))
            return
        self._languages[uid] = tuple(languages or settings.default_languages or (ENGLISH,))
        chosen: dict[str, str] = {}
        balanced: set[str] = set()
        for lang in {r_lang for r_lang, _ in results}:
            r = choose(
                results, lang, sarvam_on=settings.sarvam_on, allow_balanced=settings.allow_balanced
            )
            if r is not None:
                chosen[lang] = r.option.value
                if r.needs_balanced:
                    balanced.add(lang)
        self._chosen[uid], self._balanced[uid] = chosen, frozenset(balanced)

    def snapshot(self, uid: str) -> tuple[dict[str, str], frozenset[str], tuple[str, ...]]:
        """(language -> option, the languages needing the balanced tier, the call's languages)."""
        return (
            dict(self._chosen.get(uid, {})),
            self._balanced.get(uid, frozenset()),
            self._languages.get(uid, (ENGLISH,)),
        )


class _NoHearing:
    def __init__(self, lang: str) -> None:
        self.name, self._lang = "none", lang

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Any:
        raise SpeechUnavailable(f"no hearing option for {self._lang}")


class _NoVoice:
    def __init__(self, lang: str) -> None:
        self.name, self._lang = "none", lang

    async def speak(self, text: str, lang: str) -> bytes:
        raise SpeechUnavailable(f"no voice option for {self._lang}")


class CallSpeech:
    """A2's `SpeechKit` for one call: the checked option per language, else the cloud fallback."""

    def __init__(
        self,
        options: SpeechOptions,
        chosen: Mapping[str, str],
        balanced: frozenset[str] = frozenset(),
        languages: Sequence[str] = (ENGLISH,),
    ) -> None:
        self._options, self._chosen, self._balanced = options, dict(chosen), balanced
        self._languages = tuple(languages) or (ENGLISH,)

    def _pick(self, lang: str, built: Mapping[str, Any], fits: Callable[[str, str], bool]) -> Any:
        option = self._chosen.get(lang)
        if option is not None and option in built:
            return built[option]
        for fallback in CLOUD_FALLBACK:
            if fallback in built and fits(fallback, lang):
                return built[fallback]
        return None

    def hearing(self, lang: str) -> Hearing:
        found: Hearing | None = self._pick(lang, self._options.hearing, hears)
        return found if found is not None else _NoHearing(lang)

    def voice(self, lang: str) -> Voice:
        found: Voice | None = self._pick(lang, self._options.voices, speaks)
        return found if found is not None else _NoVoice(lang)

    def detector(self) -> LanguageDetector | None:
        """None when the call has one language or its hearing detects inside `transcribe`
        (Google's alternatives: one request, not two); else B's try-each detector."""
        if len(self._languages) < 2:
            return None
        hearing = self.hearing(self._languages[0])
        if hearing.name in NATIVE_DETECT or isinstance(hearing, _NoHearing):
            return None
        return detector_for(hearing)

    def needs_balanced(self, lang: str) -> bool:
        return lang in self._balanced


# ---- the language check, in the background -------------------------------------------------------
MakeCheck = Callable[[str, CallSettings], Awaitable[LanguageCheck]]
MSG_RUNNING = "A language check is already running: its progress is in the language table."


@dataclass
class CheckProgress:
    running: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    pairs: tuple[tuple[str, str], ...] = ()
    skipped: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def view(self, done: int) -> dict[str, Any]:
        return {
            "running": self.running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total": len(self.pairs),
            "done": min(done, len(self.pairs)),
            "skipped": dict(self.skipped),
            "error": self.error,
        }


def _runs(plan: CheckPlan, accept_unknown: bool) -> tuple[tuple[str, str], ...]:
    return tuple((p.lang, p.option) for p in plan.running if p.inr is not None or accept_unknown)


class LanguageCheckJob:
    """`POST /v1/calls/languages/check`: the estimate at once; a run in the background."""

    def __init__(
        self,
        make: MakeCheck,
        store: CallStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._make, self._store, self._clock = make, store, clock
        self.progress = CheckProgress()
        self._task: asyncio.Task[None] | None = None

    async def done(self) -> int:
        p = self.progress
        if p.started_at is None or not p.pairs:
            return 0
        try:
            results = await self._store.language_results()
        except Exception:  # noqa: BLE001 - progress is a view: unknown is 0
            return 0
        want = set(p.pairs)
        return len(
            {
                (r.lang, r.option.value)
                for r in results
                if (r.lang, r.option.value) in want and r.checked_at >= p.started_at
            }
        )

    async def view(self) -> dict[str, Any]:
        return self.progress.view(await self.done())

    async def handle(self, uid: str, body: Mapping[str, Any]) -> dict[str, Any]:
        try:
            req = CheckRequest.model_validate(dict(body))
        except ValidationError as exc:
            fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
            words = f"Check these fields: {', '.join(fields) or 'the request'}."
            raise CallsRefused(422, "bad_request", words) from None
        settings = await self._store.settings(uid)
        check = await self._make(uid, settings)
        options = [o.value for o in req.options] if req.options is not None else None
        try:
            plan = await check.plan(req.languages, options)
        except ValueError as exc:
            raise CallsRefused(422, "bad_request", str(exc)) from None
        if req.estimate_only:
            return {"plan": plan_view(plan), "check": await self.view()}
        if self.progress.running:
            raise CallsRefused(409, "check_running", MSG_RUNNING)
        if plan.total_inr > req.accept_inr + 0.005:
            words = (
                f"This check would cost about ₹{plan.total_inr:.2f}. Confirm that amount to run "
                "it, or check the free options only."
            )
            raise CallsRefused(409, "check_refused", words)
        self._start(check, plan, req)
        return {"plan": plan_view(plan), "check": await self.view()}

    async def score(self, uid: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """The owner's 1-5 scores of a language's samples (`langcheck.api.handle_score`)."""
        check = await self._make(uid, await self._store.settings(uid))
        return await handle_score(check, body)

    def _start(self, check: LanguageCheck, plan: CheckPlan, req: CheckRequest) -> None:
        self.progress = CheckProgress(
            running=True, started_at=self._clock(), pairs=_runs(plan, req.accept_unknown)
        )

        async def run() -> None:
            try:
                report = await check.run(
                    plan, accept_inr=req.accept_inr, accept_unknown=req.accept_unknown
                )
                self.progress.skipped = dict(report.skipped)
            except Exception as exc:  # noqa: BLE001 - said in the table, logged by name
                log.error("language check failed", extra={"error": type(exc).__name__})
                self.progress.error = "The language check stopped early. Try it again later."
            finally:
                self.progress.running = False
                self.progress.finished_at = self._clock()

        self._task = asyncio.ensure_future(run())

    async def aclose(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()


__all__ = [
    "CallSpeech",
    "CallSpend",
    "CallTally",
    "CheckProgress",
    "LanguageCheckJob",
    "SpeechChoices",
]
