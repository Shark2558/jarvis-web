# evals/calls_language/suites.py
"""R18 B mock suites for the language check (plan 5.3): no network, no vendor, no model.

  scoring    the bars at their edges (90 % facts, 15 % CER, 90 % voice facts, the speed shares,
             a person's 4 of 5) and the normaliser on Indian scripts. Control: the bars switched
             off MUST fail it.
  phoneline  narrowband G.711: speech frequencies kept, what a phone can't carry cut, the codec's
             known codes. Control: a "phone line" that changes nothing MUST fail it.
  selection  the first passing option in the order laptop → Google → Azure → Bhashini → Sarvam
             (only when on), the balanced tier only with his YES, a stored pass re-read against
             the bars. Control: the order reversed MUST fail it.
  free_first the app's own choice (`cards.offered`, R18 review): Google while its free allowance
             covers the call, then the cheapest paid option he allows, Sarvam never when off,
             Azure's free tier before paid, an unknown price last. Control: ranking by list
             price alone (before the review's fix) MUST fail it.
  check      the whole check on scripted options: a clean language passes and is stored, lost
             numbers / slow replies / no clips / a low score fail with plain words, a different
             option hears the voice back, a paid plan is refused before any ₹, Sarvam off is not
             run. Control: the ₹ gate bypassed MUST fail it.
Every gate is hard (100 %).
"""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable
from typing import Any

import harness as h
import numpy as np

from jarvis.calls.cards import Estimator, offered
from jarvis.calls.langcheck import runner, scoring, select
from jarvis.calls.langcheck.runner import CheckRefused, LanguageCheck
from jarvis.calls.langcheck.scoring import ClipScore
from jarvis.calls.models import CallSettings, LanguageResult, SpeechOption
from jarvis.calls.prices import SpeechPrice
from jarvis.calls.speech import phoneline
from jarvis.calls.speech.audio import SAMPLE_RATE, from_float, to_float
from jarvis.calls.speech.catalogue import OPTION_ORDER

Case = tuple[str, str, Callable[[], Awaitable[list[str]]]]  # id, why, -> failures


