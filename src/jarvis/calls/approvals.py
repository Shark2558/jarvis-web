# src/jarvis/calls/approvals.py
"""Approving a call (R18 A1; docs/plans/r18-calls.md section 4 step 1 and section 8, "A call placed
without you"; BUILD-BRIEF.md ground rule 5; Layer 4 guardrail, Layer 6 gateway tool).

Placing a call is R3: every call is a `calls_place` card through `jarvis.tools.gateway`, whether
the model proposed it in a chat or the owner pressed Call on a card in the Calls panel (the
console's press runs the same tool, `approving(card_id)`). The gateway's own rules hold: a card
every time, never Approve all, no "don't ask again", the approval token (`PendingAction`) one use
and 10 minutes, bound to the exact arguments (the number and the card's content), and the
owner's passkey whenever "Require passkey for irreversible actions" is in force.

This module adds what is particular to calls:

- `CallsService.preview` (the card's look-up): the card is built from the arguments, its limits
  are checked (`calls.limits`), and a number never called before needs his passkey: when the
  passkey requirement is NOT in force JARVIS can't ask for one, so such a call is refused with
  words that say how to switch it on (fail closed; no other proof stands in for it). The card
  text is `cards.card_text` (the number's last four digits only).
- `CallsService.place` (runs only on his approval): the same checks again, the card stored as
  APPROVED, and a dial grant issued: one use, 10 minutes, bound to the number and the card's
  digest (`GrantBook`). The call engine (A2, `CallStarter`) is then asked to start the call.
- `CallsService.take_for_dial` (the engine, just before `call.dial`): spends the grant (a card
  changed since its approval no longer matches the digest), counts the call against the day's
  limits in one transaction (`Limits.admit_dial`) and marks the card USED.
  `CallsService.confirm_dial` is the phone side's check of the `approval_id` it was sent: true
  once, for that call and number, within 2 minutes of the dial.
- `CallsService.answer_mode`: the `calls_answer_mode` tool (answering missed calls, row 104).

Grants live in this process only (Cloud Run runs one instance; the call hub is in memory too):
after a restart no grant is live, so nothing can be dialled on an old approval. Every step is in
the append-only audit (`audit_step`), with the number masked, never in full.
"""

from __future__ import annotations

import asyncio
import contextvars
import secrets
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import ValidationError

from jarvis.calls.cards import CardBuilder, CardRefused, card_text, masked, read_draft
from jarvis.calls.limits import LimitRefused, Limits
from jarvis.calls.models import (
    APPROVAL_TTL_S,
    CARD_ID_RE,
    CallCard,
    CardStatus,
)
from jarvis.calls.ports import CallStore
from jarvis.calls.tools import ANSWER_MODE, PLACE, AnswerArgs
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.tools.audit import AuditTrail
from jarvis.tools.base import Preview
from jarvis.tools.context import require_tool_context

log = get_logger(__name__)

AGENT = "communication"
SCOPE_SESSION = "calls"  # a console press's gateway scope: "<uid>:calls"
PHONE_CONFIRM_S = 120
GRANT_TTL = timedelta(seconds=APPROVAL_TTL_S)

MSG_NEEDS_PASSKEY = (
    "This number hasn't been called before, so the call needs your passkey. Set one up and "
    "switch on 'Require passkey for irreversible actions' in Approvals → Permissions, then "
    "approve the call again."
)
MSG_CHANGED = "The call card changed since it was written. Check it and approve it again."
MSG_NOT_WAITING = "That call card is no longer waiting for approval."
MSG_GRANT = "That call's approval is spent, expired or for another call. Approve it again."
MSG_UNREADABLE = "JARVIS can't read its call data just now, so nothing was done."
MSG_NOT_APPROVED = "A call runs only on the owner's approval."


class GrantInvalid(PermissionError):
    """A dial grant that is unknown, spent, expired, for another owner, call, number or card."""


