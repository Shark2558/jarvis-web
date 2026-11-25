# tests/test_r63_c_static.py -- R6.3 Part C (docs/plans/r6-3-book-content.md D0, D6, D7, D14;
# BRIEF-C section 2): the static rules of the console files of Part C (and test_book_static.py).
# - The sections reader (`console-book-reader.js`) stays ASCII, within its size, rupees only (no
#   "$" in a literal).
# - R6.4 D1 (docs/plans/r6-4-book-look.md): the in-panel full book (`console-book-pages.js`) is
#   gone: the full book reads on its own page, /book/read (tests/browser/test_r64_a_reader.py), so
#   the panel loads no full-book module and the sections reader no longer adds R6.3 G4's "+N more
#   in the full book" line. Its rules (place merge, ids only, the book session) moved with it.
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"
READER = "console-book-reader.js"
LIMIT = 270
LITERAL = re.compile(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_the_reader_is_ascii_and_within_its_size() -> None:
    text = _read(READER)
    assert text.isascii()
    assert len(text.splitlines()) <= LIMIT


def test_rupees_only() -> None:
    for lit in LITERAL.findall(_read(READER)):
        assert "$" not in re.sub(r"\$\{", "", lit), lit[:60]


def test_the_in_panel_full_book_is_gone() -> None:
    assert not (STATIC / "console-book-pages.js").exists()
    for name in (READER, "console-book.js"):
        text = _read(name)
        assert "JarvisBookPages" not in text and "console-book-pages" not in text, name
    assert "more in the full book" not in _read(READER).replace('"+N more in the full book"', "")
