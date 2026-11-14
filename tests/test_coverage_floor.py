# tests/test_coverage_floor.py -- coverage measured, and ratcheted towards ECC's 80 % (plan D17).
# CI's unit job on Python 3.12 runs pytest with `--cov=jarvis`, writes `coverage.json`, and
# `scripts/coverage_floor.py` writes the total to the job summary and fails only when the total
# drops below the committed floor (`scripts/coverage_floor.txt`); the 3.11 job runs without it.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coverage_floor.py"
FLOOR = ROOT / "scripts" / "coverage_floor.txt"


def _report(tmp_path: Path, percent: float) -> Path:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"totals": {"percent_covered": percent}}), encoding="utf-8")
    return path


def _run(tmp_path: Path, percent: float, floor: str) -> subprocess.CompletedProcess[str]:
    floor_file = tmp_path / "floor.txt"
    floor_file.write_text(floor, encoding="utf-8")
    summary = tmp_path / "summary.md"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--json", str(_report(tmp_path, percent)),
         "--floor", str(floor_file), "--summary", str(summary)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_a_total_at_or_above_the_floor_passes_and_is_written_to_the_summary(
    tmp_path: Path,
) -> None:
    got = _run(tmp_path, 71.46, "71\n")
    assert got.returncode == 0, got.stdout + got.stderr
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "71.46 %" in summary and "floor 71 %" in summary and "80 %" in summary


def test_a_total_below_the_floor_fails(tmp_path: Path) -> None:
    got = _run(tmp_path, 70.99, "71\n")
    assert got.returncode == 1
    assert "below the floor" in got.stdout


@pytest.mark.parametrize("floor", ["", "abc", "-1", "101"])
def test_a_floor_that_is_not_a_percentage_is_an_error(tmp_path: Path, floor: str) -> None:
    assert _run(tmp_path, 70.0, floor).returncode == 2


def test_a_missing_report_is_an_error(tmp_path: Path) -> None:
    got = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", str(tmp_path / "none.json"), "--floor", str(FLOOR)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert got.returncode == 2


def test_the_committed_floor_is_a_whole_percentage_below_eighty() -> None:
    value = int(FLOOR.read_text(encoding="utf-8").strip())
    assert 0 < value <= 80


def test_ci_measures_coverage_on_312_only_and_checks_the_floor() -> None:
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = ci["jobs"]["test"]["steps"]
    runs = [(s.get("if", ""), s.get("run", "")) for s in steps]
    plain = [cond for cond, run in runs if run.strip() == "pytest -q"]
    assert plain == ["matrix.python == '3.11'"]  # the 3.11 job is not slowed
    cov = [(c, r) for c, r in runs if "--cov=jarvis" in r]
    assert len(cov) == 1 and cov[0][0] == "matrix.python == '3.12'"
    assert "--cov-report=term-missing:skip-covered" in cov[0][1]
    assert "--cov-report=json" in cov[0][1]
    check = [(c, r) for c, r in runs if "coverage_floor.py" in r]
    assert len(check) == 1 and check[0][0] == "matrix.python == '3.12'"
    assert "GITHUB_STEP_SUMMARY" in check[0][1]


def test_pytest_cov_is_in_the_dev_extra() -> None:
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = data["project"]["optional-dependencies"]["dev"]
    assert any(d.startswith("pytest-cov>=") for d in dev)
