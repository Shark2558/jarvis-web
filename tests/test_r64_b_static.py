# tests/test_r64_b_static.py
"""R6.4 builder B (docs/plans/r6-4-book-look.md D7, D11): the chapter player's and the effects
engine's static files keep the Book's rules -- ASCII, at most 400 lines, no HTML sink, imports only
of the console's own modules, no colour of their own (the console's tokens only), nothing kept in
localStorage but the shared place key, and every file served from `READ_ASSETS`. The browser
tests' Vault fixture (`tests/browser/r64_vault_chapter.json`, the compiled chapter and its pages)
must still say what the script `narration/module_vault.md` says."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from jarvis.api.book_read import READ_ASSETS
from jarvis.buildbook.book.narration import load_script

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
MINE = [
    "console-book-chapter.js",
    "console-book-chapter-view.js",
    "console-book-fx.js",
    "console-book-fx-plan.js",
    "console-book-fx-chart.js",
    "console-book-fx-cards.js",
]
SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "createContextualFragment",
    "DOMParser",
    "setHTMLUnsafe",
    "srcdoc",
    "eval(",
    "new Function",
)
FIXTURE = ROOT / "tests/browser/r64_vault_chapter.json"
SCRIPT = ROOT / "src/jarvis/buildbook/book/narration/module_vault.md"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", MINE)
def test_each_file_is_ascii_small_and_has_no_html_sink(name: str) -> None:
    text = _read(name)
    assert text.isascii(), name
    assert len(text.splitlines()) <= 400, name
    assert [s for s in SINKS if s in text] == [], name
    assert not re.search(r"set(?:Timeout|Interval)\(\s*['\"`]", text), name
    assert not re.search(r"setAttribute\(\s*['\"`]on", text), name


@pytest.mark.parametrize("name", MINE)
def test_imports_only_the_consoles_modules_and_no_address(name: str) -> None:
    text = _read(name)
    for target in re.findall(r"^import [^;]*?from ['\"]([^'\"]+)['\"]", text, re.M):
        assert target.startswith("./console-"), (name, target)
    text = text.replace("'http://www.w3.org/2000/svg'", "")
    assert "http://" not in text and "https://" not in text, name


@pytest.mark.parametrize("name", MINE)
def test_no_colour_of_its_own_and_only_the_place_key_kept(name: str) -> None:
    text = _read(name)
    assert re.findall(r"['\"]#[0-9a-fA-F]{3,8}['\"]", text) == [], name  # the console's tokens only
    assert not re.search(r"\b(?:rgb|rgba|hsl|hsla)\(", text), name
    assert not re.search(r"localStorage[^;\n]*jarvis_(?!book_place_v1)", text), name
    if "localStorage" in text:
        assert "'jarvis_book_place_v1'" in text, name


def test_every_player_and_effects_file_is_served() -> None:
    on_disk = {p.name for p in STATIC.glob("console-book-chapter*.js")} | {
        p.name for p in STATIC.glob("console-book-fx*.js")
    }
    assert on_disk == set(MINE)
    assert set(MINE) <= set(READ_ASSETS)


def test_the_player_css_uses_the_consoles_tokens_only() -> None:
    raw = (STATIC / "book-read.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    mine = css[css.index(".bk-app .bk-player{") :]
    assert css.isascii()
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", mine) == []
    assert not re.search(r"\b(?:rgb|rgba|hsl|hsla)\(", mine)
    for font in re.findall(r"(?<![-\w])font\s*:\s*([^;}]+)", mine):
        assert re.search(r"var\(--|inherit", font), font


def test_the_vault_fixture_still_says_what_the_script_says() -> None:
    got = json.loads(FIXTURE.read_text(encoding="utf-8"))
    lines = got["chapter"]["lines"]
    script = load_script(SCRIPT)
    assert len(lines) == len(script.lines)
    assert [x["n"] for x in lines] == list(range(1, len(lines) + 1))
    for told, written in zip(lines, script.lines, strict=True):
        assert [c["kind"] for c in told["cues"]] == [c.kind for c in written.cues], told["n"]
        for c, w in zip(told["cues"], written.cues, strict=True):
            if "{{" not in w.target:
                assert c["target"] == w.target, told["n"]
        if "{{" not in written.text:
            assert told["text"] == written.text, told["n"]
    assert set(got["pages"]) == {p["id"] for p in got["chapter"]["pages"]}
    assert all(set(p) >= {"id", "kind", "title", "sections", "flow"} for p in got["pages"].values())
