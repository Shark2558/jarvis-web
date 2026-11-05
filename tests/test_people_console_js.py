# tests/test_people_console_js.py
"""Static checks on the People panel script: textContent only, no remote code, one tab per URL."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "src/jarvis/api/static/console-people.js"


@pytest.fixture(scope="module")
def source() -> str:
    return JS.read_text(encoding="utf-8")


def test_script_is_ascii_and_within_the_size_limit(source: str) -> None:
    assert source.isascii()
    assert len(source.splitlines()) <= 800


@pytest.mark.parametrize(
    "banned",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"],
)
def test_script_never_writes_html_or_evaluates_strings(source: str, banned: str) -> None:
    assert banned not in source


def test_script_loads_nothing_remote(source: str) -> None:
    assert not re.search(r"""['"]https?://""", source)
    assert "importScripts" not in source and "import(" not in source


def test_each_profile_opens_in_its_own_tab_without_opener_access(source: str) -> None:
    assert "window.open(p.url, '_blank', 'noopener,noreferrer')" in source
    assert "forEach((p) => { if (window.open" in source


def test_script_has_valid_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([node, "--check", str(JS)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
