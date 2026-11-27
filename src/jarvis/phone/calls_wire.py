# src/jarvis/phone/calls_wire.py
"""R18 D: what travels between the cloud and the phone app for calls, byte for byte (the server
half of android core `Calls.kt`; shared vectors in tests/fixtures/r18/phone_calls_vectors.json).

**A command** (cloud -> phone) is the one JSON form (`contract.canonical_json`) of

    {"v":1, "id":"pc_<16 hex>", "d":<device id>, "type":<type>, "iat":<unix s>, "exp":<unix s>,
     ...the type's own fields, in this order}
    call.dial    call_id, number, approval_id, label
    call.answer  call_id
    call.end     call_id
    call.route   call_id, to ("phone" | "bluetooth")
    call.card    card_id, label, purpose, passkey

signed ECDSA P-256 / SHA-256 (DER, base64url without padding) over the ASCII line
`jarvis-cloud-v1`, one `\\n`, then the body's UTF-8 bytes. The four call types are I0's
`jarvis.calls.protocol` commands; `call.card` is the approval notification's (this module's).

**The calls door body** (phone -> cloud, `POST /phone/v1/calls`, signed like every door request):

    {"v":1, "app_version", "can":{"place","answer","state","number","notify"},
     "events":[...at most 8], "acks":["pc_..."], "wait":<0..25 s>}
    call.state     {id, type, call_id|null, state, number_e164|null, rings, at}
    call.result    {id, type, command_id, call_id|null, command, ok, code, at}
    card.decision  {id, type, card_id, decision, at}

Event ids are `pe_<16 hex>`; `at` is unix seconds (the door's integers-only rule). A number only on
a ringing call. Anything else, or any second way of writing the same body, is refused.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.calls.models import CALL_ID, CARD_ID, E164
from jarvis.calls.protocol import CallAnswer, CallDial, CallEnd, CallRoute
from jarvis.mobile import contract

SCHEME = "jarvis-cloud-v1"
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
SECRET_MIN = 32
EVENTS_MAX = 8
ACKS_MAX = 16
WAIT_MAX_S = 25
APPROVAL_ID = r"^[A-Za-z0-9_-]{8,128}$"
EVENT_ID = r"^pe_[0-9a-f]{16}$"
COMMAND_ID = r"^pc_[0-9a-f]{16}$"
# Indian numbers only: +91 and ten digits not starting with 0. No short code, emergency number,
# 1900 premium line or international number has this shape (A1's limits refuse them in words;
# this is also the shape the phone checks before it dials: defence in depth).
DIAL_NUMBER = r"^\+91[1-9][0-9]{9}$"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁠-⁩﻿]")

CommandType = Literal["call.dial", "call.answer", "call.end", "call.route", "call.card"]
CardDecision = Literal["approve", "decline"]


def mask_number(number: str | None) -> str:
    """`+91********01`: the country code and the last two digits, never more (logs, audit)."""
    if not number:
        return ""
    if len(number) <= 5:
        return "*" * len(number)
    head = 3 if number.startswith("+") else 0
    return number[:head] + "*" * (len(number) - head - 2) + number[-2:]


def plain(text: str, limit: int) -> str:
    """One line of plain text: no control or invisible characters, spaces collapsed."""
    return " ".join(_CONTROL.sub("", text).split())[:limit]


# ---- the commands ------------------------------------------------------------------------------
class _Command(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    @property
    def subject(self) -> str:
        """The call (or card) the command is about, for the audit and the outbox."""
        raise NotImplementedError

    def fields(self) -> dict[str, Any]:
        """The type's own fields, after the common ones, in the wire's order."""
        raise NotImplementedError


class Dial(_Command):
    type: Literal["call.dial"] = "call.dial"
    call_id: str = Field(pattern=CALL_ID)
    number: str = Field(pattern=DIAL_NUMBER)
    approval_id: str = Field(pattern=APPROVAL_ID)
    label: str = Field(default="", max_length=40)  # for "Tap to let JARVIS call <label>"

    @property
    def subject(self) -> str:
        return self.call_id

    def fields(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "number": self.number,
            "approval_id": self.approval_id,
            "label": plain(self.label, 40),
        }


class _OnCall(_Command):
    call_id: str = Field(pattern=CALL_ID)

    @property
    def subject(self) -> str:
        return self.call_id

    def fields(self) -> dict[str, Any]:
        return {"call_id": self.call_id}


class Answer(_OnCall):
    type: Literal["call.answer"] = "call.answer"


class End(_OnCall):
    type: Literal["call.end"] = "call.end"


class RouteTo(_OnCall):
    type: Literal["call.route"] = "call.route"
    to: Literal["phone", "bluetooth"]

    def fields(self) -> dict[str, Any]:
        return {"call_id": self.call_id, "to": self.to}


class Card(_Command):
    """A call card waiting for him: the phone shows Approve / Decline (`card.decision`)."""

    type: Literal["call.card"] = "call.card"
    card_id: str = Field(pattern=CARD_ID)
    label: str = Field(min_length=1, max_length=40)
    purpose: str = Field(default="", max_length=120)
    passkey: bool = False  # a never-called number: Approve opens the console for the passkey
    expires_at: float | None = None  # when the card stops waiting (unix s); not on the wire

    @property
    def subject(self) -> str:
        return self.card_id

    def fields(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "label": plain(self.label, 40),
            "purpose": plain(self.purpose, 120),
            "passkey": self.passkey,
        }

    @classmethod
    def for_card(cls, card: Any, *, expires_at: float | None = None) -> Card:
        """From I0's `CallCard`: its name (or "your call"), purpose and `new_number`."""
        label = plain(str(getattr(card, "contact_name", "") or ""), 40) or "your call"
        return cls(
            card_id=card.id,
            label=label,
            purpose=plain(str(card.purpose), 120),
            passkey=bool(card.new_number),
            expires_at=expires_at,
        )


