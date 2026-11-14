# src/jarvis/skills/part.py
"""R14 Part C (cost and the skill register): the part's one join with the app
(`jarvis.hardening.ports`). I0's stub: status "not built yet". Part C fills it: the tool
`skills_open` (R1, no side effect), the Vitals item `ai_parts`, the `token_ledger` privacy row,
and the services `offer` (`skills.ports.ToolOffer`) and `ledger` (`skills.ports.TokenLedger`).
"""

from __future__ import annotations

from jarvis.hardening.ports import HardeningContext, HardeningPart


def build(ctx: HardeningContext) -> HardeningPart:
    return HardeningPart("skills")


__all__ = ["build"]
