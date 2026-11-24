# src/jarvis/buildbook/writer/ports.py
"""What the full book reads from R6's parts (R6.3; R6.3.1 D8: the writer's context and part are
gone): `FactSource`, R6's `BookSource` plus R6.3's `facts()` (`release.ReleaseSource`), the
type `api/r6_wiring.py` passes as the Book's source.
"""

from __future__ import annotations

from typing import Protocol

from jarvis.buildbook.facts_model import FactPack
from jarvis.buildbook.ports import BookSource


class FactSource(BookSource, Protocol):
    """R6's `BookSource` plus R6.3's `facts()` (`ReleaseSource`; I1: typed for mypy)."""

    def facts(self) -> FactPack: ...


__all__ = ["FactSource"]
