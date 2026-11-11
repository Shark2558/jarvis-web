# src/jarvis/tools/background.py
"""Background reads: the one governed path for a job that reads the owner's own data with nobody
in the loop (R11 I1; CLAUDE.md "every tool call passes jarvis.tools.gateway").

The readers are the R11 helpers' jobs: birthdays (Google Contacts), breach notices (Gmail), the
missed-activity and free-time calendar read (Google Calendar), the to-dos for "top priority"
(Google Tasks) and grocery receipts (Gmail). Each asks THE GATEWAY before it reads, by the tool
whose permission row covers the read, and leaves one kind-only line in the gateway's audit chain:

- **The gateway decides.** Its configured policy plus the owner's own rules, read exactly as the
  gateway reads them for a call (`Gateway.rules`, with the Telegram and offline wrappers), for
  each named tool at READ_ONLY.
- **Only ALLOW reads (fail closed).** "Ask first" can't be asked at 05:00 and "Never" is total;
  rules that can't be read, no gateway yet, no owner, a tool the gateway doesn't know or a tool
  that isn't read-only all mean no read. The console's own tool calls still ask as the row says.
- **One audit line each time**, the same shape for every reader: agent `helpers`, the row's tool,
  risk R1, outcome `executed` / `denied` / `error`, no arguments, and the detail "<job>" or
  "<job>; <a fixed reason word>": never a name, an address, a subject, a count or an amount.
  A refusal is written once per owner, job, tool and reason a day, so a 5-minute job never
  floods the chain.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.tools.audit import AuditTrail
from jarvis.tools.base import Tool
from jarvis.tools.policy import Effect, OwnerRules, Policy

log = get_logger(__name__)

AGENT = "helpers"
Outcome = Literal["executed", "denied", "error"]
# the fixed reason words of a refusal (the audit line's detail)
NO_GATEWAY = "no gateway"
NO_OWNER = "no owner"
UNKNOWN_TOOL = "unknown tool"
NOT_A_READ = "not a read"
UNREADABLE = "permissions unreadable"
NEVER = "never"
ASK_FIRST = "ask first"
ERRORS = frozenset({NO_GATEWAY, UNREADABLE})  # the path itself failed: outcome "error"
MAX_REMEMBERED = 512  # refusals remembered for the once-a-day rule


class _Registry(Protocol):
    def get(self, name: str) -> Tool | None: ...


class GatewayView(Protocol):
    """What a background read needs of `jarvis.tools.gateway.Gateway`."""

    policy: Policy
    rules: OwnerRules | None
    audit: AuditTrail

    @property
    def registry(self) -> _Registry: ...


class BackgroundReads:
    """`gateway`: read late (the helpers' jobs are built before the gateway). `audit`: where a
    refusal goes while there is no gateway yet (in the app, the same chain the gateway writes)."""

    def __init__(
        self,
        gateway: Callable[[], GatewayView | None],
        *,
        audit: AuditTrail,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._gateway = gateway
        self._audit = audit
        self._now = now or (lambda: datetime.now(UTC))
        self._told: dict[tuple[str, str, str, str], date] = {}

    async def allowed(self, uid: str, *tools: str, job: str) -> bool:
        """True only when the gateway's policy ALLOWs every tool's row for him (no card, no
        Never). A refusal is audited (once a day per owner, job, tool and reason) and logged."""
        why = await self._refusal(uid, tools)
        if why is None:
            return True
        log.info("helpers: background read refused", extra={"job": job, "reason": why})
        tool = tools[0] if tools else ""
        if self._first_today((uid, job, tool, why)):
            outcome: Outcome = "error" if why in ERRORS else "denied"
            await self.note(tool, job=job, outcome=outcome, why=why)
        return False

    async def note(self, tool: str, *, job: str, outcome: Outcome, why: str = "") -> None:
        """The one kind-only audit line of a background read (after it ran, or a refusal)."""
        gw = self._gateway()
        audit = gw.audit if gw is not None else self._audit
        try:
            await audit.append(
                agent=AGENT,
                tool=tool,
                risk=ActionRisk.READ_ONLY,
                outcome=outcome,
                args={},
                detail=f"{job}; {why}" if why else job,
            )
        except Exception as exc:  # noqa: BLE001 - bookkeeping; the read's own result stands
            log.error(
                "AUDIT WRITE FAILED for a background read",
                extra={"job": job, "error": type(exc).__name__},
            )

    def _first_today(self, key: tuple[str, str, str, str]) -> bool:
        today = self._now().astimezone(UTC).date()
        if self._told.get(key) == today:
            return False
        kept = {k: d for k, d in self._told.items() if d == today}
        self._told = dict(list(kept.items())[-MAX_REMEMBERED:]) | {key: today}
        return True

    async def _refusal(self, uid: str, tools: Sequence[str]) -> str | None:
        gw = self._gateway()
        if gw is None:
            return NO_GATEWAY
        if not uid or not tools:
            return NO_OWNER
        for name in tools:
            spec = gw.registry.get(name)
            if spec is None:
                return UNKNOWN_TOOL
            if spec.risk is not ActionRisk.READ_ONLY:
                return NOT_A_READ
        policy = gw.policy
        if gw.rules is not None:
            try:
                policy = policy.with_rules(await gw.rules.rules_for(uid))
            except Exception as exc:  # noqa: BLE001 - fail closed: no read this time
                log.warning("helpers: permissions unreadable", extra={"error": type(exc).__name__})
                return UNREADABLE
        for name in tools:
            effect = policy.decide(name, ActionRisk.READ_ONLY, {})
            if effect is Effect.DENY:
                return NEVER
            if effect is Effect.ASK:
                return ASK_FIRST
        return None


__all__ = [
    "AGENT",
    "ASK_FIRST",
    "NEVER",
    "NOT_A_READ",
    "NO_GATEWAY",
    "UNKNOWN_TOOL",
    "UNREADABLE",
    "BackgroundReads",
    "GatewayView",
    "Outcome",
]
