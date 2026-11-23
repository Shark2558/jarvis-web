# tests/test_r63_c_static.py -- R6.3 Part C (docs/plans/r6-3-book-content.md D0, D6, D7, D14;
# BRIEF-C section 2): the static rules of the console files of Part C (and test_book_static.py).
# - The look does not change: every class C's files put on an element is one the console's own
#   style sheets already define (or one of I0's three host boxes); no colour, font, radius or
#   shadow literal; no new style sheet.
# - The YES box: the page never types YES itself and sends exactly what was typed (one place reads
#   the box); rupees only (no "$" in a literal).
# - Storage: `jarvis_book_place_v1` is the only key C keeps across visits, and never the token; the
#   full book's routes carry the book session (`booked(...)`), the writer's never do.
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"
WRITER, PAGES, READER = "console-book-writer.js", "console-book-pages.js", "console-book-reader.js"
MINE = (WRITER, PAGES)
LIMITS = {WRITER: 400, PAGES: 400, READER: 270}
I0_HOSTS = {"bk-wtop", "bk-writer", "bk-pages"}  # console-book.js makes these boxes (seam 8)
LITERAL = re.compile(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _console_css() -> str:
    html = _read("console.html")
    sheets = re.findall(r'<link rel="stylesheet" href="/static/([^"]+\.css)">', html)
    assert "console-book.css" in sheets and "console.css" in sheets
    return "\n".join(_read(s) for s in sheets)


def _classes_used(text: str) -> set[str]:
    found: set[str] = set()
    for m in re.finditer(r"\bmk\(\s*'[a-z0-9]+'\s*,\s*'([^']*)'", text):
        found.update(m.group(1).split())
    for m in re.finditer(r"className\s*=\s*'([^']*)'", text):
        found.update(m.group(1).split())
    for m in re.finditer(r"classList\.(?:add|toggle)\(\s*'([^']*)'", text):
        found.update(m.group(1).split())
    for m in re.finditer(r"\bcls\s*\(\s*'([^']*)'", text):  # a helper that picks a class by state
        found.update(m.group(1).split())
    return found


@pytest.mark.parametrize("name", [*MINE, READER])
def test_sizes_and_ascii(name: str) -> None:
    text = _read(name)
    assert text.isascii(), name
    assert len(text.splitlines()) <= LIMITS[name], name


@pytest.mark.parametrize("name", MINE)
def test_the_stubs_are_replaced(name: str) -> None:
    text = _read(name)
    assert "settings: () => {}" not in text and "mount: () => {}" not in text, name
    assert "Object.freeze({" in text, name


@pytest.mark.parametrize("name", MINE)
def test_only_classes_the_console_already_styles(name: str) -> None:
    """D0 and the owner's standing rule: new parts are built from existing pieces only."""
    css = _console_css()
    defined = set(re.findall(r"\.([a-zA-Z][\w-]*)", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))
    used = _classes_used(_read(name))
    assert used, name
    assert sorted(used - defined - I0_HOSTS) == [], name


@pytest.mark.parametrize("name", MINE)
def test_no_style_literal_and_no_new_sheet(name: str) -> None:
    text = _read(name)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b['\"]", text), name
    assert ".style." not in text and "style=" not in text and "cssText" not in text, name
    assert "<link" not in text and ".css'" not in text, name


@pytest.mark.parametrize("name", [*MINE, READER])
def test_rupees_only(name: str) -> None:
    for lit in LITERAL.findall(_read(name)):
        assert "$" not in re.sub(r"\$\{", "", lit), (name, lit[:60])


def test_the_yes_box_is_read_in_one_place_and_never_filled_by_the_page() -> None:
    text = re.sub(r"^\s*//.*$", "", _read(WRITER), flags=re.M)  # the code, not its comments
    assert text.count("go(inp.value)") == 1  # what he typed, exactly, as typed
    assert re.findall(r"\btyped:\s*([\w.]+)", text) == ["typed", "typed"]  # the pick and a run
    assert not re.search(r"['\"`]YES['\"`]", text)  # the page never types YES
    assert not re.search(r"inp\.value\s*=\s*['\"`][^'\"`]", text)  # never pre-filled
    assert ".trim()" not in re.sub(r"//.*", "", text.split("go(inp.value)")[0][-400:])


def test_the_place_is_the_only_kept_key_and_never_the_token() -> None:
    for name in MINE:
        text = _read(name)
        keys = set(re.findall(r"localStorage\.\w+\(\s*([A-Z_]+|'[^']*')", text))
        assert keys <= {"PLACE"}, (name, keys)
        if keys:
            assert "PLACE = 'jarvis_book_place_v1'" in text, name
        for line in text.splitlines():
            if "localStorage" in line:
                assert "token" not in line.lower(), (name, line)


def test_the_full_book_rides_the_book_session_and_the_writer_never_does() -> None:
    pages, writer = _read(PAGES), _read(WRITER)
    calls = re.findall(r"\bD\.api\(([^;]*)", pages)
    assert calls and all("D.booked()" in c for c in calls), calls
    assert "booked(" not in writer and "X-Jarvis-Book" not in writer


def test_the_reader_asks_the_full_book_for_g4_only() -> None:
    reader = _read(READER)
    assert reader.count("JarvisBookPages") == 1
    assert re.search(r"JarvisBookPages[^\n]*\.more\(", reader)
