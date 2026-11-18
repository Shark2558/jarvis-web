# tests/test_r131_i1_e2e.py -- R13.1 I1: his workbook's end-to-end tests (the avatar halves, See it
# on me's life, row 388 through the mock brain) and the needles, as pytest cases over the eval
# suites (`evals/r13_1/e2e.py`, `needles.py`, run on the REAL app by `evals/r13_1/wired.py`), so a
# failure names the case, and each suite's control must fail it for its own reason.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

EVALS = Path(__file__).resolve().parents[1] / "evals" / "r13_1"


def _suite(name: str) -> ModuleType:
    """A suite by path under a unique name: evals/r13_1 never joins sys.path."""
    spec = importlib.util.spec_from_file_location(f"r13_1_suite_{name}", EVALS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


e2e, needles = _suite("e2e"), _suite("needles")


@pytest.mark.parametrize("suite", [e2e, needles], ids=["e2e", "needles"])
async def test_every_case_passes(suite: ModuleType) -> None:
    assert suite.BUILT is True
    got = await suite.cases()
    assert len(got) == len(suite.CASES) and all(r["passed"] for r in got), [
        r for r in got if not r["passed"]
    ]


async def test_the_e2e_control_fails_the_meeting_update() -> None:
    control = await e2e.control()
    assert control["suite_failed"] is True
    assert control["failed_cases"] == ["e2e:meeting_outfit_update"]


async def test_the_needles_control_finds_the_photos_in_the_logs_only() -> None:
    control = await needles.control()
    assert control["suite_failed"] is True
    assert set(control["failed_cases"]) == {
        "needles:needle_his_photo",
        "needles:needle_garment_photo",
    }
