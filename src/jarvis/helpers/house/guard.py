# src/jarvis/helpers/house/guard.py
"""What Part B's background jobs share (docs/plans/r11-free-helpers.md D20, BRIEF-COMMON §5):

- `allowed(ctx, uid, *tools)`: the owner's own permission rows decide, as for a tool call
  (`Policy(rules).decide(tool, R1, {})`). "Never" on a row stops the job for him; rules that
  can't be read stop it too (fail closed). No permission service at all (a bare test app) means
  the built-in defaults, as the DigiLocker inbox job does.
- `audit(ctx, job, kind)`: one content-free line in the audit chain (agent `helpers`, the job's
  name, the alert kind only) when a background job read his own data (Gmail).
- `Counts`: a job's result counts (class names and counts only ever reach the log).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.ports import HelperContext
from jarvis.logging import get_logger
from jarvis.tools.policy import Effect, Policy

log = get_logger(__name__)
AGENT = "helpers"


async def allowed(ctx: HelperContext, uid: str, *tools: str) -> bool:
    source = ctx.permissions()
    if source is None:
        return True
    try:
        rules = await source.rules_for(uid)
    except Exception as exc:  # noqa: BLE001 - fail closed: nothing runs this time
        log.warning("helpers: permissions unreadable", extra={"error": type(exc).__name__})
        return False
    policy = Policy(rules)
    return all(policy.decide(t, ActionRisk.READ_ONLY, {}) is not Effect.DENY for t in tools)


async def audit(ctx: HelperContext, job: str, kind: str, *, outcome: str = "ok") -> None:
    try:
        await ctx.audit.append(
            agent=AGENT,
            tool=job,
            risk=ActionRisk.READ_ONLY,
            outcome=outcome,
            args={},
            detail=kind,
        )
    except Exception as exc:  # noqa: BLE001 - bookkeeping; the job's own result stands
        log.warning("helpers: audit line not written", extra={"error": type(exc).__name__})


@dataclass
class Counts:
    values: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, n: int = 1) -> None:
        self.values[key] = self.values.get(key, 0) + n

    def done(self, *keys: str) -> dict[str, int]:
        return {**{k: 0 for k in keys}, **self.values}


__all__ = ["AGENT", "Counts", "allowed", "audit"]
