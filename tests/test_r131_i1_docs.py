# tests/test_r131_i1_docs.py -- R13.1 I1 (I0-NOTES section 5 item 5; plan D17): the guide says what
# was built. C72 and C73 are built and joined, no longer PLANNED; C63's pixel sentence names the
# third panel ("Three panels see pixels: Camera, Camera -> Wardrobe and Try-on's own photo check");
# the guide's version moves with it. Written red first.
from __future__ import annotations

from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "JARVIS-Architecture.md"


def _card(text: str, title: str) -> str:
    start = text.index(title)
    return text[start : text.index("\n#### ", start + 1)]


def test_the_guide_is_v13_1_5_with_its_change_log_row() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    # R6.3 I0: the guide moved on (v6.3.1, tests/test_r63_seams.py); R13.1's row stays in its log
    assert text.splitlines()[0].startswith("Version v6.3.")
    assert "| v13.1.5 | 18 Nov 2026, 06:15 IST | R13.1 |" in text
    assert "| v6.3." in text.splitlines()[-1]


def test_c73_says_the_role_fails_closed_and_the_risk_it_leaves() -> None:
    """I1's security review L5: the prompt-only role, never a broader one, and the residual risk
    (prompts to any Agent Platform model) with the budget alert as the outside brake."""
    c73 = _card(GUIDE.read_text(encoding="utf-8"), "#### C73 · See it on me (R13.1)")
    for words in ("only `aiplatform.endpoints.predict`", "never a broader role",
                  "any Agent Platform model", "outside JARVIS's cap", "`300INR`"):  # fmt: skip
        assert words in c73, words


def test_c72_and_c73_are_built_and_joined_not_planned() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    for title in ("#### C72 · Try-on figure (R13.1)", "#### C73 · See it on me (R13.1)"):
        card = _card(text, title)
        assert "PLANNED" not in card, title
        assert "joined at I1, v13.1.0; not yet deployed" in card, title
    assert "C72 Try-on figure, C73 See it on me (R13.1)" in text
    assert "(C72, C73, PLANNED)" not in text
    c72 = _card(text, "#### C72 · Try-on figure (R13.1)")
    for name in ("looks.py", "confirm.py", "scripts/mannequin/", "vendor/mannequin/m1/", "e2e.py"):
        assert name in c72, name
    c73 = _card(text, "#### C73 · See it on me (R13.1)")
    assert "tryon_gemini.py" in c73 and "cap.py" in c73 and "FIXED_WORDS" in c73


def test_c63_names_three_panels_that_see_pixels() -> None:
    c63 = _card(GUIDE.read_text(encoding="utf-8"), "#### C63 · Camera and vision engine (R7)")
    assert "Three panels see pixels: Camera, Camera → Wardrobe and Try-on's own photo check" in c63
    assert "Two panels see pixels" not in c63
