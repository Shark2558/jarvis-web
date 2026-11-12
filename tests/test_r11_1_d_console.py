# tests/test_r11_1_d_console.py -- R11.1 Part D: static checks on the console pieces (the real
# behaviour is tests/browser/test_r11_1_d_look.py). O8: each profile is a card with its own real
# link and "Open next"; "Open all" is gone and no `window.open` result is ever counted. O11: a
# token being read says "Checking..." on its chip. Every module is ASCII, `textContent` only, and
# its stylesheet only places things (plan D0).
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"


def _src(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# ---- O11: the Vitals chip ------------------------------------------------------------------------
def test_a_row_that_is_being_read_says_checking_on_its_chip() -> None:
    js = _src("console-vitals.js")
    assert "checking: o.checking === true" in js  # only the server's own flag
    assert "'Checking\\u2026'" in js and "chip(it.status, it.checking)" in js
    assert js.isascii() and len(js.splitlines()) <= 400


def test_a_checking_board_is_read_again_by_itself_a_few_times_only() -> None:
    js = _src("console-vitals.js")
    assert re.search(r"FOLLOW_MAX = [1-5]\b", js) and "FOLLOW_MS = " in js
    assert "S.follows < FOLLOW_MAX" in js and "clearTimeout(S.followTimer)" in js
