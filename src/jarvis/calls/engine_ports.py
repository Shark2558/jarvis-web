# src/jarvis/calls/engine_ports.py
"""What the call engine needs from the other R18 parts (R18 A2; I0-SEAMS.md; the I1 join wires
these). Structural Protocols: no part imports another part's class.

- `SpeechKit` (B, with the language table): the hearing, voice and detector chosen per language.
- `DialGate` (A1 approvals + limits): redeem the approval and count the call, just before
  `call.dial`.
- `SlotCheck` (A1 booking): is the brain's slot inside the card's windows.
- `RecordsSink` (A1 records): lines and audio as they come, the objection, the end (the vault
  writes and the calendar add with Undo).
- `OwnerNotice` (I1, `jarvis.notify`): the summary, an ask, the "tap Phone" note.
- `Spend` (`jarvis.calls.hub.BillingSpend`): every ₹ of model calls and of speech above the free
  allowances, and the owner's monthly limit.
- I0's `PhoneLink` (D, `jarvis.phone.calls`) and `DeskLink` (`jarvis.calls.hub.DeskProxy`).

`EngineDeps` holds one set of them per call (the hub swaps the desk per owner); `Timing` holds
every timeout; `brief_for` and `card_texts` turn the approved card into what the brain is told
and what the guard reads values from.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Literal, Protocol

from jarvis.calls.brain import CallBrain, CallBrief, FixedLines, Line
from jarvis.calls.captions import Captioner
from jarvis.calls.models import Booking, CallCard, CallRecord, CallSettings
from jarvis.calls.ports import CallStore, DeskLink, Hearing, LanguageDetector, PhoneLink, Voice
from jarvis.calls.protocol import DeskState
from jarvis.calls.summary import CallSummary, Summarizer
from jarvis.llm.base import Completion
from jarvis.tools.audit import AuditTrail


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---- what the engine needs from the other parts (Protocols; the I1 join wires them) -------------
class SpeechKit(Protocol):
    """B: the speech option the language check chose for each language."""

    def hearing(self, lang: str) -> Hearing: ...

    def voice(self, lang: str) -> Voice: ...

    def detector(self) -> LanguageDetector | None: ...

    def needs_balanced(self, lang: str) -> bool: ...


class DialGate(Protocol):
    """A1 (approvals + limits): redeem the approval (one use, 10 minutes, bound to the number and
    `card.digest()`), check the limits and count the call, in one go. None: dial. Otherwise the
    owner's plain words for the refusal; nothing is dialled. `call_id` (I1): the grant is spent
    for this call, so the phone's check of the dial (`call.dial`'s approval id) names it."""

    async def before_dial(
        self, uid: str, card: CallCard, approval_id: str, call_id: str
    ) -> str | None: ...


class SlotCheck(Protocol):
    """A1 (booking): is this slot inside the card's windows?"""

    def within(self, booking: Booking, day: date, start: time, end: time | None) -> bool: ...


@dataclass(frozen=True)
class BookedSlot:
    day: date
    start: time
    end: time | None

    def words(self) -> str:
        end = f"-{self.end:%H:%M}" if self.end else ""
        return f"{self.day.isoformat()} {self.start:%H:%M}{end}"


class RecordsSink(Protocol):
    """A1 (records in the vault): transcript lines and audio as the call goes, the objection
    (stop the audio recording and delete what was recorded for this call), and the end (vault
    writes, the calendar add with Undo for a booking). Returns the record with its references."""

    async def line(self, uid: str, call_id: str, line: Line) -> None: ...

    async def audio(self, uid: str, call_id: str, pcm: bytes) -> None: ...

    async def objection(self, uid: str, call_id: str) -> None: ...

    async def finish(
        self,
        uid: str,
        record: CallRecord,
        *,
        card: CallCard | None,
        summary: CallSummary,
        lines: Sequence[Line],
        booked: BookedSlot | None,
    ) -> CallRecord: ...


class OwnerNotice(Protocol):
    """I1 (`jarvis.notify`): a short note to the owner (the summary, an ask, "tap Phone")."""

    async def notice(self, uid: str, call_id: str, text: str) -> None: ...


