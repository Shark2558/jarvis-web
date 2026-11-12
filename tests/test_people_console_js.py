# tests/test_people_console_js.py
"""Static checks on the People panel script: textContent only, no remote code, one tab per click
(R11.1 D16: each profile has its own real link; the script never opens a window itself)."""

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


def test_each_profile_opens_from_its_own_link_without_opener_access(source: str) -> None:
    # R11.1 D16 (was: one window.open per URL from "Open all profiles", whose result was counted
    # although `noopener` makes it null, so the panel always said the tabs were blocked)
    assert "window.open" not in source and "Open all" not in source
    assert "a.href = p.url; a.target = '_blank'; a.rel = 'noopener noreferrer';" in source
    assert "'Open in browser'" in source and "'Open next'" in source
    # "Open next" presses ONE link, the next unopened card's own, straight from the click
    assert "const next = S.links.find((l) => !S.opened.has(l.url));" in source
    assert "if (next) next.a.click();" in source and "forEach((l) => l.a.click" not in source


def test_script_has_valid_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([node, "--check", str(JS)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_script_mirrors_the_servers_exact_host_rule(source: str) -> None:
    assert "HOSTS" not in source and "hostOk" in source
    assert r"(?:www\.)?github\.com$" in source  # github: the bare host or www, never a subdomain
    assert r"[a-z0-9-]+\.wikipedia\.org$" in source


def test_the_pill_says_brain_ai_on_or_no_ai(source: str) -> None:
    # R5.1 D9: ONE pill button; the long "No-AI (brain only)" wording became "Brain: No-AI"
    assert "'Brain: ' + word" in source and "none: 'No-AI'" in source
    assert "aria-haspopup" in source and "Paid replies resume" in source
