# src/jarvis/phone/calls.py
"""R18 D: the cloud's half of the phone's call commands and call events
(docs/plans/r18-calls/BUILD-BRIEF.md, "Phone <-> cloud"; docs/plans/r18-calls.md sections 4, 8).

**How the cloud reaches the phone.** R7 gave the phone a signed door (phone -> cloud) and, the
other way, only Web Push: Chrome shows each push through the app's notification service (R7
D10). No Firebase, no socket the phone keeps open, no foreground service (R7 D9, D22). So a
command travels in two steps:

1. `send(uid, command)` signs it, puts it in the phone's outbox and rings the **doorbell**: one
   Web Push of the kind `call_command` with a plain sentence and never a number or a name (the
   laptop's browser shows the same sentence, which is harmless and tells him what is happening).
2. The app's notification service sees that kind, asks the door `POST /phone/v1/calls` (signed,
   checked by `DoorGate` like every door request: shape, flood, device, time, cap, nonce,
   signature, rate) and the answer carries every pending command. The phone also asks on every
   call-state change and when the app opens, so a lost push only delays a command.

**The cloud's signature.** Each command is the one JSON form (`contract.canonical_json`) of
`{v, id, d, kind, call_id, iat, exp, ...}`, signed ECDSA P-256 / SHA-256 (DER, base64url) over
`"jarvis-cloud-v1\\n" + body`. The phone acts on a command only when the signature verifies with
the key the door's answer gave it (`key`), `d` is its own device id, `exp` has not passed and `id`
was never acted on. The key comes from the keyring (`CommandSigner.from_secret`, the same key on
every start, like the VAPID key) or, until that purpose exists, `CommandSigner.ephemeral()`; the
phone takes the key from each door answer (TLS to its one built-in address), so a new key after a
restart costs nothing.

**A dial** needs a live approval: `ApprovalCheck.live_until(uid, approval_id, call_id, number)`
must give a time in the future, else nothing is queued (fail closed, also when the check fails).
The command lives until that time, at most `DIAL_MAX_S`; the phone dials by itself only while it
is fresh and otherwise asks for his tap (android `calls/CallActions.kt`).

**Events** (`call.state`, `call.result`, `card.decision`) come in the same door body. Each is the
strict shape below; at most `EVENTS_MAX` a request and `EVENTS_PER_MINUTE` a phone; one older
than `EVENT_MAX_AGE_S` or ahead of the clock is dropped (answered, never delivered); an event id
seen in the last `EVENT_SEEN_S` is a retry and is not delivered twice. An event id counts as seen
only after the engine took it, so an engine failure answers 503 and the phone's retry arrives.
An incoming number (`number_e164`, ringing only) reaches the engine only while answering missed
calls is on (`AnsweringView`); otherwise it is dropped on arrival. No log line carries a full
number (`mask_number`); the audit gets the masked form.

The interface the calls engine (builder A2) consumes is `PhoneCalls` (`send`, `last_state`,
`readiness`) and the `PhoneEventSink` it implements. What I1 wires is listed in
docs/plans/r18-calls/INTEGRATION-D.md.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.mobile import contract
from jarvis.mobile.ports import PhoneReply, PhoneRequest
from jarvis.phone.door import PerPhoneRate
from jarvis.phone.store import Phone

log = get_logger(__name__)

SCHEME = "jarvis-cloud-v1"
DOOR_ROUTE = "calls"
DOOR_CAP = 16 * 1024
DOORBELL_KIND = "call_command"
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
SECRET_MIN = 32
DIAL_MAX_S = 600  # an approval lives 10 minutes; a dial never outlives it
TTL_S: Mapping[str, int] = {
    "call.answer": 30,  # a ringing call does not wait
    "call.end": 120,
    "call.route": 60,
    "call.card": 600,
}
OUTBOX_MAX = 16
DEVICES_MAX = 8
EVENTS_MAX = 8
EVENTS_PER_MINUTE = 40
EVENT_MAX_AGE_S = 900  # a phone may hold an event a while when it is offline
EVENT_AHEAD_S = 120
EVENT_SEEN_S = 1800
EVENT_SEEN_MAX = 4096
ACKS_MAX = 16
WAIT_MAX_S = 25
CHECKIN_FRESH_S = 7 * 86_400
REJECTED: Mapping[str, str] = {"error": "input_rejected"}

CALL_ID = r"^[A-Za-z0-9_-]{4,64}$"
CARD_ID = r"^[A-Za-z0-9_-]{4,64}$"
APPROVAL_ID = r"^[A-Za-z0-9_-]{8,128}$"
EVENT_ID = r"^pe_[0-9a-f]{16}$"
COMMAND_ID = r"^pc_[0-9a-f]{16}$"
# Indian numbers only, ten digits after +91 and not starting with 0 (no short code, no emergency
# number, no 1900 premium line, nothing international can have this shape); the limits of A1
# say the same in words, this is the shape the phone also checks before it dials.
DIAL_NUMBER = r"^\+91[1-9][0-9]{9}$"
E164 = r"^\+[1-9][0-9]{6,14}$"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁠-⁩﻿]")

CallState = Literal["ringing", "dialing", "active", "ended"]
CommandKind = Literal["call.dial", "call.answer", "call.end", "call.route", "call.card"]
RouteTarget = Literal["phone", "bluetooth"]
CardDecision = Literal["approve", "decline"]
CardOutcome = Literal["approved", "declined", "passkey_needed", "gone", "unavailable"]
SendStatus = Literal["queued", "refused", "no_phone"]


def mask_number(number: str | None) -> str:
    """`+91********01`: the country code and the last two digits, never more (logs, audit)."""
    if not number:
        return ""
    if len(number) <= 5:
        return "*" * len(number)
    head = 3 if number.startswith("+") else 0
    return number[:head] + "*" * (len(number) - head - 2) + number[-2:]


def _plain(text: str, limit: int) -> str:
    return " ".join(_CONTROL.sub("", text).split())[:limit]


# ---- the commands (cloud -> phone) ---------------------------------------------------------
class _Command(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    def fields(self) -> dict[str, Any]:
        """The kind's own fields, after the common ones, in this order."""
        return {}


