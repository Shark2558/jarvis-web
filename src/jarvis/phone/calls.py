# src/jarvis/phone/calls.py
"""R18 D: the cloud's half of the phone's call commands and call events
(docs/plans/r18-calls/BUILD-BRIEF.md, "Phone <-> cloud"; docs/plans/r18-calls.md sections 4, 8).
The bytes on the wire are `jarvis.phone.calls_wire`'s; what I1 wires is in
docs/plans/r18-calls/INTEGRATION-D.md.

**How the cloud reaches the phone.** R7 gave the phone a signed door (phone -> cloud) and, the
other way, only Web Push, which Chrome hands to the app's notification service (R7 D10). There is
no Firebase, no socket the phone keeps open and no foreground service (R7 D9, D22). So a command
travels in two steps:

1. `send(uid, command)` signs it, puts it in the phone's outbox and rings the **doorbell**: one Web
   Push of the kind `call_command` carrying a plain sentence, never a number or a name (the laptop's
   browser shows the same sentence: harmless, and it tells him what is happening).
2. The app's notification service sees that kind and asks the door, `POST /phone/v1/calls`, which
   `DoorGate` checks like every door request (shape, flood, device, time, cap, nonce, signature,
   rate); the answer carries every pending command. The phone also asks on every call-state change
   and when the app opens, so a lost push only delays a command, and it may wait up to 25 s for one
   (`wait`; Cloud Run runs one instance, so one in-memory outbox is enough).

**The cloud's signature** (`calls_wire`). The phone acts on a command only when it verifies with the
key the door's answer gave (`key`), names this phone, has not expired and was never acted on. The
joined phone part (I1-NOTES 2.7) uses `CommandSigner.ephemeral()`, a key made at each start: every
door answer carries it with the commands and the outbox is in memory too, so no keyring secret is
kept for it (`CommandSigner.from_secret` stays for a future key that must outlive a restart).

**A dial** needs a live approval: `ApprovalCheck.live_until(uid, approval_id, call_id, number)` must
give a time in the future, else nothing is queued (fail closed, also when the check fails). The
command lives until then, at most `DIAL_MAX_S`; the phone dials by itself only while it is fresh and
otherwise asks for his tap.

**Events** come in the same body: strict shapes, at most `EVENTS_MAX` a request and
`EVENTS_PER_MINUTE` a phone; one older than `EVENT_MAX_AGE_S` or ahead of the clock is dropped
(answered, never delivered); an event id seen in the last `EVENT_SEEN_S` is a retry and is not
delivered twice. An id counts as seen only once the engine took it: an engine failure answers 503
and the phone's retry arrives. An incoming number reaches the engine only while answering missed
calls is on (`AnsweringView`); otherwise it is dropped on arrival. No log line carries a full number
(`mask_number`); the audit gets the masked form.

**What the calls engine (A2) uses.** `OwnerPhoneLink(calls, uid)` is I0's `PhoneLink` (`send`,
`last_state`); `PhoneCalls.readiness(uid)` is the card's ready check; the engine implements
`PhoneEventSink` (I0's `CallStateEvent` for each state, `PhoneCommandResult` for each command the
phone acted on). A1's cards implement `CardDesk` and `ApprovalCheck`, its settings `AnsweringView`.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from jarvis.calls.protocol import CallStateEvent
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.mobile.ports import PhoneReply, PhoneRequest
from jarvis.phone.calls_wire import (
    EVENTS_MAX,
    WAIT_MAX_S,
    AnyEvent,
    Can,
    Card,
    CardDecision,
    CardEvent,
    CommandSigner,
    Dial,
    PhoneCommand,
    ProtocolCommand,
    ResultEvent,
    Sealed,
    StateEvent,
    from_protocol,
    mask_number,
    parse_body,
    seal,
)
from jarvis.phone.door import PerPhoneRate
from jarvis.phone.store import Phone

log = get_logger(__name__)

DOOR_ROUTE = "calls"
DOOR_CAP = 16 * 1024
DOORBELL_KIND = "call_command"
DIAL_MAX_S = 600  # an approval lives 10 minutes; a dial never outlives it
TTL_S: Mapping[str, int] = {
    "call.answer": 30,  # a ringing call does not wait
    "call.end": 120,
    "call.route": 60,
    "call.card": 600,
}
OUTBOX_MAX = 16
DEVICES_MAX = 8
EVENTS_PER_MINUTE = 40
EVENT_MAX_AGE_S = 900  # a phone may hold an event a while when it is offline
EVENT_AHEAD_S = 120
EVENT_SEEN_S = 1800
EVENT_SEEN_MAX = 4096
STATES_MAX = 64
CHECKIN_FRESH_S = 7 * 86_400
REJECTED: Mapping[str, str] = {"error": "input_rejected"}
DOORBELL_TEXT: Mapping[str, str] = {
    "call.dial": "JARVIS is placing the call you approved.",
    "call.answer": "JARVIS is answering a call for you.",
    "call.end": "JARVIS is ending the call.",
    "call.route": "JARVIS is moving the call's sound.",
    "call.card": "A JARVIS call is waiting for your approval.",
}
CardOutcome = Literal["approved", "declined", "passkey_needed", "gone", "unavailable"]
SendStatus = Literal["queued", "refused", "no_phone"]


# ---- what the engine and the cards get -------------------------------------------------------
@dataclass(frozen=True)
class PhoneCommandResult:
    """What the phone did with a command: `ok`, and `code` such as `placed`, `needs_tap`,
    `refused`, `answered`, `not_ringing`, `ended`, `routed`, `route_refused`, `no_permission`,
    `expired`."""

    device_id: str
    command_id: str
    call_id: str | None
    command: str
    ok: bool
    code: str
    at: float


@dataclass(frozen=True)
class AnsweringRule:
    on: bool = False
    after_rings: int = 5


@dataclass(frozen=True)
class SendOutcome:
    status: SendStatus
    device_id: str | None = None
    command_id: str | None = None
    rang: bool = False
    code: str = ""


@dataclass(frozen=True)
class PhoneReadiness:
    """`ready` False only for a known fault; `problems` are plain codes for the card's words:
    no_phone, not_checked_in (soft: the doorbell still wakes it), cannot_place, cannot_answer
    (soft: answering is off by default), no_call_state, no_notifications."""

    ready: bool
    device_id: str | None
    problems: tuple[str, ...]


class PhoneCommandRefused(RuntimeError):
    """`OwnerPhoneLink.send` could not queue the command: `code` is approval, number or no_phone."""

    def __init__(self, code: str) -> None:
        super().__init__(f"the phone command was not sent ({code})")
        self.code = code


# ---- the ports (implemented elsewhere; documented here) --------------------------------------
class PhoneDirectory(Protocol):
    """The owner's linked phones (`StoreDirectory` reads Part C's `PhoneStore`)."""

    async def linked(self, uid: str) -> Sequence[Phone]: ...


class ApprovalCheck(Protocol):
    """A1's approvals: when the approval `approval_id` for this call and number ends (unix
    seconds), or None when it is not live or not bound to them. It must NOT spend the approval
    (the gateway did that when the call was placed); it proves the dial is the approved one."""

    async def live_until(
        self, uid: str, approval_id: str, call_id: str, number_e164: str
    ) -> float | None: ...


class Doorbell(Protocol):
    """Wakes the phone; the number of devices that took it (`PushDoorbell`: Web Push)."""

    async def ring(self, uid: str, kind: str, text: str) -> int: ...


class PhoneEventSink(Protocol):
    """A2's calls engine. Both are awaited before the door answers; raising means "not taken": the
    door answers 503 and the phone sends the event again (it is never delivered twice)."""

    async def phone_state(self, uid: str, event: CallStateEvent) -> None: ...

    async def phone_result(self, uid: str, result: PhoneCommandResult) -> None: ...


class CardDesk(Protocol):
    """A1's call cards: Approve / Decline tapped on the phone. A card whose number was never called
    answers `passkey_needed`: the phone then opens the console's Calls panel for the passkey."""

    async def decide(
        self, uid: str, card_id: str, decision: CardDecision, device_id: str
    ) -> CardOutcome: ...


