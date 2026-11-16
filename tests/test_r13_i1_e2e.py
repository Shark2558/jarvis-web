# tests/test_r13_i1_e2e.py -- R13 I1: the workbook's end-to-end tests and the needles, as pytest
# cases over the eval suites (`evals/r13/e2e.py`, `needles.py`, run on the REAL app by
# `evals/r13/wired.py`), so a failure names the case, and each suite's control must fail it.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

EVALS = Path(__file__).resolve().parents[1] / "evals" / "r13"


def _suite(name: str) -> ModuleType:
    """A suite by path under a unique name: evals/r13 never joins sys.path (its `catalog`,
    `styling`, `phone`, `contract` and `run` would win over anything imported later)."""
    spec = importlib.util.spec_from_file_location(f"r13_suite_{name}", EVALS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


e2e, needles = _suite("e2e"), _suite("needles")


@pytest.mark.parametrize("suite", [e2e, needles], ids=["e2e", "needles"])
async def test_every_case_passes(suite: object) -> None:
    got = await suite.cases()  # type: ignore[attr-defined]
    assert got and all(r["passed"] for r in got), [r for r in got if not r["passed"]]


async def test_the_e2e_control_fails_tests_1_3_and_8() -> None:
    control = await e2e.control()
    assert control["suite_failed"] is True
    assert {"e2e:e2e_1", "e2e:e2e_3", "e2e:e2e_8"} <= set(control["failed_cases"])


async def test_the_needles_control_fails_exactly_the_private_label_case() -> None:
    control = await needles.control()
    assert control["failed_cases"] == ["needles:needle_private_label"]