class Dial(_Command):
    kind: Literal["call.dial"] = "call.dial"
    call_id: str = Field(pattern=CALL_ID)
    number: str = Field(pattern=DIAL_NUMBER)
    approval_id: str = Field(pattern=APPROVAL_ID)
    label: str = Field(default="", max_length=40)  # the card's name for "Tap to let JARVIS call"

    def fields(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "approval_id": self.approval_id,
            "label": _plain(self.label, 40),
        }


class Answer(_Command):
    kind: Literal["call.answer"] = "call.answer"
    call_id: str = Field(pattern=CALL_ID)


class End(_Command):
    kind: Literal["call.end"] = "call.end"
    call_id: str = Field(pattern=CALL_ID)


class RouteTo(_Command):
    kind: Literal["call.route"] = "call.route"
    call_id: str = Field(pattern=CALL_ID)
    to: RouteTarget

    def fields(self) -> dict[str, Any]:
        return {"to": self.to}


class Card(_Command):
    """A call card waiting for him: the phone shows Approve / Decline (`card.decision`)."""

    kind: Literal["call.card"] = "call.card"
    card_id: str = Field(pattern=CARD_ID)
    label: str = Field(min_length=1, max_length=40)
    purpose: str = Field(default="", max_length=120)
    passkey: bool = False  # a never-called number: Approve opens the console for the passkey
    expires_at: float | None = None

    @property
    def call_id(self) -> str:
        return self.card_id

    def fields(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "label": _plain(self.label, 40),
            "purpose": _plain(self.purpose, 120),
            "passkey": self.passkey,
        }


PhoneCommand = Dial | Answer | End | RouteTo | Card

DOORBELL_TEXT: Mapping[str, str] = {
    "call.dial": "JARVIS is placing the call you approved.",
    "call.answer": "JARVIS is answering a call for you.",
    "call.end": "JARVIS is ending the call.",
    "call.route": "JARVIS is moving the call's sound.",
    "call.card": "A JARVIS call is waiting for your approval.",
}


# ---- the cloud's signature ------------------------------------------------------------------
def _signing_bytes(body: str) -> bytes:
    return f"{SCHEME}\n".encode("ascii") + body.encode("utf-8")