class AnsweringView(Protocol):
    """A1's answering policy (row 104, off by default): only `on` and the ring count matter here."""

    async def rule(self, uid: str) -> AnsweringRule: ...


class Audit(Protocol):
    async def append(self, **row: Any) -> Any: ...


class StoreDirectory:
    """`PhoneDirectory` over Part C's `PhoneStore` (`store.owner(uid).phones`)."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def linked(self, uid: str) -> Sequence[Phone]:
        return tuple((await self._store.owner(uid)).phones)


class PushDoorbell:
    """`Doorbell` over the app's Web Push service, read late (`app.state.push`; None when off)."""

    def __init__(self, push: Callable[[], Any]) -> None:
        self._push = push

    async def ring(self, uid: str, kind: str, text: str) -> int:
        service = self._push()
        if service is None:
            return 0
        return int(await service.send(uid, kind=kind, text=text))


# ---- the outbox and the seen events ----------------------------------------------------------
class Outbox:
    """Pending commands per phone, at most `OUTBOX_MAX` each (the oldest goes first)."""

    def __init__(self) -> None:
        self._boxes: OrderedDict[str, OrderedDict[str, Sealed]] = OrderedDict()
        self._bells: dict[str, asyncio.Event] = {}

    def put(self, device_id: str, sealed: Sealed) -> None:
        box = self._boxes.get(device_id)
        if box is None:
            while len(self._boxes) >= DEVICES_MAX:
                gone, _ = self._boxes.popitem(last=False)
                self._bells.pop(gone, None)
            box = self._boxes[device_id] = OrderedDict()
        box[sealed.id] = sealed
        while len(box) > OUTBOX_MAX:
            box.popitem(last=False)
        self.bell(device_id).set()

    def bell(self, device_id: str) -> asyncio.Event:
        found = self._bells.get(device_id)
        if found is None:
            found = self._bells[device_id] = asyncio.Event()
        return found

    def pending(self, device_id: str, now: float) -> list[Sealed]:
        box = self._boxes.get(device_id)
        if not box:
            return []
        for cid in [c for c, s in box.items() if s.exp <= now]:
            del box[cid]
        return list(box.values())

    def ack(self, device_id: str, ids: Sequence[str]) -> None:
        box = self._boxes.get(device_id)
        if box is not None:
            for cid in ids:
                box.pop(cid, None)


