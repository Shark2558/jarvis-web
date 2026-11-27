# src/jarvis/calls/models.py
"""R18 "Calls from your laptop": the data every part shares (docs/plans/r18-calls/BUILD-BRIEF.md,
"Decisions fixed for the build"; I0 seams, docs/plans/r18-calls/I0-SEAMS.md).

Pure Pydantic v2 and the standard library (no `jarvis` import), so the call desk on the laptop and
the phone side can use the same shapes. Every cap and limit of the brief is a named constant here;
the owner's own caps live in `CallSettings` (stored by `jarvis.calls.settings`).

- `CallCard`: what the owner approves (number, purpose, what JARVIS may say and agree to, the
  languages, the booking fields, the limits, the ₹ estimate). `digest()` is what an approval is
  bound to: the number and the card's content, never its status or estimate.
- `CallRecord`: one call, outgoing or incoming: state, languages, times, ₹, vault references of the
  audio, transcript and summary, retention.
- `CallState`: the call's state machine (ready check -> dialling -> opening -> talking -> wrap-up).
- `Heard`, `LanguageResult`, `LangCheckBars`: hearing, the language check's result and its bars.

Numbers are E.164 (`+919000000001`); a model holds the plain number in memory only: the store
seals it (`jarvis.calls.store`). Nothing here logs.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Final, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ---- caps (owner settings; defaults from the brief, D6) ------------------------------------------
MONTH_CAP_INR: Final = 200  # calls, a month (inside his ₹3,000 limit)
MONTH_CAP_CEILING_INR: Final = 3_000  # never above his overall monthly limit
CALL_CAP_INR: Final = 20  # one call
CALL_CAP_CEILING_INR: Final = 200
CALL_MAX_MINUTES: Final = 6  # one call
CALL_MAX_MINUTES_CEILING: Final = 30

# ---- limits (fixed, D9; plan section 7 item 4) ---------------------------------------------------
CALLS_PER_DAY: Final = 10
CALLS_PER_NUMBER_PER_DAY: Final = 2
NEW_NUMBERS_PER_DAY: Final = 3
NO_ANSWER_REDIALS_PER_DAY: Final = 1  # at most one redial a day to a number that did not answer
QUIET_FROM: Final = time(21, 0)  # no calls 21:00-08:00 IST
QUIET_UNTIL: Final = time(8, 0)
QUIET_ZONE: Final = "Asia/Kolkata"
HOME_COUNTRY_CODE: Final = "+91"  # international numbers are refused
# Emergency and helpline short codes: never called (any number that is not a full +91 number is
# refused too; this list is for the card's plain words)
EMERGENCY_NUMBERS: Final = frozenset(
    {"100", "101", "102", "108", "112", "1091", "1098", "181", "1070", "1077", "1930", "14567"}
)
PREMIUM_PREFIXES: Final = ("1900",)  # premium-rate numbers (national form, after +91)

# ---- approvals, records, answering ---------------------------------------------------------------
APPROVAL_TTL_S: Final = 600  # an approval token: 10 minutes, one use, bound to number + digest
RETENTION_DAYS: Final = 30  # audio, transcript and summary (setting; "keep" pins one call)
RETENTION_DAYS_CEILING: Final = 30
ANSWER_AFTER_RINGS: Final = 5  # answering missed calls (off by default): after N rings
ANSWER_RINGS_MIN, ANSWER_RINGS_MAX = 2, 15
MAX_INDIAN_LANGUAGES_PER_CARD: Final = 3  # a card: English + up to 3 Indian languages
PURPOSE_MAX = 300
LINE_MAX = 200  # one "may say" / "may agree" line
LINES_MAX = 10
NAME_MAX = 60
OPENING_LINE: Final = (
    "Hello, this is JARVIS, an AI assistant calling on behalf of {first_name}. "
    "This call is recorded."
)

# ---- languages (BCP-47) --------------------------------------------------------------------------
ENGLISH: Final = "en-IN"
LANGUAGE_NAMES: Final[dict[str, str]] = {
    ENGLISH: "English",
    "as-IN": "Assamese",
    "bn-IN": "Bengali",
    "brx-IN": "Bodo",
    "doi-IN": "Dogri",
    "gu-IN": "Gujarati",
    "hi-IN": "Hindi",
    "kn-IN": "Kannada",
    "ks-IN": "Kashmiri",
    "kok-IN": "Konkani",
    "mai-IN": "Maithili",
    "ml-IN": "Malayalam",
    "mni-IN": "Manipuri",
    "mr-IN": "Marathi",
    "ne-IN": "Nepali",
    "or-IN": "Odia",
    "pa-IN": "Punjabi",
    "sa-IN": "Sanskrit",
    "sat-IN": "Santali",
    "sd-IN": "Sindhi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "ur-IN": "Urdu",
}
LANGUAGES: Final = tuple(LANGUAGE_NAMES)
SCHEDULED_LANGUAGES: Final = tuple(code for code in LANGUAGES if code != ENGLISH)

# ---- ids and shapes ------------------------------------------------------------------------------
E164 = r"^\+[1-9][0-9]{6,14}$"
CARD_ID = r"^cc_[0-9a-f]{12}$"
CALL_ID = r"^call_[0-9a-f]{12}$"
CARD_ID_RE = re.compile(CARD_ID)
CALL_ID_RE = re.compile(CALL_ID)
LANG_CODE = r"^[a-z]{2,3}-IN$"


def new_card_id() -> str:
    return f"cc_{secrets.token_hex(6)}"


def new_call_id() -> str:
    return f"call_{secrets.token_hex(6)}"


def is_language(code: str) -> bool:
    return code in LANGUAGE_NAMES


def opening_line(first_name: str) -> str:
    """The opening disclosure in English (the speech part pre-makes it per language)."""
    name = " ".join(first_name.split())
    if not name:
        raise ValueError("the owner's first name is needed for the opening line")
    return OPENING_LINE.format(first_name=name[:NAME_MAX])


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_languages(codes: tuple[str, ...]) -> tuple[str, ...]:
    if not codes:
        raise ValueError("a call needs at least one language")
    if len(set(codes)) != len(codes):
        raise ValueError("a language is listed twice")
    unknown = [c for c in codes if not is_language(c)]
    if unknown:
        raise ValueError(f"unknown language: {', '.join(unknown)}")
    if sum(1 for c in codes if c != ENGLISH) > MAX_INDIAN_LANGUAGES_PER_CARD:
        raise ValueError(f"at most {MAX_INDIAN_LANGUAGES_PER_CARD} Indian languages a call")
    return codes


def _check_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
    if len(lines) > LINES_MAX:
        raise ValueError(f"at most {LINES_MAX} lines")
    out = tuple(" ".join(x.split()) for x in lines)
    if any(not x or len(x) > LINE_MAX for x in out):
        raise ValueError(f"each line needs 1 to {LINE_MAX} characters")
    return out


# ---- enums ---------------------------------------------------------------------------------------
class Direction(StrEnum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"  # answering missed calls (row 104), message-taking only


class CardStatus(StrEnum):
    DRAFT = "draft"  # written, waiting for his tap
    APPROVED = "approved"  # approval token issued (10 minutes, one use)
    USED = "used"  # the call was placed with it
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class CallState(StrEnum):
    PREPARING = "preparing"  # ready check: desk on, audio path, phone linked, no BT headset
    DIALING = "dialing"  # the phone app dials (outgoing)
    RINGING = "ringing"  # an incoming call rings (answering)
    OPENING = "opening"  # the opening disclosure is being spoken
    TALKING = "talking"
    TAKEN_OVER = "taken_over"  # the owner took over; JARVIS is quiet, recording carries on
    WRAPPING_UP = "wrapping_up"  # hung up: summary, transcript, ₹, calendar add
    ENDED = "ended"
    FAILED = "failed"  # never connected, or the desk / phone failed
    NO_ANSWER = "no_answer"

    @property
    def terminal(self) -> bool:
        return self in (CallState.ENDED, CallState.FAILED, CallState.NO_ANSWER)


class EndReason(StrEnum):
    HUNG_UP = "hung_up"  # the other person ended it
    DONE = "done"  # JARVIS said goodbye
    OWNER_HANGUP = "owner_hangup"
    CAP_INR = "cap_inr"  # the call's or the month's ₹ cap
    CAP_MINUTES = "cap_minutes"
    NO_ANSWER = "no_answer"
    NOT_READY = "not_ready"  # the ready check failed: nothing was dialled
    DESK_LOST = "desk_lost"
    PHONE_LOST = "phone_lost"
    MENU_KEYS = "menu_keys"  # a phone menu needed keys that did not work
    ERROR = "error"


class AnswerPolicy(StrEnum):
    ALL = "all"
    CONTACTS = "contacts"  # saved contacts only
    NOT_CONTACTS = "not_contacts"  # everyone except saved contacts


class SpeechMode(StrEnum):
    CLOUD = "cloud"  # audio to cloud speech (Google free allowance, Azure F0, Bhashini, Sarvam)
    LAPTOP = "laptop"  # local models on the desk; only text reaches the cloud


class SpeechOption(StrEnum):
    LAPTOP = "laptop"
    GOOGLE = "google"
    AZURE = "azure"  # free tier F0 only: it cannot bill
    BHASHINI = "bhashini"
    SARVAM = "sarvam"  # paid: off unless the owner turns it on


class Speaker(StrEnum):
    THEM = "them"
    JARVIS = "jarvis"
    OWNER = "owner"


# ---- the call card -------------------------------------------------------------------------------
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TimeWindow(_Frozen):
    """One acceptable slot range for a booking, in the owner's zone (IST)."""

    day: date
    start: time
    end: time

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("a time window ends after it starts")
        return self


