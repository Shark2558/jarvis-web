# tests/test_evals_r11.py -- the R11 eval (evals/r11_helpers) in the unit suite, mock mode: I0's
# `gate` part passes and its control (the caps switched off) makes it fail; every part file
# exists with the shared interface, and an unbuilt part reports only "not built yet". Each builder
# adds its own assertions for its part here (or in its own tests/test_evals_r11_<part>.py).
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "evals" / "r11_helpers"
RUN = HERE / "run.py"
PARTS = ("gate", "today", "house", "nudges", "kitchen", "needles")


def test_every_part_file_has_the_interface() -> None:
    for part in PARTS:
        spec = importlib.util.spec_from_file_location(f"r11_eval_{part}", HERE / f"{part}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT / "tests"))
        spec.loader.exec_module(module)
        assert module.PART == part and isinstance(module.BUILT, bool), part
        assert callable(module.cases) and callable(module.control), part


def test_the_gate_part_passes_and_its_control_fails_it() -> None:
    r = subprocess.run(
        [sys.executable, str(RUN), "--mock"], capture_output=True, text=True, timeout=300
    )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    report = json.loads((HERE / "report.json").read_text())
    ids = {x["id"] for x in report["results"]}
    assert report["passed"] == report["cases"] and "gate:fourteen-days-on-time" in ids
    control = report["negative_control"]
    assert (
        control["suite_failed"] is True and "gate:caps-per-kind" in control["failed_cases"]["gate"]
    )
    unbuilt = set(control["parts_not_built"])
    for part in unbuilt:
        assert f"{part}:not_built_yet" in ids


def test_every_part_is_built_and_each_control_fails_its_own_part() -> None:
    """I1: all six parts are built (no "not built yet"); the needles part passes after a whole
    day of every part, and masking off (Part A's card check, Part D's receipt mask) fails it."""
    r = subprocess.run(
        [sys.executable, str(RUN), "--mock"], capture_output=True, text=True, timeout=300
    )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    report = json.loads((HERE / "report.json").read_text())
    ids = {x["id"] for x in report["results"]}
    assert not any(i.endswith(":not_built_yet") for i in ids)
    assert {"needles:card-number-nowhere", "needles:the-day-happened"} <= ids
    control = report["negative_control"]
    assert control["parts_not_built"] == []
    assert set(control["failed_cases"]) == set(PARTS)
    assert "needles:card-number-nowhere" in control["failed_cases"]["needles"]


def test_the_suite_is_gated_in_run_all_mock() -> None:
    text = (ROOT / "evals" / "run_all_mock.py").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if '"r11_helpers (gated)"' in x)
    assert 'HERE / "r11_helpers" / "run.py"' in line and line.rstrip().endswith("True),")