def _report(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(r["passed"] for r in results)
    rate = passed / len(results) if results else 0.0
    return {"cases": len(results), "pass_rate": rate, "gate": rate == 1.0, "results": results}


async def _run(cases: list[Case]) -> dict[str, Any]:
    results = []
    for cid, why, fn in cases:
        try:
            failures = await fn()
        except Exception as exc:  # noqa: BLE001 — a crash is a failed case, named
            failures = [f"raised {type(exc).__name__}: {exc}"]
        results.append({"id": cid, "why": why, "passed": not failures, "failures": failures})
    return _report(results)


def _expect(ok: bool, words: str) -> list[str]:
    return [] if ok else [words]


def _control(suite: dict[str, Any]) -> dict[str, Any]:
    failed = [r["id"] for r in suite["results"] if not r["passed"]]
    return {"suite_failed": not suite["gate"], "failed_cases": len(failed), "ids": failed}


# ---- scoring -------------------------------------------------------------------------------------


def _scoring_cases() -> list[Case]:
    def bars(
        scores: list[ClipScore], want: bool, kind: str = "hear"
    ) -> Callable[[], Awaitable[list[str]]]:
        async def f() -> list[str]:
            v = scoring.hearing_verdict(scores) if kind == "hear" else scoring.voice_verdict(scores)
            return _expect(v.passed is want, f"passed={v.passed}, wanted {want}: {v.why}")

        return f

    def text(
        ref: str, heard: str, cer: float, facts: tuple[int, int]
    ) -> Callable[[], Awaitable[list[str]]]:
        async def f() -> list[str]:
            s = scoring.score_clip(ref, heard)
            out = _expect(math.isclose(s.cer, cer, abs_tol=1e-9), f"cer {s.cer}, wanted {cer}")
            return out + _expect(
                (s.facts_total, s.facts_right) == facts, f"facts {s.facts_total, s.facts_right}"
            )

        return f

    def speed(samples: list[float], want: bool) -> Callable[[], Awaitable[list[str]]]:
        async def f() -> list[str]:
            v = scoring.speed_verdict(samples)
            return _expect(v.passed is want, f"passed={v.passed}: {v.why}")

        return f

    def human(scores: tuple[int, ...], want: bool | None) -> Callable[[], Awaitable[list[str]]]:
        async def f() -> list[str]:
            return _expect(scoring.human_verdict(scores) is want, f"wanted {want}")

        return f

    c = ClipScore
    return [
        ("hear_at_bars", "15 % CER and 90 % facts pass", bars([c(100, 15, 10, 9)], True)),
        ("hear_cer_past", "16 % CER fails", bars([c(100, 16, 10, 10)], False)),
        ("hear_facts_past", "80 % facts fail", bars([c(100, 0, 10, 8)], False)),
        ("hear_no_facts", "no key facts is no verdict", bars([c(100, 0, 0, 0)], False)),
        ("hear_pooled", "pooled over clips", bars([c(100, 30, 5, 5), c(300, 0, 5, 4)], True)),
        ("voice_at_bar", "90 % of voice facts pass", bars([c(50, 40, 10, 9)], True, "voice")),
        ("voice_past", "80 % of voice facts fail", bars([c(50, 0, 10, 8)], False, "voice")),
        ("devanagari_digits", "१०:३० is 10:30", text("१०:३० बजे", "10:30 बजे", 0.0, (1, 1))),
        ("danda_joiner", "danda and joiners are not letters", text("ക്‍ഷ ।", "ക്ഷ", 0.0, (0, 0))),
        ("time_two_numbers", "10 30 is 10:30", text("at 10:30", "at 10:30", 0.0, (1, 1))),
        ("runaway", "a runaway transcript is bounded", text("abc", "x" * 2000, 2000 / 3, (0, 0))),
        ("speed_ok", "half by 1.5 s, 9 in 10 by 2.5 s", speed([1.0] * 5 + [2.0] * 4 + [2.5], True)),
        ("speed_median", "a slow median fails", speed([1.6] * 10, False)),
        ("speed_tail", "a slow tail fails", speed([1.0] * 8 + [3.0] * 2, False)),
        ("human_none", "not yet heard", human((), None)),
        ("human_four", "a mean of 4 passes", human((5, 4, 3), True)),
        ("human_low", "a mean under 4 fails", human((3, 4, 4), False)),
    ]


async def suite_scoring() -> dict[str, Any]:
    s = await _run(_scoring_cases())
    saved = (scoring.HEAR_CER_MAX, scoring.HEAR_FACTS_MIN, scoring.VOICE_FACTS_MIN)
    scoring.HEAR_CER_MAX, scoring.HEAR_FACTS_MIN, scoring.VOICE_FACTS_MIN = 1e9, 0.0, 0.0
    try:
        s["negative_control"] = _control(await _run(_scoring_cases()))
    finally:
        scoring.HEAR_CER_MAX, scoring.HEAR_FACTS_MIN, scoring.VOICE_FACTS_MIN = saved
    s["gate"] = s["gate"] and s["negative_control"]["suite_failed"]
    return s


# ---- the phone line ------------------------------------------------------------------------------


def _tone(freq: float) -> bytes:
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    return from_float(0.4 * np.sin(2 * np.pi * freq * t))


def _db(pcm: bytes) -> float:
    x = to_float(pcm)[1600:-1600]
    return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12))


def _phone_cases(line: Callable[[bytes], bytes]) -> list[Case]:
    def kept(freq: float) -> Callable[[], Awaitable[list[str]]]:
        async def f() -> list[str]:
            d = _db(line(_tone(freq))) - _db(_tone(freq))
            return _expect(abs(d) <= 2.0, f"{freq} Hz changed by {d:.1f} dB")

        return f

    def cut(freq: float, by: float) -> Callable[[], Awaitable[list[str]]]:
        async def f() -> list[str]:
            d = _db(_tone(freq)) - _db(line(_tone(freq)))
            return _expect(d >= by, f"{freq} Hz down only {d:.1f} dB (needs {by})")

        return f

    async def codes() -> list[str]:
        got = phoneline.mulaw_decode(np.array([0xFF, 0x80, 0x00], dtype=np.uint8)).tolist()
        return _expect(got == [0, 32124, -32124], f"decoded {got}")

    async def length() -> list[str]:
        pcm = _tone(1000)
        return _expect(len(line(pcm)) == len(pcm), "length changed")

    async def noisy() -> list[str]:
        pcm = _tone(1000)
        return _expect(line(pcm) != pcm, "the codec left the audio untouched")

    return [
        ("keeps_500", "speech band kept", kept(500)),
        ("keeps_1000", "speech band kept", kept(1000)),
        ("keeps_2500", "speech band kept", kept(2500)),
        ("cuts_6000", "above 3.4 kHz cut", cut(6000, 25)),
        ("cuts_80", "below 300 Hz cut", cut(80, 10)),
        ("codec_noise", "G.711 quantises", noisy),
        ("mulaw_codes", "G.711 known codes", codes),
        ("same_length", "the length is kept", length),
    ]


