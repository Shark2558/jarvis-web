# src/jarvis/calls/engine.py
"""The live call engine (R18 A2; docs/plans/r18-calls.md 4; Layers 3-5 and 8).

One `CallSession` per call: the state machine of `CallState`

    PREPARING --(ready check, Prepare, dial gate)--> DIALING (outgoing) | RINGING (answering)
      --(phone: active)--> OPENING (the disclosure) --> TALKING <--> TAKEN_OVER
      --(goodbye / they hang up / owner hangs up / a cap / desk or phone lost)--> WRAPPING_UP
      --(summary, record, ₹)--> ENDED | NO_ANSWER | FAILED

Every input arrives as a method call from the hub (desk messages and audio, phone events, the
owner's live controls); the work runs in the session's own tasks. Every outgoing call is dialled
only after `DialGate.before_dial` redeemed its approval (R3, one use, bound to the number and the
card) and counted it against the limits: the engine never dials on its own (no automatic redial:
a number that did not answer is counted, and trying again is a new card and a new tap).

A turn: the other person's speech (only while they speak) -> language detection -> hearing ->
the brain (fast tier, the card the only authority, their words untrusted) -> the guard (in code,
before anything is spoken; a refusal says the fixed check-back line instead) -> the voice. Caps:
the call's minutes and ₹, and the month's calls ₹; at a cap JARVIS says the goodbye line and ends.
Every ₹ (speech above the free allowances, brain, captions, fixed-line translations, summary) is
added to the record's `cost_parts`. Nothing here logs or audits audio, transcripts or numbers.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time as clock_time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from jarvis.calls.brain import (
    BrainReply,
    CallBrain,
    CallBrief,
    FixedLines,
    Line,
    LineKind,
    Slot,
)
from jarvis.calls.captions import Captioner, is_english
from jarvis.calls.guard import (
    GuardContext,
    card_values,
    check_dtmf,
    check_reply,
    heard_values,
)
from jarvis.calls.live import FRAME_S, LiveListener, LiveRoom, Mixer
from jarvis.calls.models import (
    ENGLISH,
    QUIET_ZONE,
    Booking,
    CallCard,
    CallRecord,
    CallSettings,
    CallState,
    Direction,
    EndReason,
    Speaker,
    SpeechMode,
    is_language,
)
from jarvis.calls.ports import CallStore, DeskLink, Hearing, LanguageDetector, PhoneLink, Voice
from jarvis.calls.protocol import (
    FRAME_BYTES,
    CallAnswer,
    CallDial,
    CallEnd,
    CallRoute,
    CallStateEvent,
    CloudToDesk,
    DeskState,
    DeskTakeover,
    Dtmf,
    LiveCaption,
    LiveState,
    PhoneCommand,
    Prepare,
    Release,
    SayText,
    StopSpeaking,
    split_frames,
)
from jarvis.calls.summary import CallSummary, Summarizer, fallback_summary
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import Completion, LLMError
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger
from jarvis.tools.audit import AuditTrail
from jarvis.tools.card import one_line

log = get_logger(__name__)

SWITCH_CONFIDENCE = 0.7  # a language switch needs at least this detector confidence
MIN_UTTERANCE_S = 0.3
MAX_UTTERANCE_S = 30.0
MAX_BRAIN_FAILURES = 2
MAX_UNSUPPORTED = 2
OWNER_LINES_MAX = 10
NOTES_MAX = 20
MIXER_BACKLOG_FRAMES = 100  # 2 s: one desk message carries up to 1 s
RECORD_CHUNK_FRAMES = 50  # one second of mixed audio per write to the records sink
SAMPLE_SECONDS = 1 / 32_000  # one byte of 16 kHz PCM16
DETECT_EXTRA = ("en-IN", "hi-IN", "ml-IN", "ta-IN", "te-IN", "kn-IN", "bn-IN", "mr-IN", "gu-IN")
TAP_PHONE = (
    "JARVIS handed the call to you. If the sound stays on the laptop, tap Phone on your phone's "
    "call screen."
)
_OBJECTION = re.compile(
    r"\b(?:do not|don't|dont|stop|no)\s+(?:record|recording)\b|\bnot\s+be\s+recorded\b|"
    r"\bwithout\s+recording\b|\bturn\s+off\s+(?:the\s+)?recording\b",
    re.IGNORECASE,
)


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
    owner's plain words for the refusal; nothing is dialled."""

    async def before_dial(self, uid: str, card: CallCard, approval_id: str) -> str | None: ...


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
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    timing: Timing = Timing()


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