async def audit_step(
    audit: AuditTrail | None,
    tool: str,
    outcome: str,
    args: Mapping[str, Any],
    detail: str = "",
    risk: ActionRisk = ActionRisk.IRREVERSIBLE,
) -> None:
    """Append one calls step to the audit chain. Never raises: a failure is logged loudly (the
    gateway has already recorded the approved intent before anything ran)."""
    if audit is None:
        return
    try:
        await audit.append(
            agent=AGENT, tool=tool, risk=risk, outcome=outcome, args=dict(args), detail=detail
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "AUDIT WRITE FAILED (calls)",
            extra={"tool": tool, "outcome": outcome, "error": type(exc).__name__},
        )


# ---- dial grants ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Grant:
    id: str
    uid: str
    card_id: str
    number: str  # E.164, in memory only
    digest: str
    expires_at: datetime
    call_id: str | None = None  # set when the engine took it for a dial
    taken_at: datetime | None = None
    confirmed: bool = False


def _utcnow() -> datetime:
    return datetime.now(UTC)


class GrantBook:
    """The live dial grants of this process (one use, `APPROVAL_TTL_S`)."""

    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        self._grants: dict[str, Grant] = {}
        self._lock = asyncio.Lock()
        self._clock = clock

    def _sweep(self, now: datetime) -> None:
        keep = PHONE_CONFIRM_S
        self._grants = {
            k: g
            for k, g in self._grants.items()
            if g.expires_at > now
            or (g.taken_at is not None and now - g.taken_at < timedelta(seconds=keep))
        }

    async def issue(self, uid: str, card: CallCard) -> Grant:
        async with self._lock:
            now = self._clock()
            self._sweep(now)
            for k, g in list(self._grants.items()):  # one live grant per card
                if g.uid == uid and g.card_id == card.id and g.call_id is None:
                    del self._grants[k]
            grant = Grant(
                id=f"cg_{secrets.token_urlsafe(18)}",
                uid=uid,
                card_id=card.id,
                number=card.number_e164,
                digest=card.digest(),
                expires_at=now + GRANT_TTL,
            )
            self._grants[grant.id] = grant
            return grant

    async def take(self, uid: str, grant_id: str, call_id: str) -> Grant:
        """Spend the grant for one dial (GrantInvalid when it can't be)."""
        async with self._lock:
            now = self._clock()
            self._sweep(now)
            g = self._grants.get(grant_id)
            if g is None or g.uid != uid or g.call_id is not None or g.expires_at <= now:
                raise GrantInvalid(MSG_GRANT)
            taken = replace(g, call_id=call_id, taken_at=now)
            self._grants[grant_id] = taken
            return taken

    async def give_back(self, grant_id: str) -> None:
        """A dial refused after the grant was taken (a limit, a changed card): spent anyway."""
        async with self._lock:
            self._grants.pop(grant_id, None)

    async def confirm_dial(self, grant_id: str, call_id: str, number: str) -> bool:
        """The phone's check of a `call.dial`'s approval id: true once, for this call and number,
        within `PHONE_CONFIRM_S` of the dial."""
        async with self._lock:
            now = self._clock()
            self._sweep(now)
            g = self._grants.get(grant_id)
            ok = (
                g is not None
                and g.call_id == call_id
                and g.taken_at is not None
                and not g.confirmed
                and secrets.compare_digest(g.number, number)
                and now - g.taken_at < timedelta(seconds=PHONE_CONFIRM_S)
            )
            if ok and g is not None:
                self._grants[grant_id] = replace(g, confirmed=True)
            return ok

    async def drop_card(self, uid: str, card_id: str) -> int:
        async with self._lock:
            gone = [k for k, g in self._grants.items() if g.uid == uid and g.card_id == card_id]
            for k in gone:
                del self._grants[k]
            return len(gone)


# ---- ports --------------------------------------------------------------------------------------
class PasskeyPolicy(Protocol):
    """Is "Require passkey for irreversible actions" in force for him now (then the gateway's
    approval guard asks a passkey check made for exactly this card)? `PermissionsService`."""

    async def passkey_required(self, uid: str) -> bool: ...


