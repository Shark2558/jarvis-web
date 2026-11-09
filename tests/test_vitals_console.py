# tests/test_vitals_console.py -- R4: console-vitals.js obeys the console rules (static checks).
from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).parent.parent / "src/jarvis/api/static/console-vitals.js"


def src() -> str:
    return JS.read_text(encoding="utf-8")


def test_file_is_within_the_size_ceiling() -> None:
    assert len(src().splitlines()) <= 800


def test_no_markup_injection_apis() -> None:
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in src()


def test_no_remote_scripts_or_cdn() -> None:
    assert not re.search(r"https?://", src())
    assert "import(" not in src() and "importScripts" not in src()


def test_rupees_only_no_dollar_amounts() -> None:
    assert not re.search(r"\$\s*\d|USD|\bdollar", src(), re.IGNORECASE)
    assert "₹" in src() or "\\u20b9" in src()  # R5.1: ASCII source, so the rupee is escaped


def test_r51_source_is_ascii_and_within_the_new_file_budget() -> None:
    assert src().isascii()
    assert len(src().splitlines()) <= 400
    css = JS.with_name("console-vitals.css").read_text(encoding="utf-8")
    assert len(css.splitlines()) <= 300


def test_r51_never_writes_a_style_attribute_from_a_string() -> None:
    """CSP-friendly: only `el.style.width = ...` (a property), never setAttribute('style', ...)."""
    assert "setAttribute('style'" not in src() and "cssText" not in src()


def test_uses_text_content_and_the_consoles_api() -> None:
    assert "textContent" in src() and "JarvisConsole" in src()
    assert "/v1/vitals" in src()
