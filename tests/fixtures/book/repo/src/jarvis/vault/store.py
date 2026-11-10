"""Sealed storage for conversations (build book fixture)."""

from __future__ import annotations


def seal(data: bytes) -> bytes:
    """Seal bytes (the fixture only reverses them)."""
    return data[::-1]
