# evals/r13_1/figure.py
"""R13.1 eval, Part B (`figure`, BUILT): the 3D figure (docs/plans/r13-1-try-on.md D2, D3, D5-D9,
"Tests and evals"), checked on the COMMITTED release folder (static/vendor/mannequin/m1), mock
only, without a browser:

- in Python: the manifest's sums, licences, source and the 3.5 MB budget; the measure table (12
  slider ends and 4 mid points: each measurement changed alone within 0.5 cm, every case's others
  within 3.5 cm, the written file within 0.2 cm of the float build);
- in Node, through the console's own GLB reader and the engine's own plan() and model
  (tests/fixtures/r13_1/b_check.mjs): the file re-measured with its measure rig, and the body
  that is DRAWN measured itself (its height; the rig is made of its points); the reader's
  refusals (an unknown accessor type); the private zone covered in every layer state x slot set x
  variant x view; AVT-07's geometry; tucked/untucked and open/closed; AVT-02, 03, 05, 06, 08, 09,
  10, 11, 14, 15's halves; triangles <= 32,000 a figure; the governor replayed on a fast laptop
  (key taps, a slow drag) and on a slow device.

Negative controls (each must turn its own case red; `control()` re-runs the Node cases with each
applied and names what failed): two morphs swapped (the measure table); `waist_down` dropped
(waist 62 reads 63.9); the base shorts dropped in "All" (the privacy walk); the blazer sleeve 2 cm
longer (AVT-07); and the rows' own: Side returns Front's yaw (AVT-02), Back resets the tuck
(AVT-08), the closed jacket is the open one (AVT-10); the rig's top and floor taken before the
head is softened, as the first build did (the drawn figure's height, review B-1 finding 1); the
governor fed the gap between two frames instead of a frame's cost (a fast laptop is retired by
key taps, finding 2)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from r131_fakes_b import (  # noqa: E402
    manifest,
    manifest_problems,
    measure_problems,
    node_cases,
)

PART = "figure"
BUILT = True
WANTED: dict[str, str] = {  # control -> the case it must turn red
    "swap_morphs": "measure_table",
    "no_waist_down": "measure_table",
    "no_shorts": "private_zone_is_covered_in_every_layer_state_slot_set_variant_and_view",
    "long_sleeve": "avt07_a_blazer_covers_the_shirt_but_not_its_collar_or_the_watch",
    "side_is_front": "avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views",
    "back_resets_tuck": "avt08_front_to_back_keeps_the_same_pieces_layers_and_figure",
    "closed_is_open": "avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket",
    "unsoftened_rig": "drawn_figure_measures_what_was_typed",
    "input_cadence": "governor_judges_render_cost_not_input_cadence",
}


def _case(name: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures[:12]}


def _python_cases() -> list[dict[str, Any]]:
    man = manifest()
    return [
        _case("manifest_sums_licences_and_budget", manifest_problems()),
        _case(
            "measure_table_in_the_manifest",
            measure_problems(man["measure"], man["sample"], man["sliders"]),
        ),
    ]


def _node(control: str) -> list[dict[str, Any]]:
    return [
        {"id": c["id"], "passed": bool(c["passed"]), "failures": list(c["failures"])}
        for c in node_cases(control).values()
    ]


async def cases() -> list[dict[str, Any]]:
    node = await asyncio.to_thread(_node, "none")
    return [*_python_cases(), *node]


async def control() -> dict[str, Any]:
    """Each control applied in turn: the suite fails only when EVERY control turned its case red."""
    failed: dict[str, list[str]] = {}
    missed: list[str] = []
    for name, case in WANTED.items():
        got = await asyncio.to_thread(_node, name)
        red = [c["id"] for c in got if not c["passed"]]
        failed[name] = red
        if f"{PART}:{case}" not in red:
            missed.append(name)
    return {
        "name": "figure: " + ", ".join(WANTED),
        "suite_failed": not missed,
        "failed_cases": failed,
        "controls_that_failed_nothing": missed,
    }