async def suite_phoneline() -> dict[str, Any]:
    s = await _run(_phone_cases(phoneline.phone_line))
    s["negative_control"] = _control(await _run(_phone_cases(lambda pcm: pcm)))
    s["gate"] = s["gate"] and s["negative_control"]["suite_failed"]
    return s


# ---- selection -----------------------------------------------------------------------------------


def _result(lang: str, option: str, passed: bool = True, **kw: Any) -> LanguageResult:
    fields: dict[str, Any] = {
        "hear_facts": 1.0, "cer": 0.05, "speak_facts": 1.0, "p50_ms": 1200, "p90_ms": 2000,
    }  # fmt: skip
    fields.update(kw)
    return LanguageResult(
        lang=lang, option=SpeechOption(option), checked_at=h.NOW, passed=passed, **fields
    )


def _selection_cases(choose: Callable[..., LanguageResult | None]) -> list[Case]:
    def picks(
        results: list[LanguageResult], lang: str, want: str | None, **kw: bool
    ) -> Callable[[], Awaitable[list[str]]]:
        async def f() -> list[str]:
            opts = {"sarvam_on": False, "allow_balanced": False, **kw}
            got = choose(results, lang, **opts)
            name = got.option.value if got else None
            return _expect(name == want, f"chose {name}, wanted {want}")

        return f

    every = [_result("ml-IN", o) for o in ("sarvam", "bhashini", "azure", "google", "laptop")]
    return [
        ("laptop_first", "the laptop comes first", picks(every, "ml-IN", "laptop")),
        (
            "google_next",
            "then Google",
            picks([r for r in every if r.option != "laptop"], "ml-IN", "google"),
        ),
        (
            "skip_failed",
            "a failed option is skipped",
            picks([_result("ta-IN", "google", False), _result("ta-IN", "azure")], "ta-IN", "azure"),
        ),
        ("sarvam_off", "Sarvam only when on", picks([_result("pa-IN", "sarvam")], "pa-IN", None)),
        (
            "sarvam_on",
            "Sarvam when on",
            picks([_result("pa-IN", "sarvam")], "pa-IN", "sarvam", sarvam_on=True),
        ),
        (
            "balanced_no",
            "balanced only with his YES",
            picks([_result("or-IN", "azure", needs_balanced=True)], "or-IN", None),
        ),
        (
            "balanced_yes",
            "balanced with his YES",
            picks(
                [_result("or-IN", "azure", needs_balanced=True)],
                "or-IN",
                "azure",
                allow_balanced=True,
            ),
        ),
        (
            "forged_pass",
            "a stored pass over the bars is not trusted",
            picks([_result("hi-IN", "google", cer=0.4)], "hi-IN", None),
        ),
        (
            "low_score",
            "a person's 3 of 5 is not offered",
            picks([_result("bn-IN", "google", human_score=3.0, native_heard=True)], "bn-IN", None),
        ),
        ("nothing", "nothing checked: nothing offered", picks([], "as-IN", None)),
    ]


def _reversed_choose(results: Any, lang: str, *, sarvam_on: bool, allow_balanced: bool) -> Any:
    by = select.latest(results)
    for option in reversed(OPTION_ORDER):
        r = by.get((lang, option))
        if r is not None and r.passed and select.verdict(r)[0]:
            return r
    return None


async def suite_selection() -> dict[str, Any]:
    s = await _run(_selection_cases(select.choose))
    s["negative_control"] = _control(await _run(_selection_cases(_reversed_choose)))
    s["gate"] = s["gate"] and s["negative_control"]["suite_failed"]
    return s


# ---- the app's choice: free first (R18 review) ---------------------------------------------------

CALL_MINUTES = 6
FREE_PRICES = {
    SpeechOption.GOOGLE: SpeechPrice(SpeechOption.GOOGLE, 2.29, 2.86, 3600, 1_000_000),
    SpeechOption.AZURE: SpeechPrice(SpeechOption.AZURE, 0.0, 0.0, 18_000, 500_000, can_bill=False),
    SpeechOption.SARVAM: SpeechPrice(SpeechOption.SARVAM, 0.5, 3.0, paid=True),
    SpeechOption.BHASHINI: SpeechPrice(SpeechOption.BHASHINI, None, None),
}


