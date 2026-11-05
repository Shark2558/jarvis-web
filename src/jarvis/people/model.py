# src/jarvis/people/model.py
"""Every model call behind people research (R4 D10, D-D2): the classifier and the summary.

`PeopleModel` is the seam. `BrainPeopleModel` is the real one and is admitted and metered like any
other paid caller:

- `available(uid)` is True only when a brain that keeps content private exists (`tools_allowed`,
  chosen exactly as the morning brief does, so a name and its snippets never reach a training
  brain) AND the owner's monthly budget admits a call (`Billing.ensure_allowed`). Otherwise the
  service runs without a model: links only, strictest verification.
- `complete` asks the router for the FAST tier with NO tools, and returns the text with its cost.
- `record` adds the whole dossier's cost to the month in ONE `Billing.record`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.billing import Billing, BudgetError
from jarvis.brief.summarize import choose_brain
from jarvis.llm.base import ChatMessage, Role
from jarvis.llm.brains import BrainRegistry
from jarvis.llm.pricing import cost_usd
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ModelReply:
    text: str
    cost_usd: float = 0.0


class PeopleModel(Protocol):
    async def available(self, uid: str) -> bool: ...

    async def complete(
        self, uid: str, system: str, prompt: str, *, max_tokens: int
    ) -> ModelReply: ...

    async def record(self, uid: str, cost_usd: float) -> None: ...


class BrainPeopleModel:
    def __init__(
        self, brains: BrainRegistry, billing: Billing, tier: ModelTier = ModelTier.FAST
    ) -> None:
        self._brains, self._billing, self._tier = brains, billing, tier

    async def available(self, uid: str) -> bool:
        spec = choose_brain(self._brains)
        if spec is None:
            return False
        try:
            await self._billing.ensure_allowed(uid, spec)
        except BudgetError:
            return False
        return True

    async def complete(self, uid: str, system: str, prompt: str, *, max_tokens: int) -> ModelReply:
        spec = choose_brain(self._brains)
        if spec is None or not spec.tools_allowed:  # belt and braces: never a training brain
            raise RuntimeError("no brain that keeps content private is configured")
        await self._billing.ensure_allowed(uid, spec)  # call-level admission, like every caller
        done = await self._brains.router_for(spec.id).complete(
            tier=self._tier,
            system=system,
            messages=[ChatMessage(role=Role.USER, content=prompt)],
            max_tokens=max_tokens,
            tools=None,
            allow_degrade=False,
        )
        return ModelReply(done.text, done.cost_usd or cost_usd(done.model, done.usage))

    async def record(self, uid: str, cost: float) -> None:
        spec = choose_brain(self._brains)
        if spec is not None and cost > 0:
            await self._billing.record(uid, spec.id, cost)


__all__ = ["BrainPeopleModel", "ModelReply", "PeopleModel"]
