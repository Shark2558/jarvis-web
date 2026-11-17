# tests/test_r131_b_figure.py -- R13.1 Part B (docs/plans/r13-1-try-on.md D2, D3, D5-D9): the 3D
# figure's files and engine, checked without a browser. The committed release folder (static/vendor/
# mannequin/m1) is read in pure Python (its manifest, sums, licences, budget, measure table) and,
# through the console's own reader and the engine's own plan() and model, in Node (tests/fixtures/
# r13_1/b_check.mjs: the measure rig, the private zone's walk, AVT-07's geometry, the views). Each
# of the owner's rows that Part B carries has its named test; each negative control of the `figure`
# eval is proved here to turn its case red. Node missing is an error, never a skip.
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from r131_fakes_b import (
    BUDGET_BYTES,
    CONTROLS,
    FIXTURES,
    M1,
    POKE,
    STATIC,
    manifest,
    manifest_problems,
    measure_problems,
    node_cases,
)  # fmt: skip


def _passed(name: str, control: str = "none") -> None:
    case = node_cases(control)[name]
    assert case["passed"], case["failures"]


def _failed(name: str, control: str) -> list[str]:
    case = node_cases(control)[name]
    assert not case["passed"], f"{control} did not turn {name} red"
    failures: list[str] = case["failures"]
    return failures


# ---- the release folder --------------------------------------------------------------------------
def test_the_manifest_lists_every_file_with_its_sum_licence_source_and_changes() -> None:
    assert manifest_problems() == []
    man = manifest()
    assert set(man["files"]) == {
        "body.glb", "garments.glb", "LICENSE-mpfb2-CC0.txt", "LICENSE-anny-Apache-2.0.txt",
        "NOTICE-mannequin.txt",
    }  # fmt: skip
    assert man["release"] == "m1" and man["sole"] == 0.016
    assert man["sliders"] == ["height", "shoulders", "chest", "waist", "hips", "inseam"]
    assert man["morphs"] == [*man["sliders"], "waist_down"]


def test_the_body_files_licence_names_the_waist_loops_origin() -> None:
    """Review B-1, finding 12: body.glb carries the measure rig, whose waist points are in the
    order of Anny's Apache-2.0 loop; its manifest entry named CC0 alone."""
    files = manifest()["files"]
    assert files["body.glb"]["licence"] == (
        "CC0-1.0 (MakeHuman/MPFB2 assets); measure rig: the order of Anny's waist loop "
        "(Apache-2.0, NAVER Corp.); see NOTICE-mannequin.txt"
    )
    assert files["garments.glb"]["licence"] == (
        "CC0-1.0 (MakeHuman/MPFB2 assets); see NOTICE-mannequin.txt"
    )


def test_white_socks_over_white_trainers_no_longer_read_as_boots() -> None:
    _passed("socks_and_shoes_read_as_two_things")


def test_the_release_is_within_three_and_a_half_megabytes() -> None:
    total = sum(p.stat().st_size for p in M1.rglob("*") if p.is_file())
    assert total <= BUDGET_BYTES, total
    assert manifest()["files"]["body.glb"]["bytes"] <= int(1.6 * 1024 * 1024)  # the first load


def test_a_changed_file_a_missing_licence_or_a_fat_release_is_named(tmp_path: Path) -> None:
    for p in M1.iterdir():
        (tmp_path / p.name).write_bytes(p.read_bytes())
    assert manifest_problems(tmp_path) == []
    (tmp_path / "body.glb").write_bytes(b"x" + (tmp_path / "body.glb").read_bytes()[1:])
    assert any("body.glb: its sum" in p for p in manifest_problems(tmp_path))
    (tmp_path / "LICENSE-mpfb2-CC0.txt").write_text("another licence")
    assert any("the licence text is missing or changed" in p for p in manifest_problems(tmp_path))
    (tmp_path / "extra.bin").write_bytes(b"\0" * BUDGET_BYTES)
    probs = manifest_problems(tmp_path)
    assert any("over the 3.5 MB budget" in p for p in probs) and any(
        "the folder holds" in p for p in probs
    )


