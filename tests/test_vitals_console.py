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
    assert "₹" in src()


def test_uses_text_content_and_the_consoles_api() -> None:
    assert "textContent" in src() and "JarvisConsole" in src()
    assert "/v1/vitals" in src()
