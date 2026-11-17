# tests/test_r131_d_eval.py -- R13.1 Part D's `console` eval keeps its controls honest (review D-1
# L10): a control turns its row's case red only when the case's OWN checks fail, with no error of
# its own (a copy that crashes, or Node missing, proves nothing about the row).
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _eval() -> Any:
    spec = importlib.util.spec_from_file_location(
        "r131_d_console_eval", ROOT / "evals" / "r13_1" / "console.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_each_control_names_the_checks_it_must_turn_red() -> None:
    E = _eval()
    assert E.MUST_FAIL == {
        "avt15": {"checklist", "why"},
        "avt06": {"thumbnail_w2"},
        "avt11": {"each_readiness"},
        "row388": {"opened", "pieces", "covered"},
    }
    assert set(E.MUST_FAIL) == set(E.CONTROLS)


def test_a_control_counts_only_when_its_own_checks_fail_and_nothing_crashed() -> None:
    red = _eval().turned_red
    assert red("avt06", {"failures": ["thumbnail_w2"], "error": ""}) is True
    assert red("avt06", {"failures": ["opened"], "error": ""}) is False  # another check
    lost = "node is not installed"
    assert red("avt06", {"failures": [lost], "error": lost}) is False  # nothing ran
    crashed = {"failures": ["thumbnail_w2", "TypeError: x is null"], "error": "TypeError"}
    assert red("avt06", crashed) is False  # a crash is not the row's failure
    assert red("row388", {"failures": ["opened", "pieces"], "error": ""}) is False  # all three
    assert red("row388", {"failures": ["opened", "pieces", "covered"], "error": ""}) is True
