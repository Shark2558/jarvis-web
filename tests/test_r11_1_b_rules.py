# tests/test_r11_1_b_rules.py -- R11.1 Part B (plan D8, D9, D21-B): the fixed rules that turn what
# the recogniser heard into what was meant, with no model. Every case of the fixture set is
# corrected by the rules alone; a number, an amount, a date, a time, a person's name, a phone
# number or an e-mail address is never rewritten (the rules ask instead); and the per-turn hints
# come from file names and the owner's own words, deterministically.
from __future__ import annotations

import json
from typing import Any

import pytest
from r11_1_fakes_b import MISHEARINGS

from jarvis.understand import rules
from jarvis.understand.hints import conversation_nouns, file_hints, turn_hints
from jarvis.understand.rules import RULES, apply
from jarvis.understand.words import protected_words, split_words

CASES: dict[str, list[dict[str, Any]]] = json.loads(MISHEARINGS.read_text(encoding="utf-8"))


def hints_of(case: dict[str, Any]) -> tuple[str, ...]:
    return file_hints(case.get("files", []))


# ---- the fixture set -----------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES["corrected"], ids=lambda c: c["heard"])
def test_a_real_mishearing_is_corrected_by_the_rules_alone(case: dict[str, Any]) -> None:
    out = apply(case["heard"], hints_of(case))
    assert out.text == case["expect"]
    assert out.changed and out.sure and out.candidate is None


@pytest.mark.parametrize("case", CASES["with_files"], ids=lambda c: c["heard"])
def test_a_file_waiting_on_the_composer_settles_a_near_miss(case: dict[str, Any]) -> None:
    out = apply(case["heard"], hints_of(case))
    assert out.text == case["expect"] and out.changed and out.sure
    assert apply(case["heard"], ()).text != case["expect"]  # it was the file's name that did it


@pytest.mark.parametrize("case", CASES["untouched"], ids=lambda c: c["heard"])
def test_words_that_are_right_or_must_never_change_are_left_alone(case: dict[str, Any]) -> None:
    out = apply(case["heard"], ())
    assert out.text == case["heard"] and not out.changed and out.sure, case["why"]


@pytest.mark.parametrize("case", CASES["asks"], ids=lambda c: c["heard"])
def test_when_the_only_fix_would_touch_a_protected_word_the_rules_do_not_act(
    case: dict[str, Any],
) -> None:
    out = apply(case["heard"], ())
    assert out.text == case["heard"] and not out.changed and not out.sure, case["why"]


def test_the_fixture_set_is_big_enough_to_mean_something() -> None:
    assert len(CASES["corrected"]) >= 20 and len(CASES["untouched"]) >= 10
    heard = [c["heard"] for group in CASES.values() if isinstance(group, list) for c in group]
    assert len(heard) == len(set(heard))
    assert "D csb file" in heard and "Tu D calender" in heard  # the owner's own two


def test_with_the_table_emptied_the_owners_own_mishearings_stay_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rules, "RULES", ())
    assert apply("D csb file", ()).text == "D csb file"
    assert apply("Tu D calender", ()).text == "Tu D calender"
    assert len(RULES) >= 30


# ---- D21-B: what is never rewritten --------------------------------------------------------------


@pytest.mark.parametrize(
    ("heard", "kept"),
    [
        ("pay 2,500 rupees to the csb file", ["2,500", "rupees"]),
        ("add it on 12 Nov at 7:30 pm Tu D calender", ["12", "Nov", "7:30", "pm"]),
        ("mail priya@example.com D csb file", ["priya@example.com"]),
        ("ring +91 98450 00000 about D csb file", ["+91", "98450", "00000"]),
        ("tell Meera that D csb file is ready", ["Meera"]),
        ("add sixty sessions Tu D calender", ["sixty"]),
        ("book it for Monday the 3rd Tu D calender", ["Monday", "3rd"]),
    ],
)
def test_protected_words_survive_every_correction_around_them(heard: str, kept: list[str]) -> None:
    out = apply(heard, ())
    assert out.changed  # the mishearings around them were still fixed
    for word in kept:
        assert word in out.text.split(), (word, out.text)
    assert protected_words(heard) == protected_words(out.text)