def test_the_measure_table_holds_each_alone_within_half_a_centimetre() -> None:
    man = manifest()
    rows = man["measure"]
    assert measure_problems(rows, man["sample"], man["sliders"]) == []
    assert [r["case"] for r in rows][:3] == ["sample", "height min", "height max"] and len(
        rows
    ) == 19
    waist_min = next(r for r in rows if r["case"] == "waist min")
    assert abs(waist_min["got"][3] - 62) <= 0.5  # H3: the waist below the sample (v2 read 63.9)
    worst = max(abs(g - w) for r in rows for g, w in zip(r["got"], r["want"], strict=True))
    assert worst <= 3.5
    bad = [dict(rows[1], got=[150.0, 44.0, 99.3, 83.2, 96.7, 74.9])]
    moved = abs(74.9 - rows[1]["float"][5])
    assert measure_problems(bad, man["sample"], man["sliders"]) == [
        "height min: inseam wanted 79, measured 74.9 (limit 3.5)",
        f"height min: inseam moved {moved:.2f} cm when quantised",
    ]
    wide = [dict(rows[0], got=[172.0, 44.0, 96.6, 82.0, 96.0, 79.0])]
    assert measure_problems(wide, man["sample"], man["sliders"]) == [
        "sample: chest wanted 96, measured 96.6 (limit 0.5)",
        "sample: chest moved 0.60 cm when quantised",
    ]


def test_the_server_serves_the_models_and_never_the_manifest_or_a_licence() -> None:
    from jarvis.api.tryon_assets import RELEASE, mannequin_files

    mannequin_files.cache_clear()
    assert dict(mannequin_files(RELEASE)) == {
        "body.glb": "application/octet-stream", "garments.glb": "application/octet-stream",
    }  # fmt: skip


def test_the_engine_names_the_two_files_of_the_release() -> None:
    js = (STATIC / "console-tryon-3d.js").read_text(encoding="utf-8")
    assert "const FILES = ['body.glb', 'garments.glb'];" in js
    assert "'./console-tryon-glb.js'" in js and "'./console-tryon-cloth.js'" in js  # pinned loads
    assert "window.JarvisTryOn3D = engine" in js


def test_the_three_modules_keep_their_sizes_and_the_rules_of_a_drawing_module() -> None:
    limits = {
        "console-tryon-3d.js": 600,
        "console-tryon-glb.js": 200,
        "console-tryon-cloth.js": 300,
    }
    camera_words = (
        "getUser" + "Media",
        "getDisplay" + "Media",
        "Image" + "Capture",
        "facing" + "Mode",
    )
    for name, limit in limits.items():
        text = (STATIC / name).read_text(encoding="utf-8")
        assert len(text.splitlines()) <= limit, name
        for word in camera_words:  # R7's eval reads comments too
            assert word not in text, (name, word)
        assert text.isascii(), name
    glb = (STATIC / "console-tryon-glb.js").read_text(encoding="utf-8")
    for api in ("drawImage", "toBlob", "createImageBitmap", "getContext", "fetch(", "document."):
        assert api not in glb, api  # the reader touches no pixel, no network, no page


# ---- the figure, in Node (the console's own reader, plan and model) ------------------------------
def test_the_glb_reader_refuses_an_unknown_accessor_type_and_other_files() -> None:
    _passed("glb_reader_refuses_what_is_outside_the_subset")


def test_the_glb_reader_refuses_malformed_files_instead_of_reading_them() -> None:
    """Review B-1, finding 3: offsets outside the BIN chunk (NaN points, or the JSON chunk's
    bytes), a scale that is not numbers, a stride, a cut triangle, a NaN UV, `__proto__` as a
    name, one name twice (in a file or across the two)."""
    _passed("glb_reader_refuses_malformed_files")
    js = (STATIC / "console-tryon-3d.js").read_text(encoding="utf-8")
    assert "join((await Promise.all(FILES.map(" in js and "Object.assign(meshes" not in js


def test_every_part_has_the_seven_morphs_and_the_templates_are_the_manifests() -> None:
    _passed("every_part_has_the_seven_morphs_and_the_templates_are_the_manifests")


