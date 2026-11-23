# tests/test_r63_d_static.py -- R6.3 part D (docs/plans/r6-3-book-content.md D9, D14):
# console-book-tour.js, the tour's hooks on the show page. At most 300 lines, ASCII; the chapters
# menu names each scene's full-book chapter by the full book's own titles (facts_model.CHAPTERS,
# gen/modules.MODULES: this test keeps the page's table equal to them); the place it keeps is
# `jarvis_book_place_v1` only (ids only), and no line of the tour is typed into it.
from __future__ import annotations

import re
from pathlib import Path

from jarvis.buildbook.facts_model import CHAPTERS
from jarvis.buildbook.gen import modules, tour

JS = Path(__file__).resolve().parents[1] / "src/jarvis/api/static/console-book-tour.js"
TEXT = JS.read_text(encoding="utf-8")
_ENTRY = re.compile(r"(pg_[a-z0-9_]+): '((?:[^'\\]|\\.)*)'")


def test_the_file_is_ascii_and_at_most_300_lines() -> None:
    assert TEXT.isascii() and len(TEXT.splitlines()) <= 300


def test_the_chapter_names_are_the_full_books_titles() -> None:
    block = re.search(r"CHAPTER_NAMES = Object\.freeze\(\{(.*?)\}\);", TEXT, re.S)
    assert block
    table = {k: v.replace("\\'", "'") for k, v in _ENTRY.findall(block.group(1))}
    want = {f"pg_chapter_{cid}": title for cid, title in CHAPTERS}
    want |= {f"pg_module_{m.id}": m.title for m in modules.MODULES}
    assert table == want
    used = {s.chapter for s in tour.load_script().scenes} - {""}
    assert used <= set(table)


def test_the_place_is_the_one_book_key_and_ids_only() -> None:
    assert re.findall(r"'(jarvis_[a-z_0-9]+)'", TEXT) == ["jarvis_book_place_v1"]
    assert "sessionStorage" not in TEXT  # the show's token stays the show's (console-book-show.js)
    assert "JSON.stringify(" in TEXT and ".text" not in TEXT  # it never keeps a line's words


def test_no_tour_line_is_typed_into_the_page() -> None:
    for scene in tour.load_script().scenes:
        for beat in scene.beats:
            for part in re.split(r"\{\{[a-z0-9_.]+\}\}|\{h\}", beat.text):
                frag = part.strip(" .,:;")
                if len(frag) >= 18:
                    assert frag not in TEXT, (beat.id, frag)