def test_numbers_money_dates_times_names_phones_and_mail_are_all_protected() -> None:
    text = "Call Meera on 98450 00000 or meera@example.com at 7:30 pm on 12 Nov about ₹2,500"
    kept = set(protected_words(text))
    for word in (
        "Meera",
        "98450",
        "00000",
        "meera@example.com",
        "7:30",
        "pm",
        "12",
        "Nov",
        "₹2,500",
    ):
        assert word in kept, word
    assert "about" not in kept and "Call" not in kept


def test_a_name_is_protected_after_a_cue_even_in_small_letters() -> None:
    assert "priya" in protected_words("call priya now")
    assert "the" not in protected_words("call the plumber")
    assert {"D", "Raja"} <= set(protected_words("Send it to D Raja"))


def test_split_words_keeps_the_punctuation_beside_each_word() -> None:
    words = split_words("Tu D calender, please.")
    assert [w.core for w in words] == ["Tu", "D", "calender", "please"]
    assert words[2].tail == "," and words[3].tail == "."


def test_a_fuzzy_match_needs_exactly_one_candidate() -> None:
    two = ("study plan", "study plot")
    out = apply("open the study plat", two)
    assert not out.changed and not out.sure  # two files fit: ask, never guess
    assert apply("open the study plant", ("study plan",)).text == "open the study plan"


def test_a_fuzzy_match_never_rewrites_an_ordinary_or_protected_word() -> None:
    assert apply("send the plan to Priya", ("plant", "Riya")).text == "send the plan to Priya"
    assert apply("add 2026 rows", ("2027",)).text == "add 2026 rows"
    assert apply("call priya about the budget", ("riya",)).text == "call priya about the budget"


# ---- D9: per-turn hints --------------------------------------------------------------------------


def test_file_names_give_their_stem_and_their_kind_as_hints() -> None:
    hints = file_hints(["study-plan.csv", "Budget_2027 final.XLSX", "Q3 deck.pptx", "scan.jpg"])
    assert hints[:2] == ("study plan", "CSV")
    assert "Budget 2027 final" in hints and "Excel" in hints and "PowerPoint" in hints
    assert "Q3 deck" in hints and "scan" in hints
    assert all(len(h) <= 40 for h in hints)


def test_a_hostile_file_name_cannot_put_odd_characters_in_a_hint() -> None:
    hints = file_hints(["<script>alert(1)</script>.csv", "a‮b\u0000c.txt", "x" * 300 + ".md", ""])
    assert all("<" not in h and "‮" not in h and "\x00" not in h for h in hints)
    assert all(len(h) <= 40 for h in hints)


def test_conversation_nouns_are_capitalised_or_repeated_words_newest_first() -> None:
    said = [
        "Plan the CCA study sessions for Kerala",
        "the sessions should cover the registry design",
        "put the registry sessions after the Kerala review",
    ]
    nouns = conversation_nouns(said)
    assert nouns[:3] == ("Kerala", "registry", "sessions")
    assert "CCA" in nouns and "the" not in nouns and "should" not in nouns
    assert conversation_nouns([]) == ()


def test_turn_hints_are_files_then_nouns_within_the_cap() -> None:
    files = [f"file number {i}.csv" for i in range(30)]
    hints = turn_hints(files, ["Plan the Kerala review", "the Kerala review again"], limit=12)
    assert len(hints) == 12 and hints[0] == "file number 0" and hints[1] == "CSV"
    assert turn_hints(files, [], limit=0) == ()
    few = turn_hints(["study-plan.csv"], ["Plan the Kerala review", "Kerala again"], limit=40)
    assert few == ("study plan", "CSV", "Kerala")
