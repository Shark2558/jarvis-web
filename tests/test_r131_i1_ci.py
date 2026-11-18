# tests/test_r131_i1_ci.py -- R13.1 I1: CI's test job runs plain `pytest` on 3.11 and 3.12 with no
# Playwright, and collects tests/browser too. A browser module that imports Playwright at its top
# fails that collection (found at I1: B's stage test did), so every browser module reaches it
# through `pytest.importorskip` (or inside a function). Written red first.
from __future__ import annotations

import ast
from pathlib import Path

BROWSER = Path(__file__).resolve().parent / "browser"


def _top_level_playwright(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("playwright"):
            lines.append(node.lineno)
        if isinstance(node, ast.Import) and any(
            a.name.startswith("playwright") for a in node.names
        ):
            lines.append(node.lineno)
    return lines


def test_no_browser_test_module_imports_playwright_at_its_top() -> None:
    found = {p.name: _top_level_playwright(p) for p in sorted(BROWSER.glob("test_*.py"))}
    assert {name: at for name, at in found.items() if at} == {}
