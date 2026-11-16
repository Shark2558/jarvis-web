# tests/test_r13_i1_docs.py -- R13 I1's words, pinned (docs/plans/r13-wardrobe.md D9, D20, D21; the
# four INTEGRATION "Needs I1" lists): the guide's cards C69-C71 are built (not PLANNED), C63 says
# two panels see pixels and a wardrobe photo is kept only on Save, the camera's Privacy row keeps
# "Never kept: a camera frame" and sends the wardrobe photo to its own row, `wardrobe_restore` is
# his purge count, the key-change note is in the guide, and the plan records the owner's decision
# that a declined calendar event still gets an outfit plan.
from __future__ import annotations

import re
from pathlib import Path

from jarvis.vision import privacy as camera
from jarvis.wardrobe.phone import privacy as wardrobe

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "docs" / "architecture" / "JARVIS-Architecture.md").read_text("utf-8")
PLAN = (ROOT / "docs" / "plans" / "r13-wardrobe.md").read_text("utf-8")


def _card(name: str) -> str:
    start = GUIDE.index(f"#### {name} ")
    return GUIDE[start : GUIDE.index("\n#### ", start + 5)]


def test_the_three_cards_are_built_and_name_no_planned_piece() -> None:
    for name in ("C69", "C70", "C71"):
        card = _card(name)
        assert "PLANNED" not in card, name
        assert "(R13)" in card.splitlines()[0], name


def test_c63_says_two_panels_see_pixels_and_a_photo_is_kept_only_on_save() -> None:
    card = _card("C63")
    for words in (
        "Two panels see pixels: Camera and Camera → Wardrobe. A frame is never stored.",
        "A wardrobe photo is kept only when you press Save, cropped to the piece, after a check "
        "for a person or a face that can miss",
        "the use cases of R8 to R10 receive results only",
    ):
        assert words in card, words


def test_the_camera_row_keeps_its_frame_promise_and_the_photo_has_its_own_row() -> None:
    assert camera.NEVER.startswith("Never kept: a camera frame.")
    assert "its own row" in camera.NEVER
    assert "Wardrobe photos and fingerprints" == wardrobe.PHOTOS_SPEC.label
    assert "Never for a private piece" in wardrobe.PHOTOS_SPEC.what
    assert "can miss" in (wardrobe.PHOTOS_SPEC.note or "")


def test_the_restore_collection_is_his_purge_count() -> None:
    card = _card("C69")
    assert "`wardrobe_restore/{uid}` (his purge count" in card
    assert "1 hour" not in card


def test_the_outfit_plans_have_their_own_privacy_row_and_a_key_change_note() -> None:
    assert wardrobe.PLANS_ID in wardrobe.ROW_IDS and wardrobe.PLANS_SPEC.label == "Outfit plans"
    assert "Your outfit plans can't be opened (JARVIS's key changed)" in GUIDE
    assert "plans only, never his pieces or laundry" in GUIDE


def test_the_plan_records_the_owners_decision_on_declined_events() -> None:
    assert re.search(r"16 Nov.*declined.*event.*(keep|still).*plan", PLAN, re.S | re.I)


def test_the_fixer_words_are_in_the_plan_and_the_guide() -> None:
    """I1 fixes: L2's honest note, the pilot's 'not measured', and the Privacy rule (M1)."""
    for text in (PLAN, GUIDE):
        assert "cannot decode a picture" in text  # the face check is the console's (L2)
        assert "not measured in v13.0.0" in text or "Not measured in\n  v13.0.0" in text
    assert "Couldn't check right now" in PLAN and "delete still erases what is on disk" in PLAN
    assert 'never "Nothing kept yet"' in GUIDE
