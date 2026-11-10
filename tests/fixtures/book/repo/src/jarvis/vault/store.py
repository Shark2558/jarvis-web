# tests/fixtures/book/repo/src/jarvis/vault/store.py -- build book generator fixture (not imported)
"""Sealed notes at rest (fixture module; no real cryptography here)."""

from __future__ import annotations

import hashlib


def seal(note: str) -> str:
    """A stand-in for sealing: the note's digest, never the note."""
    return hashlib.sha256(note.encode()).hexdigest()