def test_the_written_files_measure_what_the_manifest_says() -> None:
    _passed("measure_table")


def test_avt03_shape_typing_178_makes_the_figure_178_centimetres() -> None:
    _passed("avt03_shape_height_178")  # the height of the body that is DRAWN, not of the rig


def test_the_drawn_figure_measures_what_was_typed_and_the_rig_is_made_of_its_points() -> None:
    """Review B-1, finding 1: the figure on screen was 1.0-1.7 cm shorter than the rig beside it."""
    _passed("drawn_figure_measures_what_was_typed")
    facts = node_cases()["drawn_facts"]
    assert facts["drawn_height_own_cm"] <= 0.5 and facts["rig_off_drawn_mm"] <= 1.0


def test_the_private_zone_is_covered_in_every_layer_state_slot_set_variant_and_view() -> None:
    _passed("private_zone_is_covered_in_every_layer_state_slot_set_variant_and_view")


def test_avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views() -> None:
    _passed("avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views")


def test_avt05_template_colour_and_texture_are_named_approximate() -> None:
    _passed("avt05_template_colour_and_texture_are_named_approximate")


def test_avt06_swapping_the_watch_changes_the_left_wrist_and_its_thumbnail() -> None:
    _passed("avt06_swapping_the_watch_changes_the_left_wrist")


def test_avt07_a_blazer_covers_the_shirt_but_not_its_collar_or_the_watch() -> None:
    _passed("avt07_a_blazer_covers_the_shirt_but_not_its_collar_or_the_watch")


def test_avt08_front_to_back_keeps_the_same_pieces_layers_and_figure() -> None:
    _passed("avt08_front_to_back_keeps_the_same_pieces_layers_and_figure")


def test_avt09_redraw_a_swap_changes_only_that_slot() -> None:
    _passed("avt09_redraw_a_swap_changes_only_that_slot")


def test_avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket() -> None:
    _passed("avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket")


def test_a_shirt_over_a_wrap_says_it_is_drawn_tucked_instead_of_ignoring_the_choice() -> None:
    """Review B-1, finding 4: `tucked: false` over a mundu was dropped in silence; show() now
    answers `forced: {top: 'tucked'}` and names `tuck` in that slot's `approx`."""
    _passed("a_top_over_a_wrap_says_it_is_drawn_tucked")


def test_avt11_a_formal_and_a_festive_look_compare_with_both_lists_and_their_readiness() -> None:
    _passed("avt11_two_figures_each_with_its_own_slots")  # B's half: two figures, each its slots


def test_avt14_a_shared_look_shows_the_dressed_figure_and_only_approved_details() -> None:
    _passed("avt14_a_private_slot_draws_only_the_covered_base_layer")  # the PNG: the browser test


def test_avt15_signals_without_a_browser_the_engine_says_not_supported() -> None:
    _passed("avt15_signals_without_a_browser")


def test_the_governor_judges_what_a_frame_cost_not_how_often_he_touched_a_key() -> None:
    """Review B-1, finding 2: replays of a fast laptop (key taps at 3 Hz, a slow drag, a 60 fps
    spin: never a step) and of a slow device (60 ms a frame: shadows off, then retired)."""
    _passed("governor_judges_render_cost_not_input_cadence")


def test_no_layer_beneath_shows_through_at_the_sample_or_at_either_end_of_a_slider() -> None:
    """Review B-1, finding 6: the base shorts, a tucked tail and the socks stay under what covers
    them at 15 shapes (inseam 66 too), judged by what an eye would see (a depth buffer in Node).
    Before the fix a level view saw up to 304 cm2 of the base shorts through a wrap (hips 78) and
    84 cm2 through the trousers (inseam 66); the documented limits are capped in the fixture."""
    case = node_cases("none", None, POKE)["no_layer_beneath_shows_through"]
    assert case["passed"], case["failures"]
    assert case["shapes"] == 15 and case["checked"] >= 120
    assert case["worst_level_cm2"] <= 0.6 and case["worst_above_cm2"] <= 22
    assert set(case["known"]) == {"inseam min", "waist max"}  # INTEGRATION-B lists both


