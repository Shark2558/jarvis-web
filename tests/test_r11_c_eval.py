# tests/test_r11_c_eval.py -- R11 Part C's eval part (evals/r11_helpers/nudges.py) in the unit
# suite: built, every case passes, and its control (claims off, so a restart sends twice) makes the
# fourteen-day case and the asked-once case fail.
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _part() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "r11_eval_nudges_c", ROOT / "evals" / "r11_helpers" / "nudges.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_nudges_eval_is_built_passes_and_its_control_fails_it() -> None:
    part = _part()
    assert part.PART == "nudges" and part.BUILT is True
    got = await part.cases()
    assert [r["id"] for r in got if not r["passed"]] == [], got
    control = await part.control()
    assert control["name"] == "claims_off" and control["suite_failed"] is True
    assert {"nudges:fourteen-days-on-time", "nudges:missed-activity-asked-once"} <= set(
        control["failed_cases"]
    )
    assert [r["id"] for r in await part.cases() if not r["passed"]] == []  # the control undone