class CallStarter(Protocol):
    """The call engine (A2): start an approved card's call; returns the call id. The engine
    calls `CallsService.take_for_dial` itself just before the phone dials."""

    async def start(self, uid: str, card: CallCard, approval_id: str) -> str: ...


_console_card: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "jarvis_calls_console_card", default=None
)


@contextmanager
def approving(card_id: str) -> Iterator[None]:
    """Around the console's `calls_place` call: the card being approved is this stored one."""
    token = _console_card.set(card_id)
    try:
        yield
    finally:
        _console_card.reset(token)


# ---- the service ------------------------------------------------------------------------------
class CallsService:
    """`calls.tools.CallTools` (place, preview, answer_mode) and the engine's dial check."""

    def __init__(
        self,
        store: CallStore,
        builder: CardBuilder,
        limits: Limits,
        *,
        grants: GrantBook | None = None,
        passkeys: PasskeyPolicy | None = None,
        starter: CallStarter | None = None,
        audit: AuditTrail | None = None,
    ) -> None:
        self.store, self.builder, self.limits = store, builder, limits
        self.grants = grants or GrantBook()
        self.passkeys, self.starter, self.audit = passkeys, starter, audit

    # ---- the card ---------------------------------------------------------------------------
    async def _card_for(self, uid: str, args: Mapping[str, Any]) -> CallCard:
        draft = read_draft(args)
        card_id = _console_card.get()
        if card_id is None:
            return await self.builder.build(uid, draft)
        stored = await self._stored(uid, card_id)
        if stored.status is not CardStatus.DRAFT:
            raise CardRefused("not_waiting", MSG_NOT_WAITING)
        card = await self.builder.build(uid, draft, card_id=stored.id)
        if card.digest() != stored.digest():
            raise CardRefused("changed", MSG_CHANGED)
        return card

    async def _stored(self, uid: str, card_id: str) -> CallCard:
        if not CARD_ID_RE.fullmatch(card_id):
            raise CardRefused("not_waiting", MSG_NOT_WAITING)
        try:
            stored = await self.store.get_card(uid, card_id)
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.error("call card unreadable", extra={"error": type(exc).__name__})
            raise CardRefused("unreadable", MSG_UNREADABLE) from None
        if stored is None:
            raise CardRefused("not_waiting", MSG_NOT_WAITING)
        return stored

    async def gates(self, uid: str, card: CallCard) -> None:
        """What must hold before a card may be approved: the limits, and a passkey JARVIS can
        ask for when the number is new. Raises LimitRefused / CardRefused."""
        await self.limits.check_approval(uid, card)
        if card.new_number and not await self._passkey_in_force(uid):
            raise CardRefused("needs_passkey", MSG_NEEDS_PASSKEY)

    async def _passkey_in_force(self, uid: str) -> bool:
        if self.passkeys is None:
            return False
        try:
            return await self.passkeys.passkey_required(uid)
        except Exception as exc:  # noqa: BLE001 - can't tell: no new number (fail closed)
            log.error("passkey policy unreadable", extra={"error": type(exc).__name__})
            return False

    # ---- the gateway tool -------------------------------------------------------------------
    async def preview(self, args: dict[str, Any]) -> Preview:
        """The approval card's look-up: refused here, no card is ever proposed."""
        uid = require_tool_context().user_id
        card = await self._card_for(uid, args)
        await self.gates(uid, card)
        return Preview(summary=card_text(card))

    async def place(self, args: dict[str, Any]) -> dict[str, Any]:
        """Runs only on his approval (the gateway spent the token and, when in force, checked
        his passkey for exactly this card)."""
        ctx = require_tool_context()
        if not ctx.confirmed:
            raise PermissionError(MSG_NOT_APPROVED)
        uid = ctx.user_id
        card = await self._card_for(uid, args)
        await self.gates(uid, card)
        approved = card.model_copy(update={"status": CardStatus.APPROVED})
        await self.store.put_card(uid, approved)
        grant = await self.grants.issue(uid, approved)
        await audit_step(
            self.audit,
            PLACE,
            "approved",
            {"card": approved.id, "digest": grant.digest},
            f"card {approved.id} to {masked(approved.number_e164)}; grant 10 min, one use",
        )
        call_id = await self._start(uid, approved, grant)
        return {
            "status": "placing" if call_id else "approved",
            "card_id": approved.id,
            "call_id": call_id,
            "words": "The call is being placed." if call_id else "The call is approved.",
        }

    async def _start(self, uid: str, card: CallCard, grant: Grant) -> str | None:
        if self.starter is None:
            return None
        try:
            return await self.starter.start(uid, card, grant.id)
        except Exception as exc:  # noqa: BLE001 - the card stays approved for 10 minutes
            log.error("the call engine did not start the call", extra={"error": type(exc).__name__})
            await audit_step(
                self.audit, PLACE, "start_failed", {"card": card.id}, type(exc).__name__
            )
            raise

    async def answer_mode(self, args: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        try:
            a = AnswerArgs.model_validate(args)
        except ValidationError:
            raise ValueError("check on, after_rings and policy") from None
        changes: dict[str, Any] = {"answering_on": a.on}
        if a.after_rings is not None:
            changes["answer_after_rings"] = a.after_rings
        if a.policy is not None:
            changes["answer_policy"] = a.policy
        saved = await self.store.save_settings(uid, changes)
        await audit_step(
            self.audit,
            ANSWER_MODE,
            "changed",
            {"on": saved.answering_on},
            f"answering {'on' if saved.answering_on else 'off'}",
            ActionRisk.REVERSIBLE,
        )
        return {
            "answering_on": saved.answering_on,
            "after_rings": saved.answer_after_rings,
            "policy": saved.answer_policy.value,
        }

    # ---- the engine and the phone -----------------------------------------------------------
    async def take_for_dial(self, uid: str, approval_id: str, call_id: str) -> CallCard:
        """Just before `call.dial`: spend the grant, match the stored card, count the call
        against today's limits (one transaction) and mark the card USED. Raises GrantInvalid,
        CardRefused or LimitRefused; nothing is dialled then."""
        grant = await self.grants.take(uid, approval_id, call_id)
        try:
            card = await self._stored(uid, grant.card_id)
            if (
                card.status is not CardStatus.APPROVED
                or card.digest() != grant.digest
                or card.number_e164 != grant.number
            ):
                raise CardRefused("changed", MSG_CHANGED)
            await self.limits.admit_dial(uid, card)
        except (CardRefused, LimitRefused) as exc:
            await self.grants.give_back(approval_id)
            await audit_step(self.audit, PLACE, "dial_refused", {"card": grant.card_id}, exc.code)
            raise
        used = card.model_copy(update={"status": CardStatus.USED})
        await self.store.put_card(uid, used)
        await audit_step(
            self.audit,
            PLACE,
            "dialling",
            {"card": card.id, "call": call_id},
            f"call {call_id} to {masked(card.number_e164)}",
        )
        return used

    async def confirm_dial(self, approval_id: str, call_id: str, number: str) -> bool:
        return await self.grants.confirm_dial(approval_id, call_id, number)

    async def cancel(self, uid: str, card_id: str) -> CallCard:
        """His Cancel: a waiting or approved card is cancelled and its grant dropped."""
        card = await self._stored(uid, card_id)
        if card.status not in (CardStatus.DRAFT, CardStatus.APPROVED):
            raise CardRefused("not_waiting", MSG_NOT_WAITING)
        cancelled = card.model_copy(update={"status": CardStatus.CANCELLED})
        await self.store.put_card(uid, cancelled)
        await self.grants.drop_card(uid, card_id)
        await audit_step(
            self.audit, PLACE, "cancelled", {"card": card_id}, "by the owner", ActionRisk.REVERSIBLE
        )
        return cancelled


__all__ = [
    "AGENT",
    "MSG_NEEDS_PASSKEY",
    "SCOPE_SESSION",
    "CallStarter",
    "CallsService",
    "Grant",
    "GrantBook",
    "GrantInvalid",
    "PasskeyPolicy",
    "approving",
    "audit_step",
]
