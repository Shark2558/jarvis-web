# src/jarvis/offline/rules.py
"""Writes made in an offline turn always ask (R1 D11 b).

A small model on the laptop picks arguments less reliably and is easier to steer with injected
text, so while `core.channel.answered_offline()` every reversible (R2) call becomes a one-tap card,
whatever the owner's Allow says. Reads are untouched, and R3 already asks and can never be relaxed.
Wraps the gateway's `OwnerRules` source (I1 builds the chain
`OfflineRules(ChannelRules(permissions, ...))`); no gateway change.

`WRITES_ASK` exists only so the offline eval can show its negative control.
"""

from __future__ import annotations

from jarvis.core.channel import answered_offline
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.policy import Effect, OwnerRules, PolicyRule

WRITES_ASK = True

OFFLINE_ASK = PolicyRule(
    tool_pattern="*",
    effect=Effect.ASK,
    risks=[ActionRisk.REVERSIBLE],
    source="offline",
    reason="Offline mode: JARVIS is running on your laptop, so every change waits for you.",
)


class OfflineRules:
    """An `OwnerRules` that adds the offline ASK rule to the wrapped source's rules."""

    def __init__(self, inner: OwnerRules) -> None:
        self._inner = inner

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        rules = await self._inner.rules_for(user_id)  # may raise: the gateway fails closed
        if WRITES_ASK and answered_offline():
            return [*rules, OFFLINE_ASK.model_copy()]
        return rules


__all__ = ["OFFLINE_ASK", "OfflineRules"]
