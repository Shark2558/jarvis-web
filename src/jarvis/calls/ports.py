# src/jarvis/calls/ports.py
"""R18 ports (BUILD-BRIEF.md "Ports"; I0-SEAMS.md): what each builder implements and the others
call. Structural (`typing.Protocol`): a part never imports another part's class.

- B: `Hearing`, `Voice`, `LanguageDetector` (speech adapters; Google via `jarvis.voice`, Azure F0,
  Bhashini, Sarvam over REST; laptop mode on the desk)
- I0: `CallStore` (`jarvis.calls.store.DocCallStore` / `MemoryCallStore`), `NumberSealer`
- A2: `DeskLink` (the desk's one WebSocket in the hub), `PhoneLink` (D's cloud -> phone channel)
- A1 / A2: `CallsApi` and `CallsSockets` (what the routes in `jarvis.api.calls_routes` call)

PCM is always 16 kHz mono signed 16-bit little-endian (`jarvis.calls.protocol`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol

from jarvis.calls.models import (
    CallCard,
    CallRecord,
    CallSettings,
    Heard,
    LanguageResult,
    SpeechOption,
)
from jarvis.calls.protocol import CallStateEvent, CloudToDesk, DeskState, PhoneCommand

if TYPE_CHECKING:
    from fastapi import WebSocket
    from pydantic import BaseModel


# ---- speech (B) ----------------------------------------------------------------------------------
class Hearing(Protocol):
    name: str  # a `SpeechOption` value, for metering and the language table

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard: ...


class Voice(Protocol):
    name: str

    async def speak(self, text: str, lang: str) -> bytes: ...  # PCM16 16 kHz mono


class LanguageDetector(Protocol):
    async def detect(self, pcm16k: bytes, candidates: Sequence[str]) -> tuple[str, float]: ...


class SpeechUnavailable(RuntimeError):
    """A speech option can't serve now (no key, quota, network): the caller tries the next one or
    ends the call politely. Its words never carry audio, text or a key."""


# ---- the store (I0) ------------------------------------------------------------------------------
class CallStoreUnreadable(RuntimeError):
    """A stored call document is not readable (or its number does not open): never "none"."""


class NumberSealer(Protocol):
    """Numbers are never stored in clear: sealed (AES-GCM, `Keyring` purpose `calls`) and
    referenced by a keyed hash (the per-number counters, "called before")."""

    def seal(self, uid: str, e164: str) -> str: ...

    def open(self, uid: str, sealed: str) -> str: ...

    def ref(self, uid: str, e164: str) -> str: ...


@dataclass(frozen=True)
class DayCounts:
    """One owner's calls on one IST day (the limits' counters)."""

    day: date
    calls: int = 0
    new_numbers: int = 0
    per_number: dict[str, int] = field(default_factory=dict)  # number ref -> calls today
    no_answer: dict[str, int] = field(default_factory=dict)  # number ref -> unanswered today

    def to_number(self, ref: str) -> int:
        return self.per_number.get(ref, 0)


# A limits check run INSIDE the counting transaction: a refusal's plain words, or None to count
LimitCheck = Callable[[DayCounts, bool], str | None]


class CallStore(Protocol):
    # cards
    async def put_card(self, uid: str, card: CallCard) -> None: ...

    async def get_card(self, uid: str, card_id: str) -> CallCard | None: ...

    async def delete_card(self, uid: str, card_id: str) -> None: ...

    # records
    async def put_record(self, uid: str, record: CallRecord) -> None: ...

    async def get_record(self, uid: str, call_id: str) -> CallRecord | None: ...

    async def list_records(self, uid: str, *, limit: int = 50) -> list[CallRecord]: ...

    async def delete_record(self, uid: str, call_id: str) -> bool: ...

    async def set_keep(self, uid: str, call_id: str, keep: bool) -> CallRecord | None: ...

    async def due_for_deletion(self, uid: str, now: datetime) -> list[CallRecord]: ...

    # counters and numbers
    async def known_number(self, uid: str, e164: str) -> bool: ...

    async def day_counts(self, uid: str, day: date) -> DayCounts: ...

    async def count_call(
        self, uid: str, day: date, e164: str, *, check: LimitCheck | None = None
    ) -> tuple[DayCounts, str | None]: ...

    async def count_no_answer(self, uid: str, day: date, e164: str) -> DayCounts: ...

    async def month_spend(self, uid: str, month: str) -> float: ...

    async def add_spend(self, uid: str, month: str, inr: float) -> float: ...

    # settings and the language table
    async def settings(self, uid: str) -> CallSettings: ...

    async def save_settings(self, uid: str, changes: dict[str, Any]) -> CallSettings: ...

    async def put_language_result(self, result: LanguageResult) -> None: ...

    async def language_results(self) -> list[LanguageResult]: ...


# ---- the desk and the phone (A2, C, D) -----------------------------------------------------------
class DeskLink(Protocol):
    async def send(self, msg: CloudToDesk) -> None: ...

    async def send_audio(self, pcm: bytes) -> None: ...  # framed as 0x02 by the link

    def is_ready(self) -> bool: ...

    def state(self) -> DeskState | None: ...


class PhoneLink(Protocol):
    async def send(self, command: PhoneCommand) -> None: ...

    def last_state(self) -> CallStateEvent | None: ...


# ---- what the routes call (A1, A2; wired by I1 on app.state) -------------------------------------
class CallsRefused(Exception):
    """A handler's refusal: the route answers `status` {error: code, detail: words}. Words are for
    the owner: never a full number, a transcript or a key."""

    def __init__(self, status: int, code: str, words: str) -> None:
        super().__init__(words)
        self.status, self.code, self.words = status, code, words


class CallsApi(Protocol):
    """`app.state.calls_api` (A1's `jarvis.api.calls_handlers_cards`, joined by I1). Each method
    returns a JSON-able model or dict; it raises `CallsRefused` to refuse."""

    async def create_card(self, uid: str, body: dict[str, Any]) -> BaseModel | dict[str, Any]: ...

    async def estimate(self, uid: str, body: dict[str, Any]) -> BaseModel | dict[str, Any]: ...

    async def get_card(self, uid: str, card_id: str) -> BaseModel | dict[str, Any]: ...

    async def approve(
        self, uid: str, card_id: str, body: dict[str, Any]
    ) -> BaseModel | dict[str, Any]: ...

    async def cancel(self, uid: str, card_id: str) -> BaseModel | dict[str, Any]: ...

    async def list_records(self, uid: str, limit: int) -> BaseModel | dict[str, Any]: ...

    async def get_record(self, uid: str, call_id: str) -> BaseModel | dict[str, Any]: ...

    async def delete_record(self, uid: str, call_id: str) -> BaseModel | dict[str, Any]: ...

    async def keep_record(
        self, uid: str, call_id: str, keep: bool
    ) -> BaseModel | dict[str, Any]: ...

    async def record_audio(self, uid: str, call_id: str) -> tuple[bytes, str]: ...  # bytes, type

    async def undo_booking(self, uid: str, call_id: str) -> BaseModel | dict[str, Any]: ...

    async def get_settings(self, uid: str) -> BaseModel | dict[str, Any]: ...

    async def put_settings(self, uid: str, body: dict[str, Any]) -> BaseModel | dict[str, Any]: ...

    async def languages(self, uid: str) -> BaseModel | dict[str, Any]: ...

    async def run_language_check(
        self, uid: str, body: dict[str, Any]
    ) -> BaseModel | dict[str, Any]: ...

    async def score_language(
        self, uid: str, body: dict[str, Any]
    ) -> BaseModel | dict[str, Any]: ...  # I1: {lang, option, scores}

    async def status(self, uid: str) -> BaseModel | dict[str, Any]: ...  # desk + phone ready


class CallsSockets(Protocol):
    """`app.state.calls_sockets` (A2's `jarvis.api.calls_ws`). It accepts or closes the socket
    itself. `desk`: unauthenticated here; A2 checks the desk's signed device credentials (the home
    bridge's signing, `jarvis.home.signing`) before `accept`. `live`: the route has already checked
    the owner (bearer token, or his session cookie from JARVIS's own origin) and passes his id."""

    async def desk(self, ws: WebSocket) -> None: ...

    async def live(self, ws: WebSocket, uid: str, call_id: str) -> None: ...


class DeskDoor(Protocol):
    """`app.state.calls_desk_door` (A2): linking the call desk, like the home bridge's link code.
    `code` and `unlink` are the owner's (console); `link` is the desk's own request with the code
    (no owner session), answering the desk's signing keys once."""

    async def code(self, uid: str) -> BaseModel | dict[str, Any]: ...

    async def link(self, body: dict[str, Any]) -> BaseModel | dict[str, Any]: ...

    async def unlink(self, uid: str) -> BaseModel | dict[str, Any]: ...


class DeskKit(Protocol):
    """`app.state.calls_desk_kit` (C): the call desk's kit zip, built like the home kit
    (reproducible bytes, so its SHA-256 shown in the console can be checked)."""

    def build(self) -> bytes: ...

    @property
    def version(self) -> str: ...


SPEECH_OPTIONS: tuple[SpeechOption, ...] = tuple(SpeechOption)

__all__ = [
    "SPEECH_OPTIONS",
    "CallStore",
    "CallStoreUnreadable",
    "CallsApi",
    "CallsRefused",
    "CallsSockets",
    "DayCounts",
    "DeskDoor",
    "DeskKit",
    "DeskLink",
    "Hearing",
    "LanguageDetector",
    "LimitCheck",
    "NumberSealer",
    "PhoneLink",
    "SpeechUnavailable",
    "Voice",
]
