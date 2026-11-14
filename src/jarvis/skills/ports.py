# src/jarvis/skills/ports.py
"""Part C's ports in the brain (docs/plans/r14-hardening.md D8, D9; seam 7), owned by I0.

The brain has exactly two slots, `Brain.slots: BrainSlots`:
- `tools(req, messages, specs)`: the tools this model call offers. Without Part C's `offer` (or
  with `tool_offer = "all"`, the kill switch) every tool, as before R14. An offer that raises, or
  answers nothing, gives every tool; a name the registry doesn't hold is never offered. The offer
  only narrows what the model sees: every call still meets the gateway's checks.
- `record(call)`: one `LedgerCall` per model call, after billing; a ledger that raises is logged
  and the reply goes on. Counts only: the ledger keeps no prompt or reply text.
There is no third slot: the history's cache hint is the Anthropic provider's own (D9, A1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from jarvis.logging import get_logger, get_trace_id

if TYPE_CHECKING:
    from jarvis.llm.base import ChatMessage, Completion, ToolSpec

log = get_logger(__name__)


@dataclass(frozen=True)
class OfferContext:
    uid: str
    text: str  # the owner's message of this turn
    messages: tuple[ChatMessage, ...]  # the window as sent (replayed tool_use names inside)
    turn: str  # fixed for the whole turn (the trace id)


class ToolOffer(Protocol):
    def __call__(self, ctx: OfferContext, specs: Sequence[ToolSpec]) -> list[ToolSpec]: ...


@dataclass(frozen=True)
class LedgerCall:
    uid: str
    brain_id: str
    system: str
    trailer: str
    messages: tuple[ChatMessage, ...] | Sequence[ChatMessage]
    tools: tuple[ToolSpec, ...] | Sequence[ToolSpec]
    completion: Completion | None


class TokenLedger(Protocol):
    async def record(self, call: LedgerCall) -> None: ...


class BrainSlots:
    def __init__(self, offer: ToolOffer | None = None, ledger: TokenLedger | None = None) -> None:
        self.offer, self.ledger = offer, ledger

    def tools(self, req: Any, messages: Sequence[Any], specs: Sequence[ToolSpec]) -> list[ToolSpec]:
        every = list(specs)
        if self.offer is None:
            return every
        ctx = OfferContext(str(req.user_id), str(req.message), tuple(messages), get_trace_id())
        try:
            got = self.offer(ctx, every)
        except Exception as exc:  # noqa: BLE001 - an offer that breaks offers every tool
            log.error("tool offer failed: every tool offered", extra={"error": type(exc).__name__})
            return every
        known = {s.name for s in every}
        offered = [s for s in got if getattr(s, "name", None) in known]
        return offered or every

    async def record(self, call: LedgerCall) -> None:
        if self.ledger is None:
            return
        try:
            await self.ledger.record(call)
        except Exception as exc:  # noqa: BLE001 - the ledger never breaks a reply
            log.warning("token ledger not written", extra={"error": type(exc).__name__})


__all__ = ["BrainSlots", "LedgerCall", "OfferContext", "TokenLedger", "ToolOffer"]
