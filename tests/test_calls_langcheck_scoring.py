# tests/test_calls_langcheck_scoring.py — R18 B: the language check's scorer (plan 5.3): text
# normalisation for every Indian script, key facts (numbers, times, dates; words the brain marked),
# character error rate, and the pass bars exactly as the plan states them.
from __future__ import annotations

import pytest

from jarvis.calls.langcheck.scoring import (
    HEAR_CER_MAX,
    HEAR_FACTS_MIN,
    HUMAN_SCORE_MIN,
    SPEED_FAST_S,
    SPEED_FAST_SHARE,
    SPEED_SLOW_S,
    SPEED_SLOW_SHARE,
    VOICE_FACTS_MIN,
    ClipScore,
    cer,
    edit_distance,
    facts_found,
    hearing_verdict,
    human_verdict,
    normalise,
    number_facts,
    score_clip,
    speed_verdict,
    voice_verdict,
)


def test_the_bars_are_the_plans() -> None:
    assert HEAR_FACTS_MIN == 0.90 and HEAR_CER_MAX == 0.15
    assert VOICE_FACTS_MIN == 0.90 and HUMAN_SCORE_MIN == 4.0
    assert (SPEED_FAST_S, SPEED_FAST_SHARE) == (1.5, 0.5)
    assert (SPEED_SLOW_S, SPEED_SLOW_SHARE) == (2.5, 0.9)


# ---- normalisation ---------------------------------------------------------------------------


def test_normalise_drops_punctuation_case_and_extra_space() -> None:
    assert normalise("  Hello,   WORLD!  It's 10:30. ") == "hello world it s 10 30"


def test_normalise_keeps_indic_vowel_signs_and_drops_danda_and_joiners() -> None:
    assert normalise("नमस्ते।  मैं ठीक हूँ॥") == "नमस्ते मैं ठीक हूँ"
    assert normalise("ക്‍ഷ") == normalise("ക്ഷ")  # a zero-width joiner is not a letter


def test_normalise_turns_every_script_s_digits_into_ascii() -> None:
    assert normalise("१०:३० बजे") == "10 30 बजे"
    assert normalise("১২৩ ௪௫ ൬") == "123 45 6"


# ---- facts -----------------------------------------------------------------------------------


def test_number_facts_read_times_groupings_and_scripts() -> None:
    assert number_facts("Pickup at 10:30 on 28.11, ₹1,00,000 and 3 bags") == (
        "1030",
        "2811",
        "100000",
        "3",
    )
    assert number_facts("सुबह ०९:३० बजे") == ("930",)  # leading zeros are not a difference
    assert number_facts("no numbers") == ()


def test_numeric_facts_match_digit_for_digit() -> None:
    assert facts_found(("1030", "3"), "at 10.30 with 3 bags") == 2
    assert facts_found(("1030",), "at 10 30") == 1  # a time heard as two numbers
    assert facts_found(("1030",), "at 10 40") == 0
    assert facts_found(("13",), "at 1030") == 0  # never a part of another number


def test_word_facts_match_after_normalisation() -> None:
    assert facts_found(("हाँ", "Saturday"), "जी हाँ, saturday को") == 2
    assert facts_found(("नहीं",), "जी हाँ") == 0


# ---- CER ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "d"),
    [("", "", 0), ("abc", "", 3), ("", "ab", 2), ("kitten", "sitting", 3), ("नमस्ते", "नमस्ते", 0)],
)
def test_edit_distance(a: str, b: str, d: int) -> None:
    assert edit_distance(a, b) == d


def test_cer_is_edits_over_the_reference_after_normalisation() -> None:
    assert cer("Hello, world.", "hello world") == 0.0
    assert cer("abcd", "abed") == pytest.approx(0.25)
    assert cer("", "") == 0.0


def test_a_runaway_transcript_is_bounded_but_still_wrong() -> None:
    s = score_clip("abc", "x" * 100_000)
    assert s.edits >= 3 and s.ref_chars == 3
    assert s.cer > 1.0


def test_score_clip_counts_the_reference_s_own_facts_by_default() -> None:
    ref = "The shop opens at 9:30 and closes at 18:00."
    s = score_clip(ref, "the shop opens at 9 30 and closes")
    assert (s.facts_total, s.facts_right) == (2, 1)
    assert s.ref_chars == len(normalise(ref))


# ---- verdicts ----------------------------------------------------------------------------------


def clip(edits: int, facts: tuple[int, int], chars: int = 100) -> ClipScore:
    return ClipScore(ref_chars=chars, edits=edits, facts_total=facts[0], facts_right=facts[1])


def test_hearing_passes_at_both_bars_exactly() -> None:
    v = hearing_verdict([clip(15, (10, 9))])
    assert v.passed and v.cer == pytest.approx(0.15) and v.facts_rate == pytest.approx(0.9)


def test_hearing_fails_on_either_bar_and_says_which() -> None:
    cer_bad = hearing_verdict([clip(16, (10, 10))])
    assert not cer_bad.passed and "character error rate" in cer_bad.why
    facts_bad = hearing_verdict([clip(0, (10, 8))])
    assert not facts_bad.passed and "key facts" in facts_bad.why


def test_hearing_is_pooled_over_the_clips() -> None:
    v = hearing_verdict([clip(30, (5, 5), chars=100), clip(0, (5, 4), chars=300)])
    assert v.cer == pytest.approx(30 / 400) and v.facts_rate == pytest.approx(0.9) and v.passed


def test_no_clips_or_no_facts_is_not_a_pass() -> None:
    assert not hearing_verdict([]).passed
    no_facts = hearing_verdict([clip(0, (0, 0))])
    assert not no_facts.passed and "no key facts" in no_facts.why


def test_voice_needs_ninety_percent_of_its_facts() -> None:
    assert voice_verdict([clip(50, (10, 9))]).passed  # the round trip's CER is not a bar
    v = voice_verdict([clip(0, (10, 8))])
    assert not v.passed and "80 %" in v.why
    assert not voice_verdict([]).passed


def test_speed_is_the_plans_two_shares() -> None:
    ok = speed_verdict([1.0] * 5 + [2.0] * 4 + [2.5])  # half by 1.5 s, all by 2.5 s
    assert ok.passed and ok.p50 == 1.0
    slow_median = speed_verdict([1.6] * 10)
    assert not slow_median.passed and "1.5 s" in slow_median.why
    slow_tail = speed_verdict([1.0] * 8 + [3.0] * 2)
    assert not slow_tail.passed and "2.5 s" in slow_tail.why
    assert not speed_verdict([]).passed


def test_speed_reports_its_percentiles() -> None:
    v = speed_verdict([0.1 * i for i in range(1, 21)])
    assert v.p50 == pytest.approx(1.0) and v.p90 == pytest.approx(1.8)


def test_human_scores_mean_of_at_least_four() -> None:
    assert human_verdict(()) is None  # not yet heard by a native speaker
    assert human_verdict((4, 4, 5)) is True
    assert human_verdict((5, 4, 3)) is True  # a mean of 4.0
    assert human_verdict((3, 4, 4)) is False
    with pytest.raises(ValueError):
        human_verdict((0,))
    with pytest.raises(ValueError):
        human_verdict((6,))
