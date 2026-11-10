"""The core loop: text in, one model call, text out (build book fixture)."""

from __future__ import annotations


class Loop:
    """One conversation turn at a time."""

    def turn(self, text: str) -> str:
        return text.strip()
