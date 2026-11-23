"""The browser suite's split across CI machines (tests/browser/shard_plan.py, 23 Nov 2026)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _plan() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "shard_plan_under_test", ROOT / "tests/browser/shard_plan.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COUNTS = {
    "tests/browser/test_a.py": 120,
    "tests/browser/test_b.py": 40,
    "tests/browser/test_c.py": 35,
    "tests/browser/test_d.py": 30,
    "tests/browser/test_e.py": 9,
    "tests/browser/test_f.py": 1,
}


def test_every_file_lands_on_exactly_one_shard() -> None:
    plan = _plan().assign(COUNTS, 4)
    assert set(plan) == set(COUNTS)
    assert set(plan.values()) <= {1, 2, 3, 4}


def test_the_plan_is_the_same_on_every_machine() -> None:
    reordered = dict(reversed(list(COUNTS.items())))
    assert _plan().assign(COUNTS, 4) == _plan().assign(reordered, 4)


def test_loads_are_balanced_within_the_largest_file() -> None:
    plan = _plan().assign(COUNTS, 4)
    loads = [sum(n for f, n in COUNTS.items() if plan[f] == s) for s in (1, 2, 3, 4)]
    assert max(loads) - min(loads) <= max(COUNTS.values())
    assert sum(loads) == sum(COUNTS.values())


def test_one_shard_takes_everything() -> None:
    assert set(_plan().assign(COUNTS, 1).values()) == {1}


@pytest.mark.parametrize("spec", ["", "1", "0/4", "5/4", "a/4", "1/0", "1/4/2", "-1/4"])
def test_a_bad_shard_spec_is_refused(spec: str) -> None:
    with pytest.raises(ValueError):
        _plan().parse(spec)


def test_a_good_shard_spec_is_read() -> None:
    assert _plan().parse(" 2/4 ") == (2, 4)


def test_ci_runs_four_shards_and_deploy_waits_for_them() -> None:
    ci: dict[str, Any] = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    job = ci["jobs"]["browser"]
    assert job["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    assert job["strategy"]["fail-fast"] is False
    assert job["env"]["JARVIS_BROWSER_SHARD"] == "${{ matrix.shard }}/4"
    assert "browser" in ci["jobs"]["deploy"]["needs"]
