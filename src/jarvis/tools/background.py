# src/jarvis/tools/background.py
"""Background reads: the one governed path for a job that reads the owner's own data with nobody
in the loop (R11 I1; CLAUDE.md "every tool call passes jarvis.tools.gateway").

The readers are the R11 helpers': birthdays (Google Contacts), breach notices (Gmail), the
missed-activity and free-time calendar read (Google Calendar), the to-dos for "top priority"
(Google Tasks) and grocery receipts (Gmail). Each asks THE GATEWAY before it reads, by the tool
whose permission row covers the read, and leaves one kind-only line in the gateway's audit chain
(`BackgroundReads.of(gateway)`; the helpers' context reads the app's gateway late):

- **The gateway decides.** Its configured policy plus the owner's own rules, read exactly as the
  gateway reads them for a call (`Gateway.rules`, with the Telegram and offline wrappers), for
  each named tool at READ_ONLY.
- **A job reads on "Allow" only (fail closed).** "Ask first" can't be asked at 05:00 and "Never"
  is total; no permission service, rules that can't be read, no gateway yet, no owner, a tool the
  gateway doesn't know or a tool that isn't read-only all mean no read.
- **Inside the gateway's call for that very tool, "Ask first" reads** (integrated review M1): the
  console's `contacts_birthdays` serves him while he is there, and the gateway already asked as
  its row says (the card, then his OK). The signal is the gateway's own: `Gateway._run` sets the
  call's `ToolContext` with the risk (`approved_risk`) and the tool (`tool`) it decided, for this
  owner. Only a read by THAT tool passes "Ask first": a call decided on another row (`focus_now`,
  `pending_list` on Nudges) never opens the to-dos' "Ask first", since no to-do card was shown
  (Mark XIV review). A job has no such context, and nothing it passes makes one. "Never" refuses.
- **It says why**: `allowed()` and `verdict()` give a `Verdict` (allowed / ask_first / denied /
  unreadable, the row's tool that stopped it, a fixed reason word); it is truthy only when
  allowed. `verdict()` is what a job would be told now, with no audit line: the helpers' "paused"
  lines (`jarvis.helpers.paused`) read it.
- **Decided as a plain read**: each row's tool at READ_ONLY with no arguments, since a job has
  none. An owner rule with conditions (`when`, `risks`) is judged as it reads for no arguments;
  inside the gateway's own call for that tool, the gateway already judged his real arguments.
- **One audit line each time**, the same shape for every reader: agent `helpers`, the row's tool,
  risk R1, outcome `executed` / `denied` / `error`, no arguments, and the detail "<job>" or
  "<job>; <a fixed reason word>": never a name, an address, a subject, a count or an amount.
  `reading()` writes it around the read itself: `executed`, `error` "failed" (or the caller's
  fixed word for that exception), or `error` "cut" when the job's time budget cancels the read
  (`CancelledError`, which `except Exception` never sees); the exception always goes on. A
  refusal is written once per owner, job, tool and reason a day, so a 5-minute job never floods
  the chain.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.tools.audit import AuditTrail
from jarvis.tools.base import Tool
from jarvis.tools.context import current_tool_context
from jarvis.tools.policy import Effect, OwnerRules, Policy

log = get_logger(__name__)

AGENT = "helpers"
Outcome = Literal["executed", "denied", "error"]
Reason = Literal["allowed", "ask_first", "denied", "unreadable"]
# the fixed reason words of a refusal (the audit line's detail)
NO_GATEWAY = "no gateway"
NO_OWNER = "no owner"
NO_RULES = "no permission service"
UNKNOWN_TOOL = "unknown tool"
NOT_A_READ = "not a read"
UNREADABLE = "permissions unreadable"
NEVER = "never"
ASK_FIRST = "ask first"
FAILED = "failed"
CUT = "cut"
ERRORS = frozenset({NO_GATEWAY, NO_RULES, UNREADABLE})  # the path itself failed: outcome "error"
MAX_REMEMBERED = 512  # refusals remembered for the once-a-day rule


class NotRead(Exception):  # noqa: N818 - a refusal, not an error
    """A source his permission row did not let read just now ("Ask first" with no card for that
    tool, or rows unreadable). Collectors name the source as not checked (`top priority`) or
    skip it quietly (a nudge's slot is decided, not retried every run)."""


@dataclass(frozen=True)
class Verdict:
    """The governed path's answer for one read: `reason`, the row's `tool` that stopped it ("" when
    allowed) and its fixed reason word (`why`). Truthy only when allowed."""

    reason: Reason
    tool: str = ""
    why: str = ""

    @property
    def ok(self) -> bool:
        return self.reason == "allowed"

    def __bool__(self) -> bool:
        return self.ok


ALLOWED = Verdict("allowed")
UNWIRED = Verdict("unreadable", why=NO_GATEWAY)  # a reader built with no governed path at all


def _refused(why: str, tool: str) -> Verdict:
    reason: Reason = "ask_first" if why == ASK_FIRST else "denied" if why == NEVER else "unreadable"
    return Verdict(reason, tool, why)


def _decided_for(uid: str) -> str:
    """The tool the gateway decided the call in flight for, for this owner, or "" (`Gateway._run`
    sets the call's context with the risk and the tool it decided; a look-up or a job has none)."""
    ctx = current_tool_context()
    if ctx is None or ctx.approved_risk is None or ctx.user_id != uid:
        return ""
    return ctx.tool


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

    @classmethod
    def of(
        cls, gateway: GatewayView, *, now: Callable[[], datetime] | None = None
    ) -> BackgroundReads:
        """The path over one gateway: its policy and rules decide; its audit chain is written."""
        return cls(lambda: gateway, audit=gateway.audit, now=now)

    async def allowed(self, uid: str, *tools: str, job: str) -> Verdict:
        """Allowed only when the gateway's policy ALLOWs every tool's row for him (inside the
        gateway's call for that very tool, "Ask first" too). A refusal is audited (once a day per
        owner, job, tool and reason) and logged; the verdict says why."""
        got = await self._decide(uid, tools, decided=_decided_for(uid))
        if got.ok:
            return got
        log.info("helpers: background read refused", extra={"job": job, "reason": got.why})
        if self._first_today((uid, job, got.tool, got.why)):
            outcome: Outcome = "error" if got.why in ERRORS else "denied"
            await self.note(got.tool, job=job, outcome=outcome, why=got.why)
        return got

    async def verdict(self, uid: str, *tools: str) -> Verdict:
        """What a job would be told now ("Allow" only), with no audit line and no log."""
        return await self._decide(uid, tools, decided="")

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

    @asynccontextmanager
    async def reading(
        self,
        tool: str,
        *,
        job: str,
        words: Mapping[type[BaseException], str] | None = None,
    ) -> AsyncIterator[None]:
        """Around ONE allowed read: its audit line whatever happens (`words`: a fixed reason word
        for an exception class, else "failed"; a cancel is "cut"). Every exception goes on."""
        try:
            yield
        except asyncio.CancelledError:
            await asyncio.shield(self.note(tool, job=job, outcome="error", why=CUT))
            raise
        except Exception as exc:
            word = next((w for cls, w in (words or {}).items() if isinstance(exc, cls)), FAILED)
            await self.note(tool, job=job, outcome="error", why=word)
            raise
        await self.note(tool, job=job, outcome="executed")

    def _first_today(self, key: tuple[str, str, str, str]) -> bool:
        today = self._now().astimezone(UTC).date()
        if self._told.get(key) == today:
            return False
        kept = {k: d for k, d in self._told.items() if d == today}
        self._told = dict(list(kept.items())[-MAX_REMEMBERED:]) | {key: today}
        return True

    async def _policy(self, gw: GatewayView, uid: str) -> Policy | Verdict:
        if gw.rules is None:  # no permission service: fail closed (as the gateway's own rows)
            return _refused(NO_RULES, "")
        try:
            return gw.policy.with_rules(await gw.rules.rules_for(uid))
        except Exception as exc:  # noqa: BLE001 - fail closed: no read this time
            log.warning("helpers: permissions unreadable", extra={"error": type(exc).__name__})
            return _refused(UNREADABLE, "")

    async def _decide(self, uid: str, tools: Sequence[str], *, decided: str) -> Verdict:
        first = tools[0] if tools else ""
        gw = self._gateway()
        if gw is None:
            return _refused(NO_GATEWAY, first)
        if not uid or not tools:
            return _refused(NO_OWNER, first)
        for name in tools:
            spec = gw.registry.get(name)
            if spec is None:
                return _refused(UNKNOWN_TOOL, name)
            if spec.risk is not ActionRisk.READ_ONLY:
                return _refused(NOT_A_READ, name)
        policy = await self._policy(gw, uid)
        if isinstance(policy, Verdict):
            return Verdict(policy.reason, first, policy.why)
        effects = [(name, policy.decide(name, ActionRisk.READ_ONLY, {})) for name in tools]
        never = next((n for n, e in effects if e is Effect.DENY), None)
        if never is not None:
            return _refused(NEVER, never)
        ask = next((n for n, e in effects if e is Effect.ASK and n != decided), None)
        if ask is not None:  # his card was for another tool, or there was none
            return _refused(ASK_FIRST, ask)
        return ALLOWED


__all__ = [
    "AGENT",
    "ALLOWED",
    "ASK_FIRST",
    "CUT",
    "FAILED",
    "NEVER",
    "NOT_A_READ",
    "NO_GATEWAY",
    "NO_RULES",
    "UNKNOWN_TOOL",
    "UNREADABLE",
    "UNWIRED",
    "BackgroundReads",
    "GatewayView",
    "NotRead",
    "Outcome",
    "Reason",
    "Verdict",
]
