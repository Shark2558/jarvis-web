# tests/test_r11_1_d_eval.py -- R11.1 Part D: the eval (evals/r11_1/look.py) is itself checked.
# Every case passes on the real code; each negative control breaks exactly the cases it must (a
# control that breaks everything proves as little as one that breaks nothing); with the picture
# guard removed the eval catches a NAME and a search for the person; a run leaves no control
# switched on and logging as it found it.
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLAN_CASES = (  # plan "Tests and evals per part", row D, and D21-D
    "profile_cards_open_one_tab_a_click",
    "product_researched",
    "landmark_researched",
    "label_researched",
    "logo_researched",
    "person_described_not_named_not_searched",
    "uncaptioned_face_no_name_no_search",
    "caption_names_a_public_figure_offer_then_the_gate",
    "typed_names_meet_the_unchanged_gate",
    "home_camera_watcher",
    "home_messenger",
    "github_one_read_in_six_hours",
)


@pytest.fixture(scope="module")
def look() -> ModuleType:
    """The part's eval, loaded by path as the runner loads it."""
    path = ROOT / "evals" / "r11_1" / "look.py"
    spec = importlib.util.spec_from_file_location("r11_1_look_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_part_is_built_and_holds_every_case_the_plan_lists(look: ModuleType) -> None:
    assert (look.PART, look.BUILT) == ("look", True)
    assert set(PLAN_CASES) <= set(look.CASES)
    assert set(look.EXPECTED) == set(look.CONTROLS) >= {"guard_off", "fault_map_empty"}
    assert all(look.EXPECTED[name] <= set(look.CASES) for name in look.CONTROLS)


async def test_every_case_passes_on_the_real_code(
    look: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    results = await look.cases()

    assert [r for r in results if not r["passed"]] == []
    assert [r["id"] for r in results] == [f"look:{name}" for name in look.CASES]
    assert capsys.readouterr().out.startswith(f"look: {len(look.CASES)} cases")


async def test_each_control_breaks_exactly_its_own_cases(look: ModuleType) -> None:
    verdict = await look.control()

    assert verdict["suite_failed"] is True
    for name in look.CONTROLS:
        broke = set(verdict["failed_cases"][name])
        assert broke == {f"look:{case}" for case in look.EXPECTED[name]}, name


async def test_with_the_guard_removed_the_eval_catches_a_name(look: ModuleType) -> None:
    look._active.add("guard_off")
    try:
        failures = {r["id"]: r["failures"] for r in await look._run()}
    finally:
        look._active.clear()

    named = failures["look:eyes_that_name_the_face_get_nowhere"]
    assert any(f.startswith("the name got through") for f in named)
    assert any(f.startswith("a web search carried the person") for f in named)
    offered = failures["look:uncaptioned_face_no_name_no_search"]
    assert "a name was offered although the picture has no text" in offered


async def test_a_control_that_breaks_nothing_does_not_count(
    look: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(look.EXPECTED, "guard_off", {"product_researched"})  # it never breaks it

    assert (await look.control())["suite_failed"] is False


async def test_a_run_leaves_no_control_on_and_logging_as_it_was(look: ModuleType) -> None:
    before = logging.root.manager.disable

    await look.control()

    assert look._active == set()
    assert logging.root.manager.disable == before