def test_trousers_with_half_their_ease_let_the_base_shorts_through() -> None:
    """The control of the case above: the trousers drawn 4 mm inside their own shape."""
    assert "thin_trousers" in CONTROLS
    case = node_cases("thin_trousers", None, POKE)["no_layer_beneath_shows_through"]
    assert not case["passed"]
    assert any("sample: " in f and "the base shows through" in f for f in case["failures"])


def test_a_states_own_answer_to_a_morph_is_a_product_target() -> None:
    _passed("a_states_own_answer_to_a_morph_is_a_product_target")


def test_a_dressed_figure_draws_at_most_32000_triangles_and_two_at_most_64000() -> None:
    _passed("triangles_within_the_budget")
    assert node_cases()["facts"]["worst_triangles"] <= 32000


# ---- the eval's negative controls each turn their own case red ----------------------------------
@pytest.mark.parametrize(
    ("control", "case", "words"),
    [
        ("swap_morphs", "measure_table", "chest min: chest wanted 76 measured 96.00"),
        ("no_waist_down", "measure_table", "waist min: waist wanted 62 measured 63.9"),
        ("no_shorts", "private_zone_is_covered_in_every_layer_state_slot_set_variant_and_view",
         "the base shorts are not drawn"),
        ("long_sleeve", "avt07_a_blazer_covers_the_shirt_but_not_its_collar_or_the_watch",
         "the last centimetre of the shirt cuff is under the blazer sleeve"),
        ("side_is_front", "avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views",
         "side is 0 degrees, not 90"),
        ("back_resets_tuck", "avt08_front_to_back_keeps_the_same_pieces_layers_and_figure",
         "front -> back changed the pieces, the styling state or the weights"),
        ("closed_is_open",
         "avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket",
         "closed: the shirt placket still shows"),
        ("input_cadence", "governor_judges_render_cost_not_input_cadence",
         "an arrow key tapped three times a second: down@5.0,retire@10.3"),
        ("unsoftened_rig", "drawn_figure_measures_what_was_typed",
         "sample: the rig reads 173.3"),
    ],
)  # fmt: skip
def test_each_control_turns_its_case_red(control: str, case: str, words: str) -> None:
    assert control in CONTROLS
    assert any(words in f for f in _failed(case, control)), node_cases(control)[case]["failures"]


def test_a_control_breaks_only_what_it_names() -> None:
    clean = {k for k, c in node_cases().items() if c["passed"]}
    assert len(clean) == len(node_cases())  # without a control every case passes
    for control in ("swap_morphs", "long_sleeve", "side_is_front"):
        red = {k for k, c in node_cases(control).items() if not c["passed"]}
        assert 1 <= len(red) <= 2, (control, red)


# ---- reproducible: with the source at hand, the build measures and counts the same --------------
@pytest.mark.skipif(not os.environ.get("JARVIS_ANNY_DIR"), reason="set JARVIS_ANNY_DIR to rebuild")
def test_a_rebuild_measures_within_a_millimetre_and_counts_the_same_triangles(
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    from r131_fakes_b import mannequin

    mannequin()
    from mannequin import build

    files = build.build(Path(os.environ["JARVIS_ANNY_DIR"]))
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    assert manifest_problems(tmp_path) == []
    drawn = node_cases("none", tmp_path)  # the rebuilt figure, judged as it is drawn
    assert drawn["drawn_figure_measures_what_was_typed"]["passed"], drawn
    new, old = json.loads(files["MANIFEST.json"]), manifest()
    assert new["triangles"] == old["triangles"] and new["templates"] == old["templates"]
    for a, b in zip(new["measure"], old["measure"], strict=True):
        assert a["case"] == b["case"]
        assert max(abs(x - y) for x, y in zip(a["got"], b["got"], strict=True)) <= 0.1, a["case"]


def test_the_fixtures_carry_no_real_piece_or_path() -> None:
    for path in sorted(FIXTURES.glob("b_*.mjs")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"/tmp/|/home/|@[a-z]+\.(?!com\b)", text), path.name
    looks: Any = (FIXTURES / "b_looks.mjs").read_text(encoding="utf-8")
    assert "made-up" in looks