class _GoogleLeft:
    """Google's free allowance left this month: plenty, or used up."""

    def __init__(self, plenty: bool) -> None:
        self.plenty = plenty

    async def left(self, option: SpeechOption) -> tuple[float, float] | None:
        if option is not SpeechOption.GOOGLE:
            return None
        return (1e6, 1e7) if self.plenty else (0.0, 0.0)


FreeChoose = Callable[[list[LanguageResult], CallSettings, bool], Awaitable[str | None]]


async def _app_choice(results: list[LanguageResult], s: CallSettings, plenty: bool) -> str | None:
    """`cards.offered` as the card, the language table and the call use it (free first)."""
    est = Estimator(FREE_PRICES, None, allowance=_GoogleLeft(plenty))
    got = offered(results, s, await est.free_options(CALL_MINUTES)).get(results[0].lang)
    return got.option.value if got else None


async def _list_price_choice(
    results: list[LanguageResult], s: CallSettings, plenty: bool
) -> str | None:
    """The negative control: ranked by list price alone (before the review's fix)."""
    got = offered(results, s).get(results[0].lang)
    return got.option.value if got else None


def _free_cases(choose: FreeChoose) -> list[Case]:
    def picks(
        results: list[LanguageResult], want: str | None, *, plenty: bool, sarvam: bool
    ) -> Callable[[], Awaitable[list[str]]]:
        async def f() -> list[str]:
            got = await choose(results, CallSettings(sarvam_on=sarvam), plenty)
            return _expect(got == want, f"chose {got}, wanted {want}")

        return f

    paid = [
        _result("hi-IN", "sarvam", inr_per_minute=0.70),
        _result("hi-IN", "google", inr_per_minute=1.57),
    ]
    unknown = [
        _result("bn-IN", "bhashini", inr_per_minute=None),
        _result("bn-IN", "google", inr_per_minute=1.57),
    ]
    azure = [
        _result("ml-IN", "sarvam", inr_per_minute=0.70),
        _result("ml-IN", "azure", inr_per_minute=0.0),
    ]
    return [
        ("allowance_left", "Google's allowance covers the call: Google, before cheaper Sarvam",
         picks(paid, "google", plenty=True, sarvam=True)),
        ("allowance_used", "the allowance used: the cheapest paid option he allows (Sarvam)",
         picks(paid, "sarvam", plenty=False, sarvam=True)),
        ("sarvam_off", "Sarvam off: never chosen, Google even past its allowance",
         picks(paid, "google", plenty=False, sarvam=False)),
        ("sarvam_off_free", "Sarvam off with the allowance left: Google",
         picks(paid, "google", plenty=True, sarvam=False)),
        ("azure_free", "Azure's free tier (it can't bill) before paid Sarvam",
         picks(azure, "azure", plenty=False, sarvam=True)),
        ("unknown_last", "an unknown price (Bhashini) after a known one, never as free",
         picks(unknown, "google", plenty=False, sarvam=False)),
    ]  # fmt: skip


async def suite_free_first() -> dict[str, Any]:
    s = await _run(_free_cases(_app_choice))
    s["negative_control"] = _control(await _run(_free_cases(_list_price_choice)))
    s["gate"] = s["gate"] and s["negative_control"]["suite_failed"]
    return s


# ---- the whole check -----------------------------------------------------------------------------


def _options(world: h.World, **over: Any) -> tuple[dict[str, h.Hearing], dict[str, h.Voice]]:
    hearing = {"google": h.Hearing("google", world), "azure": h.Hearing("azure", world)}
    voices = {"google": h.Voice("google", world), "azure": h.Voice("azure", world)}
    hearing.update(over.get("hearing", {}))
    voices.update(over.get("voices", {}))
    return hearing, voices