PhoneCommand = Dial | Answer | End | RouteTo | Card
ProtocolCommand = CallDial | CallAnswer | CallEnd | CallRoute


def from_protocol(command: ProtocolCommand | PhoneCommand, *, label: str = "") -> PhoneCommand:
    """I0's protocol command as this module's (a dial is also held to `DIAL_NUMBER`: ValueError)."""
    if isinstance(command, Dial | Answer | End | RouteTo | Card):
        return command
    if isinstance(command, CallDial):
        return Dial(
            call_id=command.call_id,
            number=command.number,
            approval_id=command.approval_id,
            label=plain(label, 40),
        )
    if isinstance(command, CallAnswer):
        return Answer(call_id=command.call_id)
    if isinstance(command, CallEnd):
        return End(call_id=command.call_id)
    return RouteTo(call_id=command.call_id, to=command.to)


# ---- the cloud's signature -----------------------------------------------------------------------
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
        """A new key for this process (the phone learns it from the next door answer)."""
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
        der = contract._unb64url(sig)  # noqa: SLF001 - the contract's own strict decoder
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
    type: str
    subject: str
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
        "type": command.type,
        "iat": int(now),
        "exp": int(exp),
        **command.fields(),
    }
    text = contract.canonical_json(data).decode("utf-8")
    return Sealed(cid, command.type, command.subject, text, signer.sign(text), float(int(exp)))


# ---- the door body (phone -> cloud) --------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Can(_Strict):
    """What the app may do now (its permissions and notifications), sent with every request."""

    place: bool
    answer: bool
    state: bool
    number: bool
    notify: bool


class StateEvent(_Strict):
    id: str = Field(pattern=EVENT_ID)
    type: Literal["call.state"]
    call_id: str | None = Field(default=..., pattern=CALL_ID)
    state: Literal["ringing", "dialing", "active", "ended"]
    number_e164: str | None = Field(default=..., pattern=E164)
    rings: int = Field(ge=0, le=60)
    at: int = Field(ge=0, le=10**11)


class ResultEvent(_Strict):
    id: str = Field(pattern=EVENT_ID)
    type: Literal["call.result"]
    command_id: str = Field(pattern=COMMAND_ID)
    call_id: str | None = Field(default=..., pattern=CALL_ID)
    command: CommandType
    ok: bool
    code: str = Field(pattern=r"^[a-z_]{1,32}$")
    at: int = Field(ge=0, le=10**11)


class CardEvent(_Strict):
    id: str = Field(pattern=EVENT_ID)
    type: Literal["card.decision"]
    card_id: str = Field(pattern=CARD_ID)
    decision: CardDecision
    at: int = Field(ge=0, le=10**11)


AnyEvent = StateEvent | ResultEvent | CardEvent
Event = Annotated[AnyEvent, Field(discriminator="type")]


class CallsBody(_Strict):
    v: Literal[1]
    app_version: str = Field(pattern=r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")
    can: Can
    events: list[Event] = Field(max_length=EVENTS_MAX)
    acks: list[Annotated[str, Field(pattern=COMMAND_ID)]] = Field(max_length=ACKS_MAX)
    wait: int = Field(ge=0, le=WAIT_MAX_S)


def parse_body(raw: bytes) -> CallsBody | None:
    """The body, only when `raw` is exactly its one JSON form (as `phone.handlers.canonical`)."""
    try:
        data = json.loads(raw.decode("utf-8"))
        parsed = CallsBody.model_validate(data)
        same = contract.canonical_json(data) == raw
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError, ValidationError):
        return None
    if not same:
        return None
    for ev in parsed.events:  # a number only on a ringing (incoming) call, never otherwise
        if isinstance(ev, StateEvent) and ev.number_e164 is not None and ev.state != "ringing":
            return None
    return parsed


__all__ = [
    "ACKS_MAX",
    "DIAL_NUMBER",
    "EVENTS_MAX",
    "SCHEME",
    "WAIT_MAX_S",
    "Answer",
    "AnyEvent",
    "CallsBody",
    "Can",
    "Card",
    "CardDecision",
    "CardEvent",
    "CommandSigner",
    "CommandType",
    "Dial",
    "End",
    "PhoneCommand",
    "ProtocolCommand",
    "ResultEvent",
    "RouteTo",
    "Sealed",
    "StateEvent",
    "from_protocol",
    "mask_number",
    "parse_body",
    "plain",
    "seal",
    "verify_command",
]