class SeenEvents:
    """Event ids taken in the last `EVENT_SEEN_S`, at most `EVENT_SEEN_MAX` (the oldest go)."""

    def __init__(self) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()

    def seen(self, key: str, now: float) -> bool:
        while self._seen:
            first, at = next(iter(self._seen.items()))
            if now - at < EVENT_SEEN_S and len(self._seen) <= EVENT_SEEN_MAX:
                break
            del self._seen[first]
        return key in self._seen

    def add(self, key: str, now: float) -> None:
        self._seen[key] = now


@dataclass(frozen=True)
class CheckIn:
    can: Can
    at: float
    app_version: str


def _when(at: float) -> datetime:
    return datetime.fromtimestamp(at, UTC)


# ---- the service -----------------------------------------------------------------------------
class PhoneCalls:
    """The phone link of the calls engine and the `calls` door route (one per process)."""

    def __init__(
        self,
        *,
        phones: PhoneDirectory,
        signer: CommandSigner,
        approvals: ApprovalCheck | None = None,
        doorbell: Doorbell | None = None,
        sink: PhoneEventSink | None = None,
        cards: CardDesk | None = None,
        answering: AnsweringView | None = None,
        audit: Audit | None = None,
        clock: Callable[[], float] = time.time,
        max_wait_s: float = WAIT_MAX_S,
    ) -> None:
        # approvals, sink, cards and answering may be set later (I1 builds this with the phone part,
        # before the calls engine exists); until approvals is set, every dial is refused
        self._phones, self._signer, self.approvals = phones, signer, approvals
        self._bell, self.sink, self.cards = doorbell, sink, cards
        self.answering, self._audit, self._clock = answering, audit, clock
        self._max_wait = max_wait_s
        self._outbox = Outbox()
        self._seen = SeenEvents()
        self._rate = PerPhoneRate(per_minute=EVENTS_PER_MINUTE, max_phones=DEVICES_MAX)
        self._checkins: OrderedDict[str, CheckIn] = OrderedDict()
        self._states: OrderedDict[str, CallStateEvent] = OrderedDict()
        self._latest: CallStateEvent | None = None

    def door_handlers(self) -> dict[str, Callable[[PhoneRequest], Awaitable[PhoneReply]]]:
        """{route: handler} for the phone part's `services["door"]` (I1)."""
        return {DOOR_ROUTE: self.door}

    # ---- sending ------------------------------------------------------------------------------
    async def send(self, uid: str, command: PhoneCommand | ProtocolCommand) -> SendOutcome:
        """Sign, queue and ring. Never raises; the outcome says what happened."""
        try:
            cmd = from_protocol(command)
        except ValueError:
            log.warning("phone command refused", extra={"code": "number"})
            return SendOutcome("refused", code="number")
        now = self._clock()
        exp = await self._expiry(uid, cmd, now)
        if exp is None:
            log.warning("phone command refused", extra={"type": cmd.type, "code": "approval"})
            await self._record_command("refused", cmd, None)
            return SendOutcome("refused", code="approval")
        target = await self._target(uid)
        if target is None:
            await self._record_command("no_phone", cmd, None)
            return SendOutcome("no_phone", code="no_phone")
        sealed = seal(self._signer, cmd, device_id=target, now=now, exp=exp)
        self._outbox.put(target, sealed)
        rang = await self._ring(uid, cmd.type)
        log.info("phone command queued", extra={"type": cmd.type, "device": target, "rang": rang})
        await self._record_command("queued", cmd, target)
        return SendOutcome("queued", device_id=target, command_id=sealed.id, rang=rang)

    async def _expiry(self, uid: str, cmd: PhoneCommand, now: float) -> float | None:
        if isinstance(cmd, Card):
            until = now + TTL_S["call.card"] if cmd.expires_at is None else cmd.expires_at
            return min(until, now + TTL_S["call.card"]) if until > now else None
        if not isinstance(cmd, Dial):
            return now + TTL_S[cmd.type]
        if self.approvals is None:
            log.warning("no approval check is wired: the dial is refused")
            return None
        try:
            live = await self.approvals.live_until(uid, cmd.approval_id, cmd.call_id, cmd.number)
        except Exception as exc:  # noqa: BLE001 - an approval that can't be read never dials
            log.warning("approval check failed", extra={"error": type(exc).__name__})
            return None
        if live is None or live <= now:
            return None
        return min(live, now + DIAL_MAX_S)

    async def _target(self, uid: str) -> str | None:
        """The linked phone that last checked in able to place calls, else the one seen last."""
        try:
            phones = list(await self._phones.linked(uid))
        except Exception as exc:  # noqa: BLE001 - no phone known is "no phone", logged
            log.warning("linked phones unreadable", extra={"error": type(exc).__name__})
            return None
        able = [p for p in phones if (c := self._checkins.get(p.id)) is not None and c.can.place]
        if able:
            return max(able, key=lambda p: self._checkins[p.id].at).id
        if not phones:
            return None
        return max(phones, key=lambda p: p.last_seen or p.linked_at).id

    async def _ring(self, uid: str, kind: str) -> bool:
        if self._bell is None:
            return False
        try:
            return await self._bell.ring(uid, DOORBELL_KIND, DOORBELL_TEXT[kind]) > 0
        except Exception as exc:  # noqa: BLE001 - the phone also asks on its own; logged
            log.warning("doorbell failed", extra={"error": type(exc).__name__})
            return False

    # ---- reading ------------------------------------------------------------------------------
    def last_state(self, call_id: str | None = None) -> CallStateEvent | None:
        """The last state of that call, or of any call when `call_id` is None."""
        return self._latest if call_id is None else self._states.get(call_id)

    async def readiness(self, uid: str) -> PhoneReadiness:
        target = await self._target(uid)
        if target is None:
            return PhoneReadiness(False, None, ("no_phone",))
        checkin = self._checkins.get(target)
        if checkin is None or self._clock() - checkin.at > CHECKIN_FRESH_S:
            return PhoneReadiness(True, target, ("not_checked_in",))
        can = checkin.can
        problems = [
            word
            for word, ok in (
                ("cannot_place", can.place),
                ("cannot_answer", can.answer),
                ("no_call_state", can.state),
                ("no_notifications", can.notify),
            )
            if not ok
        ]
        hard = {"cannot_place", "no_call_state", "no_notifications"}
        return PhoneReadiness(not hard & set(problems), target, tuple(problems))

    # ---- the door route -----------------------------------------------------------------------
    async def door(self, req: PhoneRequest) -> PhoneReply:
        body = parse_body(req.body)
        if body is None:
            log.info("phone calls body refused", extra={"device": req.device_id})
            return PhoneReply(422, REJECTED)
        now = self._clock()
        self._check_in(req.device_id, CheckIn(body.can, now, body.app_version))
        rule = await self._rule(req.uid)
        if body.events and not all(self._rate.allow(req.device_id, now) for _ in body.events):
            log.info("phone call events over the rate", extra={"device": req.device_id})
            return PhoneReply(429, {"error": "rate_limited"})
        took, decisions, failed = await self._take(req, body.events, rule, now)
        if failed:
            return PhoneReply(503, {"error": "unavailable", "detail": "Try again in a moment."})
        self._outbox.ack(req.device_id, body.acks)
        commands = await self._wait(req.device_id, body.wait, now)
        return PhoneReply(
            200,
            {
                "v": 1,
                "key": self._signer.public_key_hex,
                "answering": {"on": rule.on, "after_rings": rule.after_rings, "number": rule.on},
                "took": took,
                "commands": [c.wire() for c in commands],
                "decisions": decisions,
            },
        )

    def _check_in(self, device_id: str, checkin: CheckIn) -> None:
        self._checkins[device_id] = checkin
        self._checkins.move_to_end(device_id)
        while len(self._checkins) > DEVICES_MAX:
            self._checkins.popitem(last=False)

    async def _rule(self, uid: str) -> AnsweringRule:
        if self.answering is None:
            return AnsweringRule()
        try:
            return await self.answering.rule(uid)
        except Exception as exc:  # noqa: BLE001 - unknown means off: no number is kept
            log.warning("answering rule unreadable", extra={"error": type(exc).__name__})
            return AnsweringRule()

    async def _take(
        self, req: PhoneRequest, events: Sequence[AnyEvent], rule: AnsweringRule, now: float
    ) -> tuple[int, list[dict[str, str]], bool]:
        took, decisions = 0, list[dict[str, str]]()
        for ev in events[:EVENTS_MAX]:
            key = f"{req.device_id}:{ev.id}"
            if self._seen.seen(key, now):
                continue
            if not now - EVENT_MAX_AGE_S <= ev.at <= now + EVENT_AHEAD_S:
                log.info("phone call event out of time", extra={"type": ev.type})
                self._seen.add(key, now)
                continue
            try:
                outcome = await self._deliver(req, ev, rule)
            except Exception as exc:  # noqa: BLE001 - not taken: 503, the phone sends it again
                log.error("calls engine did not take an event", extra={"error": type(exc).__name__})
                return took, decisions, True
            self._seen.add(key, now)
            took += 1
            if isinstance(ev, CardEvent):
                decisions.append({"card_id": ev.card_id, "outcome": outcome or "unavailable"})
        return took, decisions, False

    async def _deliver(
        self, req: PhoneRequest, ev: AnyEvent, rule: AnsweringRule
    ) -> CardOutcome | None:
        uid, device = req.uid, req.device_id
        if isinstance(ev, StateEvent):
            number = ev.number_e164 if rule.on and ev.state == "ringing" else None
            state = CallStateEvent(
                call_id=ev.call_id,
                state=ev.state,
                number_e164=number,
                rings=ev.rings,
                at=_when(ev.at),
            )
            if self.sink is not None:
                await self.sink.phone_state(uid, state)
            self._remember(state)
            await self._record_event(ev.type, ev.state, number, device)
            return None
        if isinstance(ev, ResultEvent):
            result = PhoneCommandResult(
                device, ev.command_id, ev.call_id, ev.command, ev.ok, ev.code, float(ev.at)
            )
            if self.sink is not None:
                await self.sink.phone_result(uid, result)
            await self._record_event(ev.type, f"{ev.command}:{ev.code}", None, device)
            return None
        outcome: CardOutcome = "unavailable"
        if self.cards is not None:
            outcome = await self.cards.decide(uid, ev.card_id, ev.decision, device)
        await self._record_event(ev.type, f"{ev.decision}:{outcome}", None, device)
        return outcome

    def _remember(self, state: CallStateEvent) -> None:
        self._latest = state
        if state.call_id is None:
            return
        self._states[state.call_id] = state
        self._states.move_to_end(state.call_id)
        while len(self._states) > STATES_MAX:
            self._states.popitem(last=False)

    async def _wait(self, device_id: str, wait_s: int, now: float) -> list[Sealed]:
        bell = self._outbox.bell(device_id)
        bell.clear()  # before looking: a command queued from here on sets it again
        pending = self._outbox.pending(device_id, now)
        if pending or wait_s <= 0:
            return pending
        try:
            await asyncio.wait_for(bell.wait(), timeout=min(float(wait_s), self._max_wait))
        except TimeoutError:
            return []
        return self._outbox.pending(device_id, self._clock())

    # ---- the audit ----------------------------------------------------------------------------
    async def _record_command(self, outcome: str, cmd: PhoneCommand, device: str | None) -> None:
        args: dict[str, Any] = {"type": cmd.type, "subject": cmd.subject}
        if device is not None:
            args["device"] = device
        if isinstance(cmd, Dial):
            args["number"] = mask_number(cmd.number)
        await self._append("calls_phone_command", outcome, args)

    async def _record_event(self, kind: str, what: str, number: str | None, device: str) -> None:
        args: dict[str, Any] = {"type": kind, "what": what, "device": device}
        if number is not None:
            args["number"] = mask_number(number)
        await self._append("calls_phone_event", "received", args)

    async def _append(self, tool: str, outcome: str, args: dict[str, Any]) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.append(
                agent="calls", tool=tool, risk=ActionRisk.READ_ONLY, outcome=outcome, args=args
            )
        except Exception as exc:  # noqa: BLE001 - logged; the command or event already moved
            log.error("AUDIT WRITE FAILED for a call step", extra={"error": type(exc).__name__})


