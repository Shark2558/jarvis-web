# tests/fixtures/book/repo/src/jarvis/core/loop.py -- build book generator fixture (not imported)
"""The core loop: text in, a reply out (fixture module for the R6 generator tests)."""

from __future__ import annotations

from jarvis.llm.router import pick


def turn(text: str) -> str:
    """One conversation turn."""
    return f"[{pick('balanced')}] {text.strip()}"
