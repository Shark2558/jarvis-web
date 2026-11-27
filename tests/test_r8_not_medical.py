# tests/test_r8_not_medical.py -- R8 I0 seam S21 (docs/plans/r8-vision.md 6.5, ADR-51): no coach
# ever states a diagnosis, a medicine or a dose. The scan reads every coach's words: the fixed
# words in jarvis.coach.words, every string in every console-coach-*.js module, every home rule's
# strings (jarvis.coach.home), the blood-pressure category lines (only the published table's own
# name with its source: the owner's D7), and every `view` the evals produce (evals/r8, evals/r8_1
# call `medical_hits` on theirs). A negative control plants a line and must be caught.
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from r7_jsguard import tokens

from jarvis.coach import bp
from jarvis.coach.words import COACH_WORDS, NOT_MEDICAL, SAFETY, medical_hits, scan

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
HOME = ROOT / "src" / "jarvis" / "coach" / "home"


def _js_strings(path: Path) -> list[str]:
    return [t.text for t in tokens(path.read_text(encoding="utf-8")) if t.kind in ("str", "tmpl")]


def _py_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    ]


def test_the_list_holds_the_plans_words() -> None:
    for word in ("you have", "diagnos", "hypertension", "normal range", "mg", "dose", "take your",
                 "prescri", "treat"):  # fmt: skip
        assert word in NOT_MEDICAL, word


def test_every_fixed_coach_word_may_be_said() -> None:
    lines = [line for words in COACH_WORDS.values() for line in words]
    assert set(SAFETY) <= set(lines)
    assert scan(lines) == []


@pytest.mark.parametrize("path", sorted(STATIC.glob("console-coach-*.js")), ids=lambda p: p.name)
def test_no_console_coach_says_anything_medical(path: Path) -> None:
    assert scan(_js_strings(path)) == [], path.name


@pytest.mark.parametrize("path", sorted(HOME.glob("*.py")), ids=lambda p: p.name)
def test_no_home_rule_says_anything_medical(path: Path) -> None:
    assert scan(_py_strings(path)) == [], path.name


def test_a_category_is_its_published_name_and_its_source_only() -> None:
    if bp.CATEGORIES:  # builder D fills it from SOURCE; until then nothing is shown
        assert bp.SOURCE is not None and bp.SOURCE.url.startswith("https://")
    for row in bp.CATEGORIES:
        line = bp.category_line(row, bp.SOURCE)  # type: ignore[arg-type]
        assert re.fullmatch(
            r".+ \(by .+, .+, \d{4}\)\.(?: Talk to your doctor about this reading\.)?", line
        )
        rest = line.replace(row.name, "", 1)
        assert scan([rest]) == [], line  # nothing JARVIS adds is medical
    assert scan([bp.TALK_TO_DOCTOR, bp.NOT_MEDICAL]) == []


@pytest.mark.parametrize(
    "planted",
    [
        "Your blood pressure is in the normal range.",
        "You have hypertension, Sir.",
        "Take your tablet after the session.",
        "This exercise will treat your back pain.",
        "A 5 mg dose may help.",
        "That is a diagnosis I can't make.",
    ],
)
def test_the_negative_controls_are_caught(planted: str) -> None:
    assert medical_hits(planted) != []
    assert scan(["Ten reps, Sir.", planted]) == [(planted, medical_hits(planted))]


def test_counts_and_tips_are_not_caught() -> None:
    fine = ["Ten reps, Sir.", "Hold for 30 seconds.", "Sit back and lift your head, Sir.",
            "Breathe in for four.", "Lower your hips a little.", "Guest 2: 12 squats."]  # fmt: skip
    assert scan(fine) == []