class OwnerPhoneLink:
    """I0's `PhoneLink` (`jarvis.calls.ports`) for one owner: what the calls engine holds."""

    def __init__(self, calls: PhoneCalls, uid: str) -> None:
        self._calls, self._uid = calls, uid

    async def send(self, command: ProtocolCommand | PhoneCommand) -> None:
        out = await self._calls.send(self._uid, command)
        if out.status != "queued":
            raise PhoneCommandRefused(out.code or out.status)

    def last_state(self) -> CallStateEvent | None:
        return self._calls.last_state()


__all__ = [
    "DIAL_MAX_S",
    "DOORBELL_KIND",
    "DOORBELL_TEXT",
    "DOOR_CAP",
    "DOOR_ROUTE",
    "EVENTS_PER_MINUTE",
    "EVENT_MAX_AGE_S",
    "OUTBOX_MAX",
    "TTL_S",
    "AnsweringRule",
    "AnsweringView",
    "ApprovalCheck",
    "CardDesk",
    "CardOutcome",
    "Doorbell",
    "OwnerPhoneLink",
    "PhoneCalls",
    "PhoneCommandRefused",
    "PhoneCommandResult",
    "PhoneDirectory",
    "PhoneEventSink",
    "PhoneReadiness",
    "PushDoorbell",
    "SendOutcome",
    "StoreDirectory",
]