class CommandSigner:
    """The cloud's P-256 key for commands. Its private half is never stored or logged."""

    def __init__(self, private: ec.EllipticCurvePrivateKey) -> None:
        self._private = private
        raw = private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        self.public_key_hex = raw.hex()

    def __repr__(self) -> str:
        return "CommandSigner(<hidden>)"

    @classmethod
    def from_secret(cls, raw: bytes) -> CommandSigner:
        """The same key on every start: d = secret mod (n - 1) + 1 (as `VapidKey.from_secret`)."""
        if len(raw) < SECRET_MIN:
            raise ValueError("the command key's secret is too short")
        d = int.from_bytes(raw, "big") % (P256_ORDER - 1) + 1
        return cls(ec.derive_private_key(d, ec.SECP256R1()))

    @classmethod
    def ephemeral(cls) -> CommandSigner:
        return cls(ec.generate_private_key(ec.SECP256R1()))

    def sign(self, body: str) -> str:
        der = self._private.sign(_signing_bytes(body), ec.ECDSA(hashes.SHA256()))
        return contract.b64url(der)


def verify_command(public_key_hex: str, body: str, sig: str) -> bool:
    """What the phone checks (android core `CallCommands.verify`); here for tests and vectors."""
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), bytes.fromhex(public_key_hex)
        )
        der = contract._unb64url(sig)  # noqa: SLF001 - the contract's own decoder
        if not der:
            return False
        key.verify(der, _signing_bytes(body), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return False
    return True


@dataclass(frozen=True)
class Sealed:
    """A signed command in an outbox: `body` is exactly the signed text."""

    id: str
    kind: str
    call_id: str
    body: str
    sig: str
    exp: float

    def wire(self) -> dict[str, str]:
        return {"body": self.body, "sig": self.sig}


def seal(
    signer: CommandSigner,
    command: PhoneCommand,
    *,
    device_id: str,
    now: float,
    exp: float,
    command_id: str | None = None,
) -> Sealed:
    cid = command_id or f"pc_{secrets.token_hex(8)}"
    data: dict[str, Any] = {
        "v": 1,
        "id": cid,
        "d": device_id,
        "kind": command.kind,
        "call_id": command.call_id,
        "iat": int(now),
        "exp": int(exp),
        **command.fields(),
    }
    text = contract.canonical_json(data).decode("utf-8")
    return Sealed(cid, command.kind, command.call_id, text, signer.sign(text), float(int(exp)))


# ---- the events (phone -> cloud) -------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Can(_Strict):
    """What the app may do now (its permissions), sent with every calls request."""

    place: bool
    answer: bool
    state: bool
    number: bool
    notify: bool


class StateEvent(_Strict):
    id: str = Field(pattern=EVENT_ID)
    kind: Literal["call.state"]
    call_id: str | None = Field(default=..., pattern=CALL_ID)
    state: CallState
    number_e164: str | None = Field(default=..., pattern=E164)
    rings: int = Field(ge=0, le=60)
    at: int = Field(ge=0, le=10**11)


class ResultEvent(_Strict):
    id: str = Field(pattern=EVENT_ID)
    kind: Literal["call.result"]
    command_id: str = Field(pattern=COMMAND_ID)
    call_id: str | None = Field(default=..., pattern=CALL_ID)
    command: CommandKind
    ok: bool
    code: str = Field(pattern=r"^[a-z_]{1,32}$")
    at: int = Field(ge=0, le=10**11)


class CardEvent(_Strict):
    id: str = Field(pattern=EVENT_ID)
    kind: Literal["card.decision"]
    card_id: str = Field(pattern=CARD_ID)
    decision: CardDecision
    at: int = Field(ge=0, le=10**11)


Event = Annotated[StateEvent | ResultEvent | CardEvent, Field(discriminator="kind")]


class CallsBody(_Strict):
    v: Literal[1]
    app_version: str = Field(pattern=r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")
    can: Can
    events: list[Event] = Field(max_length=EVENTS_MAX)
    acks: list[Annotated[str, Field(pattern=COMMAND_ID)]] = Field(max_length=ACKS_MAX)
    wait: int = Field(ge=0, le=WAIT_MAX_S)


def parse_body(raw: bytes) -> CallsBody | None:
    """The body, only when `raw` is exactly its one JSON form (as `handlers.canonical`)."""
    try:
        data = json.loads(raw.decode("utf-8"))
        parsed = CallsBody.model_validate(data)
        same = contract.canonical_json(data) == raw
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError, ValidationError):
        return None
    if not same:
        return None
    for ev in parsed.events:  # a number only on a ringing call (incoming): never otherwise
        if isinstance(ev, StateEvent) and ev.number_e164 is not None and ev.state != "ringing":
            return None
    return parsed


# ---- what the calls engine gets --------------------------------------------------------------
@dataclass(frozen=True)
class PhoneCallState:
    """One `call.state` from the phone. `call_id` is None for a call JARVIS did not place (an
    incoming one before it is answered). `number_e164` is set only for a ringing incoming call
    while answering missed calls is on. `rings` counts rings so far (the app's estimate)."""

    device_id: str
    call_id: str | None
    state: CallState
    number_e164: str | None
    rings: int
    at: float


@dataclass(frozen=True)
class PhoneCommandResult:
    """What the phone did with a command: `ok`, and `code` such as `placed`, `needs_tap`,
    `refused`, `answered`, `ended`, `route_refused`, `no_permission`, `expired`."""

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
    ready: bool
    device_id: str | None
    problems: tuple[str, ...]


# ---- the ports (implemented elsewhere; documented here) --------------------------------------
class PhoneDirectory(Protocol):
    """The owner's linked phones (`StoreDirectory` reads Part C's `PhoneStore`)."""

    async def linked(self, uid: str) -> Sequence[Phone]: ...


class ApprovalCheck(Protocol):
    """A1's approvals: when the approval `approval_id` for this call and number ends (unix
    seconds), or None when it is not live or not bound to them. It must NOT spend the approval:
    the gateway did that when the call was placed; this only proves the dial is the approved one."""

    async def live_until(
        self, uid: str, approval_id: str, call_id: str, number_e164: str
    ) -> float | None: ...


class Doorbell(Protocol):
    """Wakes the phone; the number of devices that took it (`PushDoorbell` uses Web Push)."""

    async def ring(self, uid: str, kind: str, text: str) -> int: ...


class PhoneEventSink(Protocol):
    """A2's calls engine. Both are awaited before the door answers; raising means "not taken":
    the door answers 503 and the phone sends the event again."""

    async def phone_state(self, uid: str, state: PhoneCallState) -> None: ...

    async def phone_result(self, uid: str, result: PhoneCommandResult) -> None: ...


class CardDesk(Protocol):
    """A1's call cards: Approve / Decline tapped on the phone's notification. A card whose number
    was never called answers `passkey_needed` (the phone then opens the console for the passkey)."""

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
        sent = await service.send(uid, kind=kind, text=text)
        return int(sent)


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
        for cid in ids:
            if box is not None:
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


# ---- the service -----------------------------------------------------------------------------
class PhoneCalls:
    """The phone link of the calls engine (the I0 `PhoneLink` port) and the `calls` door route."""

    def __init__(
        self,
        *,
        phones: PhoneDirectory,
        signer: CommandSigner,
        approvals: ApprovalCheck,
        doorbell: Doorbell | None = None,
        sink: PhoneEventSink | None = None,
        cards: CardDesk | None = None,
        answering: AnsweringView | None = None,
        audit: Audit | None = None,
        clock: Callable[[], float] = time.time,
        max_wait_s: float = WAIT_MAX_S,
    ) -> None:
        self._phones, self._signer, self._approvals = phones, signer, approvals
        self._bell, self._sink, self._cards = doorbell, sink, cards
        self._answering, self._audit, self._clock = answering, audit, clock
        self._max_wait = max_wait_s
        self._outbox = Outbox()
        self._seen = SeenEvents()
        self._rate = PerPhoneRate(per_minute=EVENTS_PER_MINUTE, max_phones=DEVICES_MAX)
        self._checkins: dict[str, CheckIn] = {}
        self._states: OrderedDict[str, PhoneCallState] = OrderedDict()

    def door_handlers(self) -> dict[str, Callable[[PhoneRequest], Awaitable[PhoneReply]]]:
        """{route: handler} for `MobilePart.services["door"]` of the phone part (I1)."""
        return {DOOR_ROUTE: self.door}

    # ---- sending ------------------------------------------------------------------------------
    async def send(self, uid: str, command: PhoneCommand) -> SendOutcome:
        """Sign, queue and ring. Never raises; the outcome says what happened."""
        now = self._clock()
        exp = await self._expiry(uid, command, now)
        if exp is None:
            log.warning("phone command refused", extra={"kind": command.kind, "code": "approval"})
            await self._record("calls_phone_command", "refused", command, None)
            return SendOutcome("refused", code="approval")
        target = await self._target(uid)
        if target is None:
            await self._record("calls_phone_command", "no_phone", command, None)
            return SendOutcome("no_phone", code="no_phone")
        sealed = seal(self._signer, command, device_id=target, now=now, exp=exp)
        self._outbox.put(target, sealed)
        rang = await self._ring(uid, command.kind)
        log.info(
            "phone command queued",
            extra={"kind": command.kind, "device": target, "rang": rang},
        )
        await self._record("calls_phone_command", "queued", command, target)
        return SendOutcome("queued", device_id=target, command_id=sealed.id, rang=rang)

    async def _expiry(self, uid: str, command: PhoneCommand, now: float) -> float | None:
        if isinstance(command, Card):
            until = command.expires_at or now + TTL_S["call.card"]
            return min(until, now + TTL_S["call.card"]) if until > now else None
        if not isinstance(command, Dial):
            return now + TTL_S[command.kind]
        try:
            live = await self._approvals.live_until(
                uid, command.approval_id, command.call_id, command.number
            )
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
        if not phones:
            return None
        able = [p for p in phones if (c := self._checkins.get(p.id)) and c.can.place]
        if able:
            return max(able, key=lambda p: self._checkins[p.id].at).id
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
    def last_state(self, call_id: str) -> PhoneCallState | None:
        return self._states.get(call_id)

    async def readiness(self, uid: str) -> PhoneReadiness:
        """For the card's ready check: which phone, and what is missing (plain codes)."""
        target = await self._target(uid)
        if target is None:
            return PhoneReadiness(False, None, ("no_phone",))
        checkin = self._checkins.get(target)
        if checkin is None or self._clock() - checkin.at > CHECKIN_FRESH_S:
            return PhoneReadiness(True, target, ("not_checked_in",))
        problems = [
            word
            for word, ok in (
                ("cannot_place", checkin.can.place),
                ("cannot_answer", checkin.can.answer),
                ("no_call_state", checkin.can.state),
                ("no_notifications", checkin.can.notify),
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
        self._checkins[req.device_id] = CheckIn(body.can, now, body.app_version)
        if len(self._checkins) > DEVICES_MAX:
            self._checkins.pop(next(iter(self._checkins)))
        rule = await self._rule(req.uid)
        if body.events and not all(self._rate.allow(req.device_id, now) for _ in body.events):
            log.info("phone calls events over the rate", extra={"device": req.device_id})
            return PhoneReply(429, {"error": "rate_limited"})
        took, decisions, failed = await self._take(req, body.events, rule, now)
        if failed:
            return PhoneReply(503, {"error": "unavailable", "detail": "Try again in a moment."})
        self._outbox.ack(req.device_id, body.acks)
        commands = await self._wait(req.device_id, body.wait, now)
        answer: dict[str, Any] = {
            "v": 1,
            "key": self._signer.public_key_hex,
            "answering": {
                "on": rule.on,
                "after_rings": rule.after_rings,
                "number": rule.on,
            },
            "took": took,
            "commands": [c.wire() for c in commands],
            "decisions": decisions,
        }
        return PhoneReply(200, answer)

    async def _rule(self, uid: str) -> AnsweringRule:
        if self._answering is None:
            return AnsweringRule()
        try:
            return await self._answering.rule(uid)
        except Exception as exc:  # noqa: BLE001 - unknown means off: no number is kept
            log.warning("answering rule unreadable", extra={"error": type(exc).__name__})
            return AnsweringRule()

    async def _take(
        self,
        req: PhoneRequest,
        events: Sequence[StateEvent | ResultEvent | CardEvent],
        rule: AnsweringRule,
        now: float,
    ) -> tuple[int, list[dict[str, str]], bool]:
        took, decisions = 0, list[dict[str, str]]()
        for ev in events:
            key = f"{req.device_id}:{ev.id}"
            if self._seen.seen(key, now):
                continue
            if not now - EVENT_MAX_AGE_S <= ev.at <= now + EVENT_AHEAD_S:
                log.info("phone call event stale", extra={"kind": ev.kind})
                self._seen.add(key, now)
                continue
            try:
                outcome = await self._deliver(req, ev, rule)
            except Exception as exc:  # noqa: BLE001 - not taken: 503, the phone sends it again
                log.error("calls engine refused a phone event", extra={"error": type(exc).__name__})
                return took, decisions, True
            self._seen.add(key, now)
            took += 1
            if isinstance(ev, CardEvent):
                decisions.append({"card_id": ev.card_id, "outcome": outcome or "unavailable"})
        return took, decisions, False

    async def _deliver(
        self, req: PhoneRequest, ev: StateEvent | ResultEvent | CardEvent, rule: AnsweringRule
    ) -> CardOutcome | None:
        uid, device = req.uid, req.device_id
        if isinstance(ev, StateEvent):
            number = ev.number_e164 if rule.on and ev.state == "ringing" else None
            state = PhoneCallState(device, ev.call_id, ev.state, number, ev.rings, float(ev.at))
            if self._sink is not None:
                await self._sink.phone_state(uid, state)
            self._remember(state)
            await self._record_event(ev.kind, ev.state, number, device)
            return None
        if isinstance(ev, ResultEvent):
            result = PhoneCommandResult(
                device, ev.command_id, ev.call_id, ev.command, ev.ok, ev.code, float(ev.at)
            )
            if self._sink is not None:
                await self._sink.phone_result(uid, result)
            await self._record_event(ev.kind, ev.code, None, device)
            return None
        outcome: CardOutcome = "unavailable"
        if self._cards is not None:
            outcome = await self._cards.decide(uid, ev.card_id, ev.decision, device)
        await self._record_event(ev.kind, f"{ev.decision}:{outcome}", None, device)
        return outcome

    def _remember(self, state: PhoneCallState) -> None:
        if state.call_id is None:
            return
        self._states[state.call_id] = state
        self._states.move_to_end(state.call_id)
        while len(self._states) > 64:
            self._states.popitem(last=False)

    async def _wait(self, device_id: str, wait_s: int, now: float) -> list[Sealed]:
        pending = self._outbox.pending(device_id, now)
        if pending or wait_s <= 0:
            return pending
        bell = self._outbox.bell(device_id)
        bell.clear()
        try:
            await asyncio.wait_for(bell.wait(), timeout=min(float(wait_s), self._max_wait))
        except TimeoutError:
            return []
        return self._outbox.pending(device_id, self._clock())

    # ---- the audit ----------------------------------------------------------------------------
    async def _record(
        self, tool: str, outcome: str, command: PhoneCommand, device: str | None
    ) -> None:
        args: dict[str, Any] = {"kind": command.kind, "call_id": command.call_id}
        if device is not None:
            args["device"] = device
        if isinstance(command, Dial):
            args["number"] = mask_number(command.number)
        await self._append(tool, outcome, args)

    async def _record_event(self, kind: str, what: str, number: str | None, device: str) -> None:
        args: dict[str, Any] = {"kind": kind, "what": what, "device": device}
        if number is not None:
            args["number"] = mask_number(number)
        await self._append("calls_phone_event", "received", args)

    async def _append(self, tool: str, outcome: str, args: dict[str, Any]) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.append(
                agent="calls",
                tool=tool,
                risk=ActionRisk.READ_ONLY,
                outcome=outcome,
                args=args,
            )
        except Exception as exc:  # noqa: BLE001 - logged; the command or event already moved
            log.error("AUDIT WRITE FAILED for a call step", extra={"error": type(exc).__name__})


__all__ = [
    "DIAL_MAX_S",
    "DOORBELL_KIND",
    "DOOR_CAP",
    "DOOR_ROUTE",
    "EVENTS_MAX",
    "EVENTS_PER_MINUTE",
    "EVENT_MAX_AGE_S",
    "OUTBOX_MAX",
    "SCHEME",
    "TTL_S",
    "Answer",
    "AnsweringRule",
    "AnsweringView",
    "ApprovalCheck",
    "CallsBody",
    "Can",
    "Card",
    "CardDecision",
    "CardDesk",
    "CardOutcome",
    "CommandSigner",
    "Dial",
    "Doorbell",
    "End",
    "PhoneCallState",
    "PhoneCalls",
    "PhoneCommand",
    "PhoneCommandResult",
    "PhoneDirectory",
    "PhoneEventSink",
    "PhoneReadiness",
    "PushDoorbell",
    "RouteTo",
    "Sealed",
    "SendOutcome",
    "StoreDirectory",
    "mask_number",
    "parse_body",
    "seal",
    "verify_command",
]