def _check_cases(make: Callable[..., tuple[LanguageCheck, Any, Any]]) -> list[Case]:
    async def clean() -> list[str]:
        world = h.World()
        lc, store, _ = make(world, *_options(world))
        report = await lc.run(await lc.plan(["hi-IN"]))
        g = next(r for r in report.results if r.option == "google")
        stored = len(await store.language_results())
        return _expect(
            g.passed and stored == 2, f"passed={g.passed} {g.why_failed}, stored {stored}"
        ) + _expect(
            g.versions.get("heard_back_by") == "azure",
            f"heard back by {g.versions.get('heard_back_by')}",
        )

    async def lossy() -> list[str]:
        world = h.World()
        lc, _, _ = make(
            world,
            *_options(
                world,
                hearing={"google": h.Hearing("google", world, lambda t: re.sub(r"\d", "", t))},
            ),
        )
        report = await lc.run(await lc.plan(["hi-IN"]))
        g = next(r for r in report.results if r.option == "google")
        return _expect(
            not g.passed and any("key facts" in w for w in g.why_failed), f"{g.why_failed}"
        )

    async def slow() -> list[str]:
        world = h.World()
        lc, _, _ = make(world, *_options(world, voices={"google": h.Voice("google", world, 1.5)}))
        report = await lc.run(await lc.plan(["hi-IN"]))
        g = next(r for r in report.results if r.option == "google")
        return _expect(not g.passed and any("speed" in w for w in g.why_failed), f"{g.why_failed}")

    async def no_clips() -> list[str]:
        world = h.World()
        lc, _, _ = make(world, *_options(world), clips=h.Clips(world, down=True))
        report = await lc.run(await lc.plan(["hi-IN"]))
        r = report.results[0]
        return _expect(
            not r.passed and any("could not be fetched" in w for w in r.why_failed),
            f"{r.why_failed}",
        )

    async def paid_refused() -> list[str]:
        world = h.World()
        s = h.plain_settings(voice_stt_free_seconds=0)
        lc, store, bill = make(world, *_options(world), settings=s)
        plan = await lc.plan(["hi-IN"], options=["google"])
        refused = False
        try:
            await lc.run(plan)
        except CheckRefused:
            refused = True
        month = await bill.month(h.UID)
        ran = len(await store.language_results())
        return _expect(
            refused and month.inr_total == 0 and ran == 0,
            f"refused={refused}, ₹{month.inr_total}, ran {ran}",
        )

    async def sarvam_off() -> list[str]:
        world = h.World()
        lc, _, _ = make(
            world, {"sarvam": h.Hearing("sarvam", world)}, {"sarvam": h.Voice("sarvam", world)}
        )
        (p,) = (await lc.plan(["hi-IN"], options=["sarvam"])).pairs
        return _expect(not p.runs and "paid option" in p.why, f"runs={p.runs} {p.why}")

    async def low_score() -> list[str]:
        world = h.World()
        lc, store, _ = make(world, *_options(world))
        await lc.run(await lc.plan(["hi-IN"]))
        await lc.score("hi-IN", "google", [3, 3, 4])
        chosen = select.choose(
            await store.language_results(), "hi-IN", sarvam_on=False, allow_balanced=False
        )
        return _expect(
            chosen is not None and chosen.option == "azure", f"chose {chosen and chosen.option}"
        )

    return [
        ("clean_passes", "a clean language passes, stored, judged by another option", clean),
        ("lost_numbers", "lost numbers fail hearing in plain words", lossy),
        ("slow_replies", "slow replies fail speed", slow),
        ("no_clips", "no test clips: hearing not checked, said plainly", no_clips),
        ("paid_refused", "a paid plan is refused before any ₹ or request", paid_refused),
        ("sarvam_off", "Sarvam off is not run", sarvam_off),
        ("low_score", "a person's low score moves the language to the next option", low_score),
    ]


class _NoGate(LanguageCheck):
    async def run(
        self, plan: runner.CheckPlan, *, accept_inr: float = 0.0, accept_unknown: bool = False
    ) -> runner.CheckReport:
        return await super().run(plan, accept_inr=math.inf, accept_unknown=accept_unknown)


def _no_gate(world: h.World, *a: Any, **kw: Any) -> tuple[LanguageCheck, Any, Any]:
    lc, store, bill = h.check(world, *a, **kw)
    lc.__class__ = _NoGate
    return lc, store, bill


async def suite_check() -> dict[str, Any]:
    s = await _run(_check_cases(h.check))
    s["negative_control"] = _control(await _run(_check_cases(_no_gate)))
    s["gate"] = s["gate"] and s["negative_control"]["suite_failed"]
    return s


__all__ = ["suite_check", "suite_phoneline", "suite_scoring", "suite_selection"]