class CallSession:
    def __init__(
        self,
        deps: EngineDeps,
        *,
        uid: str,
        record: CallRecord,
        card: CallCard | None,
        settings: CallSettings,
    ) -> None:
        self.d = deps
        self.uid = uid
        self.record = record
        self.card = card
        self.settings = settings
        langs = card.languages if card is not None else settings.default_languages
        self.brief = brief_for(card, settings, langs)
        self.allowed: tuple[str, ...] = tuple(langs)
        self.lang = self.allowed[0]
        self.used: list[str] = [self.lang]
        self.state = record.state
        self.room = LiveRoom()
        self.mixer = Mixer(MIXER_BACKLOG_FRAMES)
        self.lines: list[Line] = []
        self.owner_lines: list[str] = []
        self.notes: list[str] = []
        self.cost: dict[str, float] = {}
        self.recording = settings.record_audio
        self.objected = False
        self.taken_over = False
        self.booked: BookedSlot | None = None
        self.end_reason: EndReason | None = None
        self.outcome: str | None = None
        self.answered_at: datetime | None = None
        self.done = asyncio.Event()
        self._card_values = card_values(card_texts(card, self.brief))
        self._heard: list[str] = []
        self._utter = bytearray()
        self._them_speaking = False
        self._jarvis_speaking = False
        self._stop = asyncio.Event()  # set: stop the line being spoken now
        self._played: dict[str, asyncio.Event] = {}
        self._dtmf_done: asyncio.Event = asyncio.Event()
        self._prepared = asyncio.Event()
        self._phone: asyncio.Future[str] | None = None
        self._told = asyncio.Event()
        self._gen = 0
        self._reply_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._ending = False  # no new work: a goodbye or the end is under way
        self._closed = False  # `end` / `_finish` has started (once)
        self._voice = asyncio.Lock()  # one line spoken at a time
        self._quiet = asyncio.Event()  # set while JARVIS is not speaking
        self._quiet.set()
        self._month_spent = 0.0
        self._said_goodbye = False
        self._failures = 0
        self._unsupported_count = 0
        self._slot_retry = False
        self._still_asked = False
        self._last_activity = clock_time.monotonic()
        self._rec_buf = bytearray()
        self._utterance_seq = 0
        self._desk_lost_at: float | None = None

    # ---- small helpers ---------------------------------------------------------------------------
    @property
    def call_id(self) -> str:
        return self.record.id

    @property
    def total_inr(self) -> float:
        return round(sum(self.cost.values()), 4)

    def seconds(self) -> int:
        if self.answered_at is None:
            return 0
        return max(0, int((self.d.clock() - self.answered_at).total_seconds()))

    def _max_seconds(self) -> int:
        minutes = self.settings.call_max_minutes
        if self.card is not None:
            minutes = min(minutes, self.card.limits.max_minutes)
        return minutes * 60

    def _max_inr(self) -> float:
        cap = float(self.settings.call_cap_inr)
        if self.card is not None:
            cap = min(cap, float(self.card.limits.max_inr))
        return cap

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(_log_failure)
        return task

    async def settle(self) -> None:
        """Wait until no background work is left (tests, and the hub before forgetting a call)."""
        while self._tasks:
            pending = [t for t in self._tasks if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            else:  # done, their callbacks not run yet (gather would not yield: Python 3.12)
                await asyncio.sleep(0)

    def _touch(self) -> None:
        self._last_activity = clock_time.monotonic()
        self._still_asked = False

    def _guard(self) -> GuardContext:
        return GuardContext(
            card=self._card_values,
            heard=heard_values(self._heard),
            first_name=self.brief.first_name,
        )

    async def _audit(self, step: str, outcome: str = "ok", detail: str = "") -> None:
        risk = ActionRisk.IRREVERSIBLE if step in ("dial", "answer") else ActionRisk.READ_ONLY
        try:
            await self.d.audit.append(
                agent="calls",
                tool="calls.engine",
                risk=risk,
                outcome=outcome,
                args={"call_id": self.call_id, "step": step},
                detail=detail[:200],
            )
        except Exception as exc:  # noqa: BLE001 - an audit outage never stops a live call
            log.error("call audit failed", extra={"step": step, "error": type(exc).__name__})

    async def _charge(self, part: str, inr: float) -> None:
        if inr > 0:
            self.cost[part] = round(self.cost.get(part, 0.0) + inr, 6)
        await self._check_caps()

    async def _meter_model(self, part: str, completion: Completion | None) -> None:
        if completion is None:
            return
        try:
            inr = await self.d.spend.model(self.uid, self.d.brain.spec.id, completion)
        except Exception as exc:  # noqa: BLE001 - metering never breaks a call
            log.error("call meter failed", extra={"part": part, "error": type(exc).__name__})
            return
        await self._charge(part, inr)

    async def _meter_speech(self, option: str, kind: Kind, units: float) -> None:
        try:
            inr = await self.d.spend.speech(self.uid, option, kind, units)
        except Exception as exc:  # noqa: BLE001
            log.error("call meter failed", extra={"part": kind, "error": type(exc).__name__})
            return
        await self._charge("hearing" if kind == "hear" else "voice", inr)

    async def _send_desk(self, msg: CloudToDesk) -> bool:
        try:
            await self.d.desk.send(msg)
        except Exception as exc:  # noqa: BLE001 - a lost desk is handled by `on_desk_lost`
            log.warning("desk send failed", extra={"type": msg.type, "error": type(exc).__name__})
            return False
        return True

    async def _send_audio(self, pcm: bytes) -> bool:
        try:
            await self.d.desk.send_audio(pcm)
        except Exception as exc:  # noqa: BLE001
            log.warning("desk audio failed", extra={"error": type(exc).__name__})
            return False
        return True

    async def _send_phone(self, cmd: PhoneCommand) -> bool:
        try:
            await self.d.phone.send(cmd)
        except Exception as exc:  # noqa: BLE001 - the phone's own timeout ends the call
            log.warning("phone send failed", extra={"type": cmd.type, "error": type(exc).__name__})
            return False
        return True

    # ---- live listeners ------------------------------------------------------------------------
    def add_listener(self, listener: LiveListener) -> None:
        self.room.add(listener)
        listener.push_json(self._state_msg(listener))
        for line in self.lines[-20:]:
            listener.push_json(self._caption_msg(line))

    def _state_msg(self, listener: LiveListener) -> dict[str, Any]:
        return LiveState(
            call_id=self.call_id,
            state=self.state,
            lang=self.lang,
            seconds=self.seconds(),
            cost_inr=self.total_inr,
            listening=listener.wants_audio,
            taken_over=self.taken_over,
            recording=self.recording and not self.objected,
            end_reason=self.end_reason,
        ).model_dump(mode="json")

    def _caption_msg(self, line: Line) -> dict[str, Any]:
        lang = line.lang if is_language(line.lang) else ENGLISH
        return LiveCaption(
            who=Speaker(line.who), lang=lang, text=line.text[:2000], english=line.english[:2000]
        ).model_dump(mode="json")

    def _push_state(self) -> None:
        self.room.send_each(self._state_msg)

    def _set_state(self, state: CallState) -> None:
        self.state = state
        self._push_state()

    def set_listening(self, listener: LiveListener, audio: bool) -> None:
        listener.set_audio(audio)
        listener.push_json(self._state_msg(listener))

    # ---- audio out to listeners and the recording ------------------------------------------------
    def pump_audio(self) -> None:
        """One mixer tick: the mixed frame to listeners who want audio and to the recording."""
        frame = self.mixer.tick()
        if frame is None:
            return
        if self.room.wants_audio():
            self.room.audio(frame)
        if self.recording and not self.objected:
            self._rec_buf += frame
            if len(self._rec_buf) >= RECORD_CHUNK_FRAMES * FRAME_BYTES:
                self._flush_recording()

    def _flush_recording(self) -> None:
        if not self._rec_buf:
            return
        chunk, self._rec_buf = bytes(self._rec_buf), bytearray()
        if self.recording and not self.objected:
            self._spawn(self.d.records.audio(self.uid, self.call_id, chunk))

    async def _mixer_loop(self) -> None:
        start = clock_time.monotonic()
        n = 0
        while not self.state.terminal and self.state is not CallState.WRAPPING_UP:
            self.pump_audio()
            n += 1
            await asyncio.sleep(max(0.0, start + n * FRAME_S - clock_time.monotonic()))

    # ---- starting a call -----------------------------------------------------------------------
    async def start_outgoing(self, approval_id: str) -> None:
        """Ready check, Prepare, the dial gate, dial, wait for an answer, then the call."""
        if self.card is None or self.record.direction is not Direction.OUTGOING:
            raise ValueError("an outgoing call needs its card")
        if not await self._ready():
            return
        gate = self.d.gate
        refusal = (
            "no dial gate"
            if gate is None
            else await gate.before_dial(self.uid, self.card, approval_id)
        )
        if refusal is not None:
            await self._audit("dial", "refused", "gate")
            await self._send_desk(Release(call_id=self.call_id))
            await self._finish(EndReason.ERROR, outcome="failed", note=refusal)
            return
        self._spawn(self._prewarm())
        self._phone = asyncio.get_running_loop().create_future()
        self._set_state(CallState.DIALING)
        await self._audit("dial")
        number = self.card.number_e164
        await self._send_phone(
            CallDial(call_id=self.call_id, number=number, approval_id=approval_id)
        )
        await self._await_answer(self.d.timing.ring_s, no_answer=True)

    async def start_answering(self) -> None:
        """A missed call the answering policy said yes to (row 104): message-taking only."""
        if self.record.direction is not Direction.INCOMING:
            raise ValueError("answering is for incoming calls")
        if not await self._ready():
            return
        self._spawn(self._prewarm())
        self._phone = asyncio.get_running_loop().create_future()
        self._set_state(CallState.RINGING)
        await self._audit("answer")
        await self._send_phone(CallAnswer(call_id=self.call_id))
        await self._await_answer(self.d.timing.answer_s, no_answer=False)

    async def _ready(self) -> bool:
        month = self.d.clock().astimezone(ZoneInfo(QUIET_ZONE)).strftime("%Y-%m")
        try:
            self._month_spent = await self.d.store.month_spend(self.uid, month)
        except Exception as exc:  # noqa: BLE001 - fail closed: no call we can't account for
            log.error("calls month unreadable", extra={"error": type(exc).__name__})
            note = "This month's calls spend could not be read, so nothing was dialled."
            await self._finish(EndReason.NOT_READY, outcome="failed", note=note)
            return False
        if self._month_spent >= self.settings.month_cap_inr:
            note = "This month's calls limit is used up, so nothing was dialled."
            await self._finish(EndReason.CAP_INR, outcome="cap_rupees", note=note)
            return False
        problems = self._desk_problems(self.d.desk.state())
        if problems:
            await self._audit("ready", "not_ready", ",".join(problems))
            await self._finish(
                EndReason.NOT_READY, outcome="desk_not_ready", note="; ".join(problems)
            )
            return False
        mode = self.record.speech_mode
        await self._send_desk(Prepare(call_id=self.call_id, mode=mode, languages=self.allowed[:4]))
        try:
            await asyncio.wait_for(self._prepared.wait(), self.d.timing.prepare_s)
        except TimeoutError:
            await self._send_desk(Release(call_id=self.call_id))
            await self._audit("ready", "not_ready", "prepare_timeout")
            note = "The laptop call desk did not switch its audio for the call."
            await self._finish(EndReason.NOT_READY, outcome="desk_not_ready", note=note)
            return False
        return True

    def _desk_problems(self, st: DeskState | None) -> list[str]:
        if st is None or not self.d.desk.is_ready():
            return ["The laptop call desk is not connected."]
        out = [one_line(p, 200) for p in st.problems]
        if st.bt_headset:
            out.append("A Bluetooth headset is connected to the laptop: Phone Link refuses calls.")
        if not st.cable:
            out.append("VB-CABLE was not found on the laptop.")
        if not st.phone_link:
            out.append("Phone Link has no phone connected for calls.")
        if not st.ready and not out:
            out.append("The laptop call desk is not ready.")
        return out

    async def _prewarm(self) -> None:
        kinds = (LineKind.CHECK_BACK, LineKind.GOODBYE, LineKind.GOODBYE_CAP, LineKind.HANDOVER)
        for lang in self.allowed:
            for kind in kinds:
                await self._line(kind, lang)

    async def _await_answer(self, timeout: float, *, no_answer: bool) -> None:
        assert self._phone is not None
        try:
            got = await asyncio.wait_for(asyncio.shield(self._phone), timeout)
        except TimeoutError:
            got = "timeout"
        if self._closed:
            return  # the owner hung up while it rang: `end` finished the call
        if got != "active":
            if got == "timeout":
                await self._send_phone(CallEnd(call_id=self.call_id))
            await self._send_desk(Release(call_id=self.call_id))
            if no_answer and self.card is not None:
                day = self.d.clock().astimezone(ZoneInfo(QUIET_ZONE)).date()
                with contextlib.suppress(Exception):
                    await self.d.store.count_no_answer(self.uid, day, self.card.number_e164)
                await self._finish(EndReason.NO_ANSWER, outcome="no_answer")
            else:
                await self._finish(EndReason.PHONE_LOST, outcome="failed")
            return
        await self._connected()

    async def _connected(self) -> None:
        self.answered_at = self.d.clock()
        if self.d.timing.tick_s > 0:
            self._spawn(self._ticker())
        if self.d.timing.pace:
            self._spawn(self._mixer_loop())
        self._set_state(CallState.OPENING)
        kind = LineKind.OPENING if self.card is not None else LineKind.OPENING_ANSWERING
        await self._say_line(kind)
        if self._ending or self.taken_over:
            return
        self._set_state(CallState.TALKING)
        self._touch()
        self.schedule_reply()

    # ---- inputs from the desk ------------------------------------------------------------------
    def on_desk_state(self, st: DeskState) -> None:
        if st.ready and self.state is CallState.PREPARING:
            self._prepared.set()

    def on_mic(self, owner_mic: bool) -> None:
        if not owner_mic and self.state is CallState.PREPARING:
            self._prepared.set()

    def on_vad(self, speaking: bool) -> None:
        if not self._live():
            return
        self._touch()
        if speaking:
            self._them_speaking = True
            if self._jarvis_speaking:
                self._barge_in()
            return
        self._them_speaking = False
        self._close_utterance()

    def on_audio(self, pcm: bytes) -> None:
        """0x01 frames (whole 640-byte frames, already checked by the protocol)."""
        if not self._live():
            return
        for frame in split_frames(pcm):
            self.mixer.them(frame)
        if self.record.speech_mode is SpeechMode.CLOUD:
            self._utter += pcm
            if len(self._utter) * SAMPLE_SECONDS >= MAX_UTTERANCE_S:
                self._close_utterance()

    def on_heard_text(self, lang: str, text: str, confidence: float) -> None:
        """Laptop speech mode: the desk heard it itself."""
        if self._live():
            self._touch()
            self._spawn(self._heard_line(lang, text, confidence))

    def on_played(self, utterance_id: str) -> None:
        ev = self._played.get(utterance_id)
        if ev is not None:
            ev.set()

    def on_dtmf_done(self, digit: str) -> None:
        del digit
        self._dtmf_done.set()

    async def on_desk_error(self, code: str) -> None:
        await self._audit("desk_error", "error", code)

    def on_desk_lost(self) -> None:
        """The desk's socket closed: JARVIS can't hear or speak. A desk back within the grace
        carries on (Prepare again); otherwise the call is ended."""
        if self.state.terminal or self._closed or self._desk_lost_at is not None:
            return
        self._desk_lost_at = clock_time.monotonic()
        self._stop.set()
        if self.state is not CallState.PREPARING:  # `_ready` times out on its own
            self._spawn(self._desk_grace())

    async def _desk_grace(self) -> None:
        await asyncio.sleep(self.d.timing.desk_grace_s)
        if self._desk_lost_at is not None and not self.state.terminal and not self._closed:
            await self._audit("desk_lost", "error")
            await self.end(EndReason.DESK_LOST, outcome="desk_dropped", say_goodbye=False)

    async def on_desk_back(self) -> None:
        if self._desk_lost_at is None or self.state.terminal:
            return
        self._desk_lost_at = None
        mode = self.record.speech_mode
        await self._send_desk(Prepare(call_id=self.call_id, mode=mode, languages=self.allowed[:4]))

    def _live(self) -> bool:
        return self.state in (CallState.OPENING, CallState.TALKING, CallState.TAKEN_OVER)

    def _barge_in(self) -> None:
        self._stop.set()
        self._spawn(self._send_desk(StopSpeaking(call_id=self.call_id)))

    def _close_utterance(self) -> None:
        if self.record.speech_mode is not SpeechMode.CLOUD:
            return
        pcm, self._utter = bytes(self._utter), bytearray()
        if len(pcm) * SAMPLE_SECONDS < MIN_UTTERANCE_S:
            return
        self._spawn(self._hear(pcm))

    # ---- inputs from the phone -----------------------------------------------------------------
    async def on_phone_state(self, ev: CallStateEvent) -> None:
        if ev.state == "active" and self._phone is not None and not self._phone.done():
            self._phone.set_result("active")
        elif ev.state == "ended":
            if self._phone is not None and not self._phone.done():
                self._phone.set_result("ended")
            elif not self.state.terminal and self.state is not CallState.WRAPPING_UP:
                reason = EndReason.DONE if self._said_goodbye else EndReason.HUNG_UP
                await self.end(reason, say_goodbye=False, phone_ended=True)

    # ---- the owner's live controls -------------------------------------------------------------
    async def takeover(self, *, to_phone: bool = False) -> None:
        if self.taken_over or self.state not in (CallState.OPENING, CallState.TALKING):
            return
        self.taken_over = True
        self._gen += 1
        await self._audit("takeover", detail="phone" if to_phone else "laptop")
        await self._hush()
        await self._say_line(LineKind.HANDOVER)
        await self._send_desk(DeskTakeover(call_id=self.call_id))
        if to_phone:
            await self._send_phone(CallRoute(call_id=self.call_id, to="phone"))
            await self._notice(TAP_PHONE)
        self._set_state(CallState.TAKEN_OVER)

    async def tell(self, text: str) -> None:
        line = one_line(text, 500)
        if not line or self.state.terminal:
            return
        self.owner_lines = [*self.owner_lines, line][-OWNER_LINES_MAX:]
        await self._audit("tell")
        self._told.set()
        if self.state is CallState.TALKING and not self._busy():
            self.schedule_reply()

    async def hangup(self) -> None:
        await self._audit("hangup")
        await self.end(EndReason.OWNER_HANGUP, outcome="hung_up", say_goodbye=False)

    def _busy(self) -> bool:
        running = self._reply_task is not None and not self._reply_task.done()
        return running or self._jarvis_speaking or self._them_speaking

    # ---- hearing -------------------------------------------------------------------------------
    async def _hear(self, pcm: bytes) -> None:
        candidates = self.allowed
        detector = self.d.speech.detector()
        lang, conf = self.lang, 0.0
        if detector is not None:
            extra = tuple(c for c in DETECT_EXTRA if c not in self.allowed)
            try:
                lang, conf = await detector.detect(pcm, (*self.allowed, *extra))
            except Exception as exc:  # noqa: BLE001 - detection is a hint; hearing goes on
                log.warning("language detection failed", extra={"error": type(exc).__name__})
                lang, conf = self.lang, 0.0
        hear_lang = lang if lang in self.allowed and conf >= SWITCH_CONFIDENCE else self.lang
        if lang not in self.allowed and conf >= SWITCH_CONFIDENCE:
            await self._unsupported()
            return
        hearing = self.d.speech.hearing(hear_lang)
        langs = [hear_lang] if detector is not None else list(candidates)
        try:
            heard = await hearing.transcribe(pcm, langs)
        except Exception as exc:  # noqa: BLE001 - a missed line is asked again
            log.warning(
                "hearing failed", extra={"option": hearing.name, "error": type(exc).__name__}
            )
            await self._meter_speech(hearing.name, "hear", len(pcm) * SAMPLE_SECONDS)
            if self.state is CallState.TALKING and not self.taken_over:
                await self._say_line(LineKind.REPEAT)
            return
        await self._meter_speech(hearing.name, "hear", heard.seconds)
        confidence = conf if detector is not None else heard.confidence
        await self._heard_line(heard.lang, heard.text, confidence)

    async def _heard_line(self, lang: str, text: str, confidence: float) -> None:
        text = one_line(text, 2000)
        if not text:
            return
        if lang != self.lang and confidence >= SWITCH_CONFIDENCE:
            if lang in self.allowed:
                self._switch(lang)
            elif is_language(lang):
                await self._unsupported()
                return
        if not is_language(lang):
            lang = self.lang
        self._heard.append(text)
        english = text if is_english(lang) else ""
        line = Line(who="them", lang=lang, text=text, english=english)
        self.lines.append(line)
        if english or self.taken_over or self.state is not CallState.TALKING:
            await self._caption(len(self.lines) - 1)
        if english and _OBJECTION.search(english):
            await self._objection()
        if self.state is CallState.TALKING and not self.taken_over and not self._ending:
            self.schedule_reply()

    async def _caption(self, index: int, english: str | None = None) -> None:
        """Finish line `index`'s English (given, its own, or one translation), then send it to the
        listeners and the records."""
        line = self.lines[index]
        if english is None and not line.english:
            cap = await self.d.captions.english(line.text, line.lang)
            await self._meter_model("captions", cap.completion)
            english = cap.english
        if english is not None and not line.english:
            line = Line(
                who=line.who, lang=line.lang, text=line.text, english=one_line(english, 600)
            )
            self.lines[index] = line
            if line.who == "them" and _OBJECTION.search(line.english):
                await self._objection()
        self.room.send(self._caption_msg(line))
        await self.d.records.line(self.uid, self.call_id, line)

    def _switch(self, lang: str) -> None:
        if lang == self.lang or lang not in self.allowed:
            return
        self.lang = lang
        if lang not in self.used:
            self.used.append(lang)
        self._push_state()

    async def _unsupported(self) -> None:
        self._unsupported_count += 1
        self._gen += 1
        text = FixedLines.english(
            LineKind.UNSUPPORTED, self.brief.first_name, languages=self.allowed
        )
        await self._speak(text, ENGLISH, english=text)
        hindi, done = await self.d.lines.text(
            LineKind.UNSUPPORTED, "hi-IN", self.brief.first_name, languages=self.allowed
        )
        await self._meter_model("lines", done)
        await self._speak(hindi, "hi-IN", english=text, required=False)
        if self._unsupported_count >= MAX_UNSUPPORTED:
            await self.end(EndReason.DONE, outcome="unsupported_language", say_goodbye=False)

    # ---- the brain's turn ----------------------------------------------------------------------
    def schedule_reply(self) -> None:
        self._gen += 1
        if self._reply_task is None or self._reply_task.done():
            self._reply_task = self._spawn(self._reply_loop())

    def _tier(self) -> ModelTier:
        if self.settings.allow_balanced and self.d.speech.needs_balanced(self.lang):
            return ModelTier.BALANCED
        return ModelTier.FAST

    async def _reply_loop(self) -> None:
        while not self._ending and not self.taken_over and not self.state.terminal:
            gen = self._gen
            if not await self.d.spend.allowed(self.uid):
                await self.cap(EndReason.CAP_INR)
                return
            try:
                turn = await self.d.brain.reply(
                    self.brief,
                    self.lines,
                    lang=self.lang,
                    seconds_left=self._max_seconds() - self.seconds(),
                    owner_lines=self.owner_lines,
                    notes=self.notes,
                    tier=self._tier(),
                )
            except LLMError as exc:
                log.warning("call brain failed", extra={"error": type(exc).__name__})
                await self._brain_failed()
                return
            await self._meter_model("brain", turn.completion)
            if gen != self._gen or self._ending or self.taken_over:
                continue  # newer words or an instruction arrived meanwhile: think again
            again = await self._act(turn.reply)
            if not again:
                return

    async def _brain_failed(self) -> None:
        self._failures += 1
        if self._failures >= MAX_BRAIN_FAILURES:
            await self._say_line(LineKind.CHECK_BACK)
            await self.end(EndReason.ERROR, outcome="brain_failed", say_goodbye=True)
            return
        await self._say_line(LineKind.REPEAT)

    async def _act(self, reply: BrainReply | None) -> bool:
        """Carry out one reply. True: ask the brain again (a slot outside the limits)."""
        if reply is None:
            await self._brain_failed()
            return False
        self._failures = 0
        await self._take_captions(reply)
        if reply.note:
            self.notes = [*self.notes, one_line(reply.note, 200)][-NOTES_MAX:]
        if reply.recording_objection:
            await self._objection()
        action = reply.action
        if action == "switch_language":
            if reply.lang in self.allowed:
                self._switch(reply.lang)
            else:
                await self._unsupported()
                return False
        if action == "book_slot":
            return await self._book(reply)
        if action == "dtmf":
            if self.card is not None:  # never on a missed call JARVIS answered
                await self._press(reply.keys or "")
            if reply.say.strip():
                await self._say_checked(reply)
            return False
        if action == "ask_owner":
            return await self._ask_owner(reply)
        await self._say_checked(reply)
        if action == "end":
            await self.end(EndReason.DONE, say_goodbye=False)
        return False

    async def _take_captions(self, reply: BrainReply) -> None:
        """The brain's `heard_english` captions their newest line (no extra call); any older
        line still without English gets its own translation."""
        waiting = [i for i, x in enumerate(self.lines) if x.who == "them" and not x.english]
        for i in waiting:
            newest = i == waiting[-1]
            await self._caption(i, (reply.heard_english.strip() or None) if newest else None)

    async def _say_checked(self, reply: BrainReply) -> None:
        verdict = check_reply(reply.say, reply.say_english, self._guard())
        if not verdict.ok:
            log.info("call reply refused by the guard", extra={"reasons": list(verdict.reasons)})
            await self._audit("guard", "refused", ",".join(verdict.reasons))
            await self._say_line(LineKind.CHECK_BACK)
            return
        english = reply.say_english if reply.say_english else reply.say
        await self._speak(reply.say, self.lang, english=english)

    async def _book(self, reply: BrainReply) -> bool:
        slot = reply.slot
        booking = self.card.booking if self.card is not None else None
        parsed = _parse_slot(slot)
        if booking is not None and parsed is not None and self.d.slots.within(booking, *parsed):
            self.booked = BookedSlot(*parsed)
            self._slot_retry = False
            await self._audit("booked")
            await self._say_checked(reply)
            return False
        await self._audit("booked", "outside")
        if booking is None or self._slot_retry:
            self._slot_retry = False
            await self._say_line(LineKind.CHECK_BACK)
            return False
        self._slot_retry = True
        words = f"{slot.date} {slot.start}" if slot is not None else "the slot"
        self.notes = [
            *self.notes,
            f"The slot {words} is outside the card's booking limits: "
            "do not accept it; ask for a time inside them.",
        ][-NOTES_MAX:]
        self._gen += 1
        return True

    async def _press(self, keys: str) -> None:
        verdict = check_dtmf(keys, self._guard())
        if not verdict.ok:
            await self._audit("dtmf", "refused", ",".join(verdict.reasons))
            return
        await self._audit("dtmf", detail=str(len(keys)))
        for digit in keys:
            self._dtmf_done.clear()
            await self._send_desk(Dtmf(call_id=self.call_id, digit=digit))
            try:
                await asyncio.wait_for(self._dtmf_done.wait(), self.d.timing.dtmf_s)
            except TimeoutError:
                await self._audit("dtmf", "no_answer")
                self.notes = [*self.notes, "A phone menu key could not be pressed."][-NOTES_MAX:]
                return

    async def _ask_owner(self, reply: BrainReply) -> bool:
        """Hold, ask the owner, wait for his Tell JARVIS. True: think again with his answer."""
        verdict = check_reply(reply.say or "x", reply.say_english, self._guard())
        if reply.say.strip() and verdict.ok:
            await self._speak(reply.say, self.lang, english=reply.say_english or reply.say)
        else:
            await self._say_line(LineKind.HOLD)
        question = one_line(reply.question or "JARVIS needs your answer on the call.", 300)
        self._told.clear()
        await self._audit("ask_owner")
        await self._notice(f"JARVIS asks: {question}")
        self.room.send(
            self._caption_msg(
                Line(who="jarvis", lang=ENGLISH, text="", english=f"(to you) {question}")
            )
        )
        try:
            await asyncio.wait_for(self._told.wait(), self.d.timing.ask_owner_s)
        except TimeoutError:
            await self._say_line(LineKind.CHECK_BACK)
            await self.end(EndReason.DONE, say_goodbye=True)
            return False
        return True

    async def _objection(self) -> None:
        if self.objected:
            return
        self.objected = True
        self.recording = False
        self._rec_buf = bytearray()
        await self._audit("objection")
        try:
            await self.d.records.objection(self.uid, self.call_id)
        except Exception as exc:  # noqa: BLE001 - said; retried by the retention job's delete
            log.error("recording not deleted", extra={"error": type(exc).__name__})
        self._push_state()

    # ---- speaking ------------------------------------------------------------------------------
    async def _line(self, kind: LineKind, lang: str) -> str:
        text, done = await self.d.lines.text(
            kind, lang, self.brief.first_name, languages=self.allowed
        )
        await self._meter_model("lines", done)
        return text

    async def _say_line(self, kind: LineKind) -> None:
        text = await self._line(kind, self.lang)
        english = FixedLines.english(kind, self.brief.first_name, languages=self.allowed)
        await self._speak(text, self.lang, english=english)
        if kind in (LineKind.GOODBYE, LineKind.GOODBYE_CAP):
            self._said_goodbye = True

    async def _hush(self) -> None:
        """Stop the line being spoken (if any) and wait until JARVIS is quiet."""
        if self._jarvis_speaking:
            self._barge_in()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._quiet.wait(), self.d.timing.laptop_say_s)

    async def _speak(self, text: str, lang: str, *, english: str, required: bool = True) -> None:
        """Say one line (already guarded or fixed). Lines are spoken one at a time."""
        async with self._voice:
            if self._desk_lost_at is not None or self.state.terminal:
                return
            line = Line(who="jarvis", lang=lang, text=text, english=english)
            self.lines.append(line)
            self.room.send(self._caption_msg(line))
            await self.d.records.line(self.uid, self.call_id, line)
            self._stop.clear()
            self._jarvis_speaking = True
            self._quiet.clear()
            try:
                if self.record.speech_mode is SpeechMode.LAPTOP:
                    await self._speak_on_laptop(text, lang)
                else:
                    await self._speak_in_cloud(text, lang, required=required)
            finally:
                self._jarvis_speaking = False
                self._quiet.set()
                self._touch()

    async def _speak_on_laptop(self, text: str, lang: str) -> None:
        self._utterance_seq += 1
        utt = f"u{self._utterance_seq}"
        played = asyncio.Event()
        self._played[utt] = played
        msg = SayText(call_id=self.call_id, utterance_id=utt, lang=lang, text=text[:2000])
        await self._send_desk(msg)
        stop = asyncio.ensure_future(self._stop.wait())
        done = asyncio.ensure_future(played.wait())
        try:
            await asyncio.wait(
                {stop, done},
                timeout=self.d.timing.laptop_say_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            stop.cancel()
            done.cancel()
            self._played.pop(utt, None)

    async def _speak_in_cloud(self, text: str, lang: str, *, required: bool) -> None:
        try:
            voice = self.d.speech.voice(lang)
            pcm = await voice.speak(text, lang)
            frames = split_frames(pcm) if pcm else []
        except Exception as exc:  # noqa: BLE001 - no voice: a required line ends the call
            log.error("call voice failed", extra={"error": type(exc).__name__})
            if required and not self._closed:
                self._spawn(self.end(EndReason.ERROR, outcome="failed", say_goodbye=False))
            return
        await self._meter_speech(voice.name, "voice", len(text))
        if not self._stop.is_set():
            await self._send_paced(frames)

    async def _send_paced(self, frames: list[bytes]) -> None:
        """JARVIS's voice to the desk at most `lead_s` ahead of real time, a few frames per
        message, stopping at once on barge-in, takeover or the end."""
        timing = self.d.timing
        start = clock_time.monotonic()
        step = 5  # 100 ms a message
        for i in range(0, len(frames), step):
            if self._stop.is_set() or self._desk_lost_at is not None:
                return
            chunk = frames[i : i + step]
            if not await self._send_audio(b"".join(chunk)):
                return
            for frame in chunk:
                self.mixer.jarvis(frame)
            if timing.pace:
                ahead = start + (i + len(chunk)) * FRAME_S - timing.lead_s - clock_time.monotonic()
                if ahead > 0:
                    stop = asyncio.ensure_future(self._stop.wait())
                    try:
                        await asyncio.wait({stop}, timeout=ahead)
                    finally:
                        stop.cancel()
        if timing.pace and not self._stop.is_set():
            await asyncio.sleep(timing.lead_s)

    async def _notice(self, text: str) -> None:
        try:
            await self.d.notice.notice(self.uid, self.call_id, text)
        except Exception as exc:  # noqa: BLE001 - a missed note never stops a call
            log.warning("call notice failed", extra={"error": type(exc).__name__})

    # ---- caps, silence and the clock -----------------------------------------------------------
    async def _ticker(self) -> None:
        while not self.state.terminal and self.state is not CallState.WRAPPING_UP:
            await asyncio.sleep(self.d.timing.tick_s)
            await self.tick()

    async def tick(self) -> None:
        """Once a second: the caps, a long silence, and the listeners' clock."""
        if self.state.terminal or self._ending:
            return
        await self._check_caps()
        if self._ending:
            return
        quiet = clock_time.monotonic() - self._last_activity
        if (
            self.state is CallState.TALKING
            and not self._busy()
            and quiet >= self.d.timing.silence_s
        ):
            if self._still_asked:
                await self._say_line(LineKind.GOODBYE)
                await self.end(EndReason.DONE, say_goodbye=False)
                return
            await self._say_line(LineKind.STILL_THERE)
            self._still_asked = True
        self._push_state()

    async def _check_caps(self) -> None:
        if self._ending or self.answered_at is None:
            return
        if self.seconds() >= self._max_seconds() - self.d.timing.cap_grace_s:
            await self.cap(EndReason.CAP_MINUTES)
        elif self.total_inr >= self._max_inr() or self._month_reached():
            await self.cap(EndReason.CAP_INR)

    def _month_reached(self) -> bool:
        return self._month_spent + self.total_inr >= self.settings.month_cap_inr

    async def cap(self, reason: EndReason) -> None:
        """A cap was reached: the goodbye line, then the end."""
        if self._ending or self._closed:
            return
        self._ending = True
        self._gen += 1
        await self._audit("cap", detail=reason.value)
        await self._hush()
        if not self.taken_over:
            await self._say_line(LineKind.GOODBYE_CAP)
        outcome = "cap_minutes" if reason is EndReason.CAP_MINUTES else "cap_rupees"
        await self.end(reason, outcome=outcome, say_goodbye=False)

    # ---- the end -------------------------------------------------------------------------------
    async def end(
        self,
        reason: EndReason,
        *,
        outcome: str | None = None,
        say_goodbye: bool = True,
        phone_ended: bool = False,
    ) -> None:
        if self._closed or self.state.terminal:
            return
        self._closed = True
        self._ending = True
        self._gen += 1
        if self._phone is not None and not self._phone.done():
            self._phone.set_result("closed")  # a dial still ringing stops waiting
        await self._hush()
        connected = self.answered_at is not None
        polite = say_goodbye and connected and not phone_ended and not self.taken_over
        if polite and not self._said_goodbye:
            await self._say_line(LineKind.GOODBYE)
        if not phone_ended:
            await self._send_phone(CallEnd(call_id=self.call_id))
        await self._send_desk(Release(call_id=self.call_id))
        await self._finish(reason, outcome=outcome)

    def _outcome(self, reason: EndReason, given: str | None) -> str:
        if given:
            return given
        if self.taken_over and reason in (EndReason.HUNG_UP, EndReason.OWNER_HANGUP):
            return "taken_over"
        if reason is EndReason.HUNG_UP:
            return "they_hung_up"
        if reason is EndReason.DONE:
            return "message_taken" if self.card is None else "completed"
        return {
            EndReason.OWNER_HANGUP: "hung_up",
            EndReason.CAP_INR: "cap_rupees",
            EndReason.CAP_MINUTES: "cap_minutes",
            EndReason.NO_ANSWER: "no_answer",
            EndReason.NOT_READY: "desk_not_ready",
            EndReason.DESK_LOST: "desk_dropped",
            EndReason.PHONE_LOST: "phone_dropped",
        }.get(reason, "failed")

    async def _finish(
        self, reason: EndReason, *, outcome: str | None = None, note: str = ""
    ) -> None:
        """Summary, record, ₹, the vault and the owner's note; then the listeners close."""
        self._ending = self._closed = True
        self.end_reason = reason
        self.outcome = self._outcome(reason, outcome)
        if note:
            self.notes = [*self.notes, one_line(note, 300)][-NOTES_MAX:]
        self._set_state(CallState.WRAPPING_UP)
        self._flush_recording()
        booked = self.booked.words() if self.booked else None
        connected = self.answered_at is not None
        if connected and self.lines:
            result = await self.d.summarizer.summarize(
                self.brief, self.lines, outcome=self.outcome, booking=booked, notes=self.notes
            )
            summary = result.summary
            await self._meter_model("summary", result.completion)
        else:  # nothing was said: the summary is built in code, no model call
            summary = fallback_summary(
                self.brief, outcome=self.outcome, booking=booked, notes=self.notes
            )
        final = _final_state(reason, connected=connected)
        record = self.record.model_copy(
            update={
                "state": final,
                "end_reason": reason,
                "languages_used": tuple(c for c in self.used if is_language(c)),
                "answered_at": self.answered_at,
                "ended_at": self.d.clock(),
                "seconds": self.seconds(),
                "cost_inr": self.total_inr,
                "cost_parts": dict(self.cost),
                "recorded": self.recording and not self.objected,
                "objected": self.objected,
            }
        )
        await self._close_out(record, summary)
        self.state = final
        self._push_state()
        self.room.close_all(1000)
        await self._audit("end", final.value, reason.value)
        self.done.set()

    async def _close_out(self, record: CallRecord, summary: CallSummary) -> None:
        try:
            record = await self.d.records.finish(
                self.uid,
                record,
                card=self.card,
                summary=summary,
                lines=self.lines,
                booked=self.booked,
            )
        except Exception as exc:  # noqa: BLE001 - the record below still keeps the call
            log.error("call records not finished", extra={"error": type(exc).__name__})
        self.record = record
        try:
            await self.d.store.put_record(self.uid, record)
            month = (record.ended_at or self.d.clock()).astimezone(ZoneInfo(QUIET_ZONE))
            if record.cost_inr > 0:
                await self.d.store.add_spend(self.uid, month.strftime("%Y-%m"), record.cost_inr)
        except Exception as exc:  # noqa: BLE001
            log.error("call record not saved", extra={"error": type(exc).__name__})
        words = summary.text
        if self.outcome == "desk_not_ready" and self.notes:
            words = f"{words} {self.notes[-1]}"
        await self._notice(one_line(words, 400))


def _final_state(reason: EndReason, *, connected: bool) -> CallState:
    if reason is EndReason.NO_ANSWER:
        return CallState.NO_ANSWER
    if not connected:
        return CallState.FAILED
    return CallState.ENDED


def _parse_slot(slot: Slot | None) -> tuple[date, time, time | None] | None:
    if slot is None:
        return None
    try:
        day = date.fromisoformat(slot.date)
        start = time.fromisoformat(slot.start)
        end = time.fromisoformat(slot.end) if slot.end else None
    except ValueError:
        return None
    if end is not None and end <= start:
        return None
    return day, start, end


def _log_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("call task failed", extra={"error": type(exc).__name__})


__all__ = [
    "MAX_BRAIN_FAILURES",
    "SWITCH_CONFIDENCE",
    "TAP_PHONE",
    "BookedSlot",
    "CallSession",
    "DialGate",
    "EngineDeps",
    "OwnerNotice",
    "RecordsSink",
    "SlotCheck",
    "Spend",
    "SpeechKit",
    "Timing",
    "brief_for",
    "card_texts",
]
