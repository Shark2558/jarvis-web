# tests/test_r14_d_eval.py -- Part D's eval part (evals/r14/noai.py) is BUILT: its cases pass on
# fakes and its negative control (R14 phrases off) fails every D12 row, so it can fail at all.
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _noai() -> ModuleType:
    spec = importlib.util.spec_from_file_location("r14_noai_eval", ROOT / "evals/r14/noai.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_noai_part_passes_and_its_control_fails_every_row() -> None:
    noai = _noai()
    assert noai.PART == "noai" and noai.BUILT is True
    results = await noai.cases()
    assert [r["id"] for r in results if not r["passed"]] == []
    rows = [r["id"] for r in results if r["id"].startswith("noai:row")]
    assert len(rows) >= 13  # at least one example per row of plan D12
    control = await noai.control()
    assert control["suite_failed"] is True and sorted(control["failed_cases"]) == sorted(rows)
