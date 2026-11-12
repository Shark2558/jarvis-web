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
    # the security review's (H1, H2, M1, M2): the cases the fix added
    "flag_false_but_the_description_names_someone",
    "lower_and_all_caps_names_stay_out",
    "a_name_holding_a_thing_word_is_neither_shown_nor_searched",
    "invented_caption_is_only_an_offer_with_its_line",
    "main_brain_research_person_on_a_picture_turn",
    "main_brain_web_query_on_a_picture_turn",
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
    assert "turn_guard_off" in look.CONTROLS
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


async def _failures_with(look: ModuleType, control: str) -> dict[str, list[str]]:
    look._active.add(control)
    try:
        return {r["id"]: r["failures"] for r in await look._run()}
    finally:
        look._active.clear()


async def test_open_all_put_back_fails_by_what_one_press_does(look: ModuleType) -> None:
    """Code review M3: the O8 case presses "Open next" on a real run of the script; the control
    fails because one press opens every profile through window.open, not by a string match."""
    failures = (await _failures_with(look, "open_all_back"))[
        "look:profile_cards_open_one_tab_a_click"
    ]

    n = len(look.LINKS)
    assert f"window.open was called {n * n} times" in failures  # each press opened all of them
    assert any(f.startswith('"Open next" does not open exactly one card a press') for f in failures)


async def test_with_the_turn_guard_off_the_eval_catches_a_face_name_researched(
    look: ModuleType,
) -> None:
    failures = await _failures_with(look, "turn_guard_off")

    brain = failures["look:main_brain_research_person_on_a_picture_turn"]
    assert any(f.startswith("a name from a face was researched") for f in brain)
    web = failures["look:main_brain_web_query_on_a_picture_turn"]
    assert any(f.startswith("a query carrying a person went out") for f in web)


async def test_with_the_picture_guard_off_a_flag_that_lies_is_caught(look: ModuleType) -> None:
    failures = await _failures_with(look, "guard_off")

    lied = failures["look:flag_false_but_the_description_names_someone"]
    assert any(f.startswith("the name got through") for f in lied)
    caps = failures["look:lower_and_all_caps_names_stay_out"]
    assert len(caps) == 2  # the lower-case one and the ALL CAPS one
    things = failures["look:a_name_holding_a_thing_word_is_neither_shown_nor_searched"]
    assert things and all(f.startswith("shown") for f in things)


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
