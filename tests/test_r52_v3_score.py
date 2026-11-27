# tests/test_r52_v3_score.py -- R5.2 V3: scoring the session (plan 3.3, 5). Word error and command
# accuracy on the held-out prompts, the fair common set, the chosen engine (the laptop within the
# 2-point bar), corrections that repeat and never touch numbers, money or codes, and new words.
from __future__ import annotations

import pytest
from r52_v3_fakes import normalise

from jarvis.localspeech.protocol import PromptKind
from jarvis.voice.profile import EngineScore, ListenEngine, Prompt, apply_corrections
from jarvis.voice.session_prompts import build_prompts, scored
from jarvis.voice.session_score import (
    MIN_PROMPTS,
    Heard,
    align,
    choose,
    edits,
    learn_corrections,
    meets_bar,
    new_words,
    score_engines,
    tokens,
    words_of,
)

B, G = ListenEngine.BROWSER, ListenEngine.GOOGLE
S, M = ListenEngine.WHISPER_SMALL, ListenEngine.WHISPER_MEDIUM


@pytest.mark.parametrize(
    ("said", "heard"),
    [
        ("Wake me at 6:45 tomorrow.", "wake me at six forty-five tomorrow"),
        ("What's 18 percent of 2,400?", "what's 18% of two thousand four hundred"),
        ("The bill was 450 rupees.", "the bill was ₹450"),
        ("Split 1,200 between 4 people.", "split 1200 between four people"),
        ("The code is 4 7 2 9.", "the code is four seven two nine"),
        ("It costs 1,999 rupees.", "it costs one thousand nine hundred and ninety nine rupees"),
        ("Set an alarm for 5:20.", "Set an alarm for 5.20"),
        ("The battery is at 80 percent.", "the battery is at eighty per cent"),
    ],
)
def test_an_engines_own_way_of_writing_numbers_is_not_an_error(said: str, heard: str) -> None:
    assert tokens(said, normalise) == tokens(heard, normalise)


def test_am_and_pm_and_plain_words() -> None:
    assert tokens("at 7 a.m.", normalise) == ["at", "7", "am"]
    assert tokens("a man", normalise) == ["a", "man"]
    assert words_of("That'll be all, Java’s") == ["that'll", "be", "all", "java's"]


def test_word_alignment_counts_each_edit() -> None:
    ref, hyp = "stop talking now".split(), "stop walking now please".split()
    assert edits(ref, hyp) == 2
    ops = [op for op, _, _ in align(ref, hyp)]
    assert ops == ["=", "s", "=", "i"]
    assert edits([], ["a"]) == 1 and edits(["a"], []) == 1


def _heard(plan_prompts: tuple[Prompt, ...], engine: ListenEngine, wrong: int = 0) -> list[Heard]:
    """Every held-out prompt heard right, but the first `wrong` ones with a word dropped."""
    rows = []
    for i, p in enumerate(x for x in plan_prompts if scored(x)):
        text = p.text if i >= wrong else " ".join(p.text.split()[1:])
        rows.append(Heard(engine=engine, prompt_id=p.id, text=text, ms=100 + i))
    return rows


def test_engines_ranked_by_word_error_with_command_accuracy() -> None:
    plan = build_prompts()
    heard = _heard(plan.prompts, S, 4) + _heard(plan.prompts, G, 0) + _heard(plan.prompts, B, 30)
    ranking = score_engines(plan.prompts, plan.keys, heard, normalise)
    assert [s.engine for s in ranking] == [G, S, B]
    google, small, browser = ranking
    assert google.wer == 0 and google.commands == 1 and google.prompts == 80
    assert 0 < small.wer < browser.wer and small.median_ms == 139
    assert browser.commands < 1  # dropped first words lose some commands' key phrases


def test_engines_are_compared_on_the_prompts_every_one_heard() -> None:
    plan = build_prompts()
    held = [p for p in plan.prompts if scored(p)]
    google = [h for h in _heard(plan.prompts, G) if h.prompt_id in {p.id for p in held[:40]}]
    small = _heard(plan.prompts, S)
    few = _heard(plan.prompts, B)[: MIN_PROMPTS - 1]
    ranking = score_engines(plan.prompts, plan.keys, google + small + few, normalise)
    assert {s.engine for s in ranking} == {G, S}  # too few for the browser
    assert all(s.prompts == 40 for s in ranking)
    assert score_engines(plan.prompts, plan.keys, few, normalise) == ()