class Booking(_Frozen):
    """A booking call's fields (plan section 4, step 9): JARVIS accepts only a slot inside the
    windows and repeats it back; afterwards the calendar add (with Undo) if `add_to_calendar`."""

    windows: tuple[TimeWindow, ...] = Field(min_length=1, max_length=6)
    give_name: str = Field(min_length=1, max_length=NAME_MAX)
    give_number: str | None = Field(default=None, pattern=E164)
    reason: str = Field(min_length=1, max_length=PURPOSE_MAX)
    no_payment: bool = True  # fixed: JARVIS never agrees to pay
    duration_minutes: int = Field(default=30, ge=5, le=480)
    add_to_calendar: bool = True

    @field_validator("no_payment")
    @classmethod
    def _never_pays(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("a call never agrees to a payment")
        return v


class CardLimits(_Frozen):
    max_minutes: int = Field(default=CALL_MAX_MINUTES, ge=1, le=CALL_MAX_MINUTES_CEILING)
    max_inr: int = Field(default=CALL_CAP_INR, ge=1, le=CALL_CAP_CEILING_INR)


_DIGEST_FIELDS = (
    "number_e164",
    "direction",
    "purpose",
    "may_say",
    "may_agree",
    "languages",
    "template",
    "booking",
    "limits",
)


class CallCard(_Frozen):
    id: str = Field(default_factory=new_card_id, pattern=CARD_ID)
    direction: Direction = Direction.OUTGOING
    number_e164: str = Field(pattern=E164)
    contact_name: str = Field(default="", max_length=NAME_MAX)
    purpose: str = Field(min_length=1, max_length=PURPOSE_MAX)
    may_say: tuple[str, ...] = ()  # what JARVIS may tell them ("the address on file")
    may_agree: tuple[str, ...] = ()  # what it may agree to ("pickup tomorrow 10:00-12:00")
    languages: tuple[str, ...] = (ENGLISH,)  # the first is the opening language
    template: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$")
    booking: Booking | None = None
    limits: CardLimits = CardLimits()
    estimate_inr: float | None = Field(default=None, ge=0)  # None: not estimated (never ₹0)
    new_number: bool = False  # never called before: the approval needs his passkey
    status: CardStatus = CardStatus.DRAFT
    created_at: AwareDatetime = Field(default_factory=_utcnow)

    @field_validator("languages")
    @classmethod
    def _langs(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return _check_languages(v)

    @field_validator("may_say", "may_agree")
    @classmethod
    def _lines(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return _check_lines(v)

    @property
    def first_language(self) -> str:
        return self.languages[0]

    def digest(self) -> str:
        """SHA-256 of the number and the card's content: an approval binds to it, so a card edited
        after approval no longer matches. Status, estimate and times are not part of it."""
        body = self.model_dump(mode="json", include=set(_DIGEST_FIELDS))
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---- the call record -----------------------------------------------------------------------------
class CallRecord(_Frozen):
    id: str = Field(default_factory=new_call_id, pattern=CALL_ID)
    card_id: str | None = Field(default=None, pattern=CARD_ID)  # None: an incoming call
    direction: Direction = Direction.OUTGOING
    number_e164: str = Field(pattern=E164)
    contact_name: str = Field(default="", max_length=NAME_MAX)
    state: CallState = CallState.PREPARING
    end_reason: EndReason | None = None
    speech_mode: SpeechMode = SpeechMode.CLOUD
    languages_used: tuple[str, ...] = ()
    started_at: AwareDatetime
    answered_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    seconds: int = Field(default=0, ge=0)
    cost_inr: float = Field(default=0, ge=0)
    cost_parts: dict[str, float] = Field(default_factory=dict)  # hearing, voice, brain, summary
    recorded: bool = True  # audio kept (D8); False once the other person objected
    objected: bool = False  # recording stopped and deleted for this call
    audio_ref: str | None = None  # vault references (encrypted there)
    transcript_ref: str | None = None
    summary_ref: str | None = None
    booking_event_ref: str | None = None  # the calendar event added after a booking (Undo)
    keep: bool = False  # kept past retention by the owner
    retention_days: int = Field(default=RETENTION_DAYS, ge=1, le=RETENTION_DAYS_CEILING)

    @field_validator("languages_used")
    @classmethod
    def _known(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(not is_language(c) for c in v):
            raise ValueError("unknown language")
        return v

    @property
    def delete_after(self) -> datetime:
        return self.started_at + timedelta(days=self.retention_days)


# ---- hearing and the language check --------------------------------------------------------------
class Heard(_Frozen):
    lang: str = Field(pattern=LANG_CODE)
    text: str = Field(max_length=4_000)
    confidence: float = Field(ge=0, le=1)
    seconds: float = Field(ge=0)  # the audio's length (what hearing is priced by)


class LangCheckBars(_Frozen):
    """Plan 5.3: the bars a language must pass, per option."""

    hear_clips: int = 20
    hear_facts: float = 0.90  # key facts right
    max_cer: float = 0.15  # character error rate
    speak_sentences: int = 10
    speak_facts: float = 0.90
    human_samples: int = 3
    human_score: int = 4  # 1-5, a person over a real call
    p50_ms: int = 1500  # half the replies start within
    p90_ms: int = 2500  # 9 in 10 within
    brain_turns: int = 10


LANG_CHECK: Final = LangCheckBars()


class LanguageResult(_Frozen):
    lang: str = Field(pattern=LANG_CODE)
    option: SpeechOption
    checked_at: AwareDatetime
    hear_facts: float | None = Field(default=None, ge=0, le=1)
    cer: float | None = Field(default=None, ge=0)
    speak_facts: float | None = Field(default=None, ge=0, le=1)
    human_score: float | None = Field(default=None, ge=1, le=5)
    native_heard: bool = False  # "not yet heard by a native speaker" until scored
    p50_ms: int | None = Field(default=None, ge=0)
    p90_ms: int | None = Field(default=None, ge=0)
    brain_ok: bool | None = None
    needs_balanced: bool = False  # offered only with his YES (and its higher ₹)
    inr_per_minute: float | None = Field(default=None, ge=0)  # None: unknown, never shown as ₹0
    passed: bool = False
    why_failed: tuple[str, ...] = ()
    versions: dict[str, str] = Field(default_factory=dict)  # model / provider ids checked


# ---- the owner's settings ------------------------------------------------------------------------
class CallSettings(_Frozen):
    month_cap_inr: int = Field(default=MONTH_CAP_INR, ge=0, le=MONTH_CAP_CEILING_INR)
    call_cap_inr: int = Field(default=CALL_CAP_INR, ge=1, le=CALL_CAP_CEILING_INR)
    call_max_minutes: int = Field(default=CALL_MAX_MINUTES, ge=1, le=CALL_MAX_MINUTES_CEILING)
    default_languages: tuple[str, ...] = (ENGLISH,)
    answering_on: bool = False  # row 104: off by default
    answer_after_rings: int = Field(
        default=ANSWER_AFTER_RINGS, ge=ANSWER_RINGS_MIN, le=ANSWER_RINGS_MAX
    )
    answer_policy: AnswerPolicy = AnswerPolicy.ALL
    retention_days: int = Field(default=RETENTION_DAYS, ge=1, le=RETENTION_DAYS_CEILING)
    record_audio: bool = True  # D8
    allow_balanced: bool = False  # a language needing the balanced tier, only with his YES
    sarvam_on: bool = False  # paid speech, only with his YES
    owner_first_name: str = Field(default="", max_length=NAME_MAX)
    updated_at: AwareDatetime | None = None

    @field_validator("default_languages")
    @classmethod
    def _langs(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return _check_languages(v)


__all__ = [
    "ANSWER_AFTER_RINGS",
    "APPROVAL_TTL_S",
    "CALLS_PER_DAY",
    "CALLS_PER_NUMBER_PER_DAY",
    "CALL_CAP_INR",
    "CALL_ID",
    "CALL_ID_RE",
    "CALL_MAX_MINUTES",
    "CARD_ID",
    "CARD_ID_RE",
    "E164",
    "EMERGENCY_NUMBERS",
    "ENGLISH",
    "HOME_COUNTRY_CODE",
    "LANGUAGES",
    "LANGUAGE_NAMES",
    "LANG_CHECK",
    "LANG_CODE",
    "MAX_INDIAN_LANGUAGES_PER_CARD",
    "MONTH_CAP_INR",
    "NEW_NUMBERS_PER_DAY",
    "NO_ANSWER_REDIALS_PER_DAY",
    "OPENING_LINE",
    "PREMIUM_PREFIXES",
    "QUIET_FROM",
    "QUIET_UNTIL",
    "QUIET_ZONE",
    "RETENTION_DAYS",
    "SCHEDULED_LANGUAGES",
    "AnswerPolicy",
    "Booking",
    "CallCard",
    "CallRecord",
    "CallSettings",
    "CallState",
    "CardLimits",
    "CardStatus",
    "Direction",
    "EndReason",
    "Heard",
    "LangCheckBars",
    "LanguageResult",
    "Speaker",
    "SpeechMode",
    "SpeechOption",
    "TimeWindow",
    "is_language",
    "new_call_id",
    "new_card_id",
    "opening_line",
]
