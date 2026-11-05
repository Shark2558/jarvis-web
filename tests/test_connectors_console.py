# tests/test_connectors_console.py -- R4 C: static rules for console-connectors.js (textContent
# only, no CDN, <= 800 lines, ASCII, no dollar amounts, valid syntax).
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

import jarvis

JS = Path(jarvis.__file__).parent / "api" / "static" / "console-connectors.js"


def test_file_is_small_ascii_and_self_contained() -> None:
    text = JS.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 800
    assert text.isascii()
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", text)
    assert not re.search(r"https?://(?!photos\.google\.com)", text)
    assert not re.search(r"\$\s?\d", text)  # rupees only


def test_a_token_is_never_stored_or_logged_by_the_page() -> None:
    text = JS.read_text(encoding="utf-8")
    assert not re.search(r"localStorage|sessionStorage|console\.log", text)
    assert "el.token.value = ''" in text  # cleared after sending


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_syntax_is_valid() -> None:
    done = subprocess.run(["node", "--check", str(JS)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_the_page_handles_reconnect_and_the_new_import_states() -> None:
    text = JS.read_text(encoding="utf-8")
    for needle in ("needs_reconnect", "edge_error", "timed_out", "picker_uri"):
        assert needle in text
