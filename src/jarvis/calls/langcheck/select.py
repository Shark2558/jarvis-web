# src/jarvis/calls/langcheck/select.py
"""Which option a language uses, and which languages call cards may offer (R18 B; plan 5.3 step 5).

`verdict` re-reads a stored `LanguageResult` against the plan's bars (`LANG_CHECK`), so the pass
is always the bars', also after the owner scores a sample:

    hearing  key facts ≥ 90 % and character error rate ≤ 15 %
    voice    key facts ≥ 90 % after the phone line
    speed    half of the replies start within 1.5 s, 9 in 10 within 2.5 s
    person   the owner's mean score of 1–5 at least 4, once he has scored (until then the language
             is offered "not yet heard by a native speaker")
    brain    not failed (a language whose 10-turn mock call failed on the fast tier)

`choose`: for each language, the FIRST passing option in the order laptop → Google free → Azure
free → Bhashini → Sarvam, Sarvam only when the owner turned it on; a result that needs the
balanced tier only with his YES (`allow_balanced`). The latest result per language and option
counts. Only chosen languages appear on call cards (`offered`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.calls.models import LANG_CHECK, LANGUAGE_NAMES, LangCheckBars, LanguageResult
from jarvis.calls.speech.catalogue import OPTION_ORDER, SARVAM


def _pct(x: float) -> str:
    return f"{round(x * 100)} %"


def _hearing(r: LanguageResult, bars: LangCheckBars) -> list[str]:
    if r.hear_facts is None or r.cer is None:
        return ["hearing was not checked"]
    out = []
    if r.hear_facts < bars.hear_facts:
        out.append(f"hearing: {_pct(r.hear_facts)} of key facts (needs {_pct(bars.hear_facts)})")
    if r.cer > bars.max_cer:
        out.append(f"hearing: character error rate {_pct(r.cer)} (at most {_pct(bars.max_cer)})")
    return out


def _voice(r: LanguageResult, bars: LangCheckBars) -> list[str]:
    if r.speak_facts is None:
        return ["voice was not checked"]
    if r.speak_facts < bars.speak_facts:
        return [f"voice: {_pct(r.speak_facts)} of key facts heard (needs {_pct(bars.speak_facts)})"]
    return []


def _speed(r: LanguageResult, bars: LangCheckBars) -> list[str]:
    if r.p50_ms is None or r.p90_ms is None:
        return ["speed was not measured"]
    out = []
    if r.p50_ms > bars.p50_ms:
        out.append(f"speed: half of the replies within {r.p50_ms / 1000:.1f} s (needs 1.5 s)")
    if r.p90_ms > bars.p90_ms:
        out.append(f"speed: 9 in 10 replies within {r.p90_ms / 1000:.1f} s (needs 2.5 s)")
    return out


def verdict(r: LanguageResult, bars: LangCheckBars = LANG_CHECK) -> tuple[bool, tuple[str, ...]]:
    reasons = [*_hearing(r, bars), *_voice(r, bars), *_speed(r, bars)]
    if r.human_score is not None and r.human_score < bars.human_score:
        reasons.append(f"a person scored it {r.human_score:.1f} of 5 (needs {bars.human_score})")
    if r.brain_ok is False:
        reasons.append("the brain's fast tier did not hold a mock call in this language")
    return not reasons, tuple(reasons)


def latest(results: Sequence[LanguageResult]) -> dict[tuple[str, str], LanguageResult]:
    out: dict[tuple[str, str], LanguageResult] = {}
    for r in results:
        key = (r.lang, r.option.value)
        if key not in out or r.checked_at > out[key].checked_at:
            out[key] = r
    return out


def _usable(r: LanguageResult | None, allow_balanced: bool) -> bool:
    return r is not None and r.passed and verdict(r)[0] and (allow_balanced or not r.needs_balanced)


def choose(
    results: Sequence[LanguageResult] | dict[tuple[str, str], LanguageResult],
    lang: str,
    *,
    sarvam_on: bool,
    allow_balanced: bool,
) -> LanguageResult | None:
    by_key = results if isinstance(results, dict) else latest(results)
    for option in OPTION_ORDER:
        if option == SARVAM and not sarvam_on:
            continue
        r = by_key.get((lang, option))
        if _usable(r, allow_balanced):
            return r
    return None


@dataclass(frozen=True)
class LanguageRow:
    """One line of the Calls panel's language table."""

    lang: str
    name: str
    option: str | None  # None: not offered
    inr_per_minute: float | None  # None: unknown (never shown as ₹0)
    native_heard: bool
    needs_balanced: bool
    why: tuple[str, ...]  # why it is not offered (each option's reasons)


def table(
    results: Sequence[LanguageResult],
    langs: Sequence[str],
    *,
    sarvam_on: bool,
    allow_balanced: bool,
) -> list[LanguageRow]:
    by_key = latest(results)
    rows = []
    for lang in langs:
        chosen = choose(by_key, lang, sarvam_on=sarvam_on, allow_balanced=allow_balanced)
        if chosen is not None:
            rows.append(
                LanguageRow(
                    lang,
                    LANGUAGE_NAMES.get(lang, lang),
                    chosen.option.value,
                    chosen.inr_per_minute,
                    chosen.native_heard,
                    chosen.needs_balanced,
                    (),
                )  # fmt: skip
            )
            continue
        why = tuple(
            f"{option}: {'; '.join(r.why_failed or verdict(r)[1]) or 'needs the balanced tier'}"
            for option in OPTION_ORDER
            if (r := by_key.get((lang, option))) is not None
        ) or ("not checked yet",)
        rows.append(
            LanguageRow(lang, LANGUAGE_NAMES.get(lang, lang), None, None, False, False, why)
        )
    return rows


def offered(
    results: Sequence[LanguageResult], *, sarvam_on: bool, allow_balanced: bool
) -> tuple[str, ...]:
    """The languages call cards may use: those with a chosen option, in the table's order."""
    by_key = latest(results)
    return tuple(
        lang
        for lang in LANGUAGE_NAMES
        if choose(by_key, lang, sarvam_on=sarvam_on, allow_balanced=allow_balanced) is not None
    )


__all__ = ["LanguageRow", "choose", "latest", "offered", "table", "verdict"]