def _score(engine: ListenEngine, wer: float, commands: float = 1.0) -> EngineScore:
    return EngineScore(engine=engine, wer=wer, commands=commands, prompts=80)


def test_the_laptop_is_chosen_within_two_points_and_medium_only_when_clearly_better() -> None:
    assert choose([_score(G, 0.05), _score(S, 0.065)]) is S
    assert choose([_score(G, 0.05), _score(S, 0.08)]) is G
    assert choose([_score(G, 0.05), _score(S, 0.06, commands=0.9)]) is G
    assert choose([_score(M, 0.04), _score(S, 0.05)]) is S  # medium not clearly better
    assert choose([_score(M, 0.02), _score(G, 0.03), _score(S, 0.05)]) is M
    assert choose([]) is None
    assert meets_bar([_score(G, 0.05), _score(S, 0.065)], S) is True
    assert meets_bar([_score(S, 0.065)], S) is None
    assert meets_bar([_score(G, 0.01), _score(S, 0.065)], S) is False


def _rows(prompts: list[Prompt], text_of: dict[str, str]) -> list[Heard]:
    return [Heard(engine=S, prompt_id=p.id, text=text_of.get(p.id, p.text)) for p in prompts]


def test_repeating_mishearings_become_corrections_applied_to_the_engines_own_text() -> None:
    plan = build_prompts()
    held = [p for p in plan.prompts if scored(p)]
    jarvis = [p for p in held if "Jarvis" in p.text]
    assert len(jarvis) >= 2
    wrong = {p.id: p.text.replace("Jarvis", "Java's") for p in jarvis}
    once = next(p for p in held if "Mumbai" in p.text)
    wrong[once.id] = once.text.replace("Mumbai", "Mum Bye")  # once only: not learned
    found = learn_corrections(plan.prompts, _rows(held, wrong))
    assert [(c.heard, c.meant, c.seen) for c in found] == [("java's", "Jarvis", len(jarvis))]
    assert apply_corrections("Thank you, Java's.", found) == "Thank you, Jarvis."


def test_corrections_never_come_from_numbers_money_or_codes() -> None:
    plan = build_prompts()
    held = [p for p in plan.prompts if scored(p)]
    numbers = [p for p in held if p.kind is PromptKind.NUMBERS]
    wrong = {p.id: p.text.replace("minutes", "minnits") for p in numbers}
    wrong |= {p.id: "the coat is four seven two nine" for p in numbers if "code" in p.text}
    asks = [p for p in held if p.kind is PromptKind.COMMAND and "rupee" not in p.text][:3]
    wrong |= {p.id: p.text + " two" for p in asks}  # a heard number word: refused
    assert learn_corrections(plan.prompts, _rows(held, wrong)) == ()


def test_a_phrase_he_really_says_elsewhere_is_never_corrected() -> None:
    plan = build_prompts()
    held = [p for p in plan.prompts if scored(p)]
    jarvis = [p for p in held if "Jarvis" in p.text]
    wrong = {p.id: p.text.replace("Jarvis", "mic") for p in jarvis}  # he says "mic" in commands
    assert len(jarvis) >= 2 and learn_corrections(plan.prompts, _rows(held, wrong)) == ()


def test_new_words_are_his_typed_names_and_misheard_names_never_twice() -> None:
    plan = build_prompts(["Zephyrine"])
    held = [p for p in plan.prompts if scored(p)]
    mine = [p for p in plan.prompts if p.id in plan.own]
    wrong = {p.id: p.text.replace("Zephyrine", "Zeffer Inn") for p in mine}
    found = learn_corrections(plan.prompts, _rows(held, wrong))
    assert [(c.heard, c.meant) for c in found] == [("zeffer inn", "Zephyrine")]
    got = new_words(found, plan.prompts, ["Quillon", "jarvis"], ["zephyrine"])
    assert got == ("Quillon",)  # his word already listed; JARVIS is always sent
    assert new_words(found, plan.prompts, [], []) == tuple(c.meant for c in found)
