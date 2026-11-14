# src/jarvis/billing/ledger.py
"""The token ledger (docs/plans/r14-hardening.md D8): per call, per owner per day, counts only.
I0's stub: `NoLedger` records nothing. Part C builds `{prefix}token_ledger/{uid}_{yyyymmdd}` (90
days): calls, cold calls, input, cache read, cache write and output tokens, characters by part,
tools offered, skills opened."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from jarvis.skills.ports import LedgerCall


class NoLedger:
    async def record(self, call: LedgerCall) -> None:
        return None


NO_LEDGER: Final = NoLedger()

__all__ = ["NO_LEDGER", "NoLedger"]
