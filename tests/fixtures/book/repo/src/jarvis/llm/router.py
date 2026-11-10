# tests/fixtures/book/repo/src/jarvis/llm/router.py -- build book generator fixture (not imported)
"""The model router: a skill asks for a tier, never a model id (fixture module)."""

from __future__ import annotations

TIERS = ("fast", "balanced", "strong")


def pick(tier: str) -> str:
    """The tier to use; an unknown one falls back to balanced."""
    return tier if tier in TIERS else "balanced"
