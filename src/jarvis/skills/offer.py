# src/jarvis/skills/offer.py
"""The turn's tools (docs/plans/r14-hardening.md D9). I0's stub: `offer_all`, every tool, as
before R14. Part C replaces the body with the register's offer (keyword matches, the last 3
turns' skills, the sticky set, the core, every tool a replayed `tool_use` names)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.llm.base import ToolSpec
    from jarvis.skills.ports import OfferContext


def offer_all(ctx: OfferContext | None, specs: Sequence[ToolSpec]) -> list[ToolSpec]:
    return list(specs)


__all__ = ["offer_all"]
