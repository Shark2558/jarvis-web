# tests/test_r81_i1_join.py -- R8.1 I1 join (docs/plans/r8-integration/R81-I1-NOTES.md): the
# seams between the four R8.1 builders and R8's joined engine, on synthetic data only.
#   - the setup channel: the Workout pane's choices reach a use case only through the REAL port
#     core's live(..., {setup}) (S2's contract line from R8's join, r.setup on every Result);
#     builder G's modules read it there (they read a first state {setup} before the join)
#   - the four R8.1 evals are gated in `make eval-mock`
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from r8_fakes import FIXTURES, STATIC, run_node

from jarvis.coach.usecases import parse_tally

ROOT = Path(__file__).resolve().parents[1]
DYNAMIC = FIXTURES / "dynamic_sequences.mjs"
WALL = {"support": "wall"}


def _code(name: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)


# ---- the setup channel through the real driver ----------------------------------------------------
def test_a_handstand_through_the_real_driver_times_nothing_without_a_wall_or_a_spotter() -> None:
    for setup in (None, {}, {"support": "nobody"}, {"stance": "southpaw"}):
        out = run_node(DYNAMIC, "mod.handstandDriver", {"hold": 10, "setup": setup})
        assert out["errors"] == [] and out["frames"] > 100, setup
        assert [t["tally"] for t in out["tallies"]] == [None], setup
        texts = json.dumps(out["tallies"][0]["view"])
        assert "wall" in texts.lower() or "spotter" in texts.lower(), setup


@pytest.mark.parametrize("support", ["wall", "spotter"])
def test_a_handstand_through_the_real_driver_holds_once_the_pane_passes_its_support(
    support: str,
) -> None:
    out = run_node(DYNAMIC, "mod.handstandDriver", {"hold": 10, "setup": {"support": support}})
    assert out["errors"] == []
    assert out["setups"] == [json.dumps({"support": support}, separators=(",", ":"))]
    (one,) = out["tallies"]
    tally = one["tally"]
    assert tally is not None and tally["support"] == support
    assert abs(tally["hold_s"] - 10) <= 1  # row 237: hold time within 1 s
    assert parse_tally("handstand", tally) is not None


def test_g_reads_the_setup_from_each_result_never_from_a_first_state() -> None:
    for name in ("console-coach-handstand.js", "console-coach-agility.js", "console-coach-boxing.js"):
        code = _code(name)
        assert "r.setup" in code, name
        assert "state.setup" not in code, name


def test_the_partner_driver_passes_the_consent_through_the_real_live() -> None:
    src = (FIXTURES / "tests_sequences.mjs").read_text(encoding="utf-8")
    body = src.split("export async function partnerDriver", 1)[1].split("\nexport ", 1)[0]
    assert "setup: setup || undefined" in body
    assert "Object.assign({}, r, { setup })" not in body  # no pass-through stands in for the driver


# ---- the evals ------------------------------------------------------------------------------------
def test_the_four_r81_evals_are_gated_in_the_mock_run() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_all_mock_r81", ROOT / "evals" / "run_all_mock.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    gated: dict[str, Any] = {str(cmd[-1]): g for _, cmd, g in mod.SUITES}
    for part in ("strength", "flow", "dynamic", "care"):
        path = str(ROOT / "evals" / "r8_1" / f"{part}.py")
        assert gated.get(path) is True, part