Kind = Literal["hear", "voice"]


class Spend(Protocol):
    """I1 (`jarvis.billing` + `jarvis.calls.prices`): meter one model call or one speech use and
    return its ₹; `allowed` is the owner's overall monthly limit for the call brain."""

    async def model(self, uid: str, brain_id: str, completion: Completion) -> float: ...

    async def speech(self, uid: str, option: str, kind: Kind, units: float) -> float: ...

    async def allowed(self, uid: str) -> bool: ...


@dataclass(frozen=True)
class Timing:
    prepare_s: float = 8.0
    ring_s: float = 60.0
    answer_s: float = 15.0
    silence_s: float = 12.0
    laptop_say_s: float = 20.0
    desk_grace_s: float = 10.0
    ask_owner_s: float = 45.0
    dtmf_s: float = 3.0
    cap_grace_s: float = 10.0
    tick_s: float = 1.0
    lead_s: float = 0.3  # how far ahead of real time JARVIS's audio is sent to the desk
    pace: bool = True  # False in tests: no real-time sleeps


@dataclass(frozen=True)
class EngineDeps:
    desk: DeskLink
    phone: PhoneLink
    speech: SpeechKit
    brain: CallBrain
    captions: Captioner
    summarizer: Summarizer
    lines: FixedLines
    store: CallStore
    records: RecordsSink
    spend: Spend
    slots: SlotCheck
    notice: OwnerNotice
    audit: AuditTrail
    gate: DialGate | None = None
    clock: Callable[[], datetime] = _utcnow
    timing: Timing = field(default_factory=lambda: Timing())


def brief_for(card: CallCard | None, settings: CallSettings, languages: Sequence[str]) -> CallBrief:
    """What the brain is told: the card's fields, or the answering brief for a missed call."""
    first = settings.owner_first_name or "the owner"
    if card is None:
        return CallBrief(
            first_name=first,
            purpose="Take a message for the owner",
            languages=tuple(languages),
            mode="answering",
        )
    may = [*card.may_say, *(f"May agree to: {x}" for x in card.may_agree)]
    booking = None
    if card.booking is not None:
        b = card.booking
        windows = "; ".join(f"{w.day.isoformat()} {w.start:%H:%M}-{w.end:%H:%M}" for w in b.windows)
        give = f" Number to give: {b.give_number}." if b.give_number else ""
        booking = f"Acceptable: {windows}. Name to give: {b.give_name}.{give} Reason: {b.reason}."
    return CallBrief(
        first_name=first,
        purpose=card.purpose,
        may_say=tuple(may),
        booking=booking,
        languages=card.languages,
        mode="outgoing",
    )


def card_texts(card: CallCard | None, brief: CallBrief) -> list[str]:
    """Every text on the card the guard reads values from."""
    out = [brief.purpose, *brief.may_say, brief.booking or ""]
    if card is not None:
        out += [card.number_e164, card.contact_name]
        if card.booking and card.booking.give_number:
            out.append(card.booking.give_number)
    return out


def desk_problems(st: DeskState | None, *, connected: bool) -> list[str]:
    """The ready check's plain words (empty: ready). Nothing is dialled while any is left."""
    if st is None or not connected:
        return ["The laptop call desk is not connected."]
    out = [" ".join(p.split())[:200] for p in st.problems]
    if st.bt_headset:
        out.append("A Bluetooth headset is connected to the laptop: Phone Link refuses calls.")
    if not st.cable:
        out.append("VB-CABLE was not found on the laptop.")
    if not st.phone_link:
        out.append("Phone Link has no phone connected for calls.")
    if not st.ready and not out:
        out.append("The laptop call desk is not ready.")
    return out


__all__ = [
    "BookedSlot",
    "DialGate",
    "EngineDeps",
    "Kind",
    "OwnerNotice",
    "RecordsSink",
    "SlotCheck",
    "Spend",
    "SpeechKit",
    "Timing",
    "brief_for",
    "card_texts",
    "desk_problems",
]
