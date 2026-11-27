# src/jarvis/calls/engine_turns.py
"""One turn of a call (R18 A2; docs/plans/r18-calls.md 4.4-4.6, 4.9-4.10, 8): the part of
`CallSession` that hears the other person and answers. Split from `engine.py` for size; it is a
base class of `CallSession` and reads and writes the session's own state (declared below).

Hearing: the utterance (sent only while they speak) -> per-utterance language detection among
the call's languages plus a few common ones (a confident other language switches from the next
sentence; a language the call does not allow gets the English and Hindi line and, the second
time, the end) -> the language's hearing -> the line, its English caption (cheapest path) and the
records. The brain's turn: one reply at a time; words that arrive while it thinks make it think
again (the stale reply is metered, never spoken); the action is carried out in code: `say`
through the guard (a refusal says the check-back line), `book_slot` only inside the card's
windows (one retry with a note, then check back), `dtmf` keys through the same digit rule (never
on a missed call JARVIS answered), `ask_owner` holds and waits for his Tell JARVIS, `end` says
goodbye and ends; `recording_objection` stops and deletes the recording.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable
from datetime import date, time
from typing import TYPE_CHECKING, Any

from jarvis.calls.brain import BrainReply, CallBrief, FixedLines, Line, LineKind, Slot
from jarvis.calls.captions import is_english
from jarvis.calls.engine_ports import BookedSlot, EngineDeps, Kind
from jarvis.calls.engine_voice import CallVoice
from jarvis.calls.guard import GuardContext, check_dtmf, check_reply
from jarvis.calls.live import LiveRoom
from jarvis.calls.models import (
    ENGLISH,
    CallCard,
    CallRecord,
    CallSettings,
    CallState,
    EndReason,
    SpeechMode,
    is_language,
)
from jarvis.calls.protocol import Dtmf
from jarvis.llm.base import Completion, LLMError
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger
from jarvis.tools.card import one_line

log = get_logger(__name__)

SWITCH_CONFIDENCE = 0.7  # a language switch needs at least this detector confidence
MIN_UTTERANCE_S = 0.3
MAX_UTTERANCE_S = 30.0
MAX_BRAIN_FAILURES = 2
MAX_UNSUPPORTED = 2
NOTES_MAX = 20
SAMPLE_SECONDS = 1 / 32_000  # one byte of 16 kHz PCM16
DETECT_EXTRA = ("en-IN", "hi-IN", "ml-IN", "ta-IN", "te-IN", "kn-IN", "bn-IN", "mr-IN", "gu-IN")
OBJECTION = re.compile(
    r"\b(?:do not|don't|dont|stop|no)\s+(?:record|recording)\b|\bnot\s+be\s+recorded\b|"
    r"\bwithout\s+recording\b|\bturn\s+off\s+(?:the\s+)?recording\b",
    re.IGNORECASE,
)


class Turns:
    """Hearing and the brain's turn; `CallSession` supplies the state and the helpers."""

    # the session's state this part reads and writes
    d: EngineDeps
    uid: str
    record: CallRecord
    card: CallCard | None
    settings: CallSettings
    brief: CallBrief
    allowed: tuple[str, ...]
    lang: str
    used: list[str]
    state: CallState
    room: LiveRoom
    voice: CallVoice
    lines: list[Line]
    owner_lines: list[str]
    notes: list[str]
    recording: bool
    objected: bool
    taken_over: bool
    booked: BookedSlot | None
    _heard: list[str]
    _utter: bytearray
    _rec_buf: bytearray
    _gen: int
    _reply_task: asyncio.Task[None] | None
    _ending: bool
    _closed: bool
    _failures: int
    _unsupported_count: int
    _slot_retry: bool
    _told: asyncio.Event
    _dtmf_done: asyncio.Event
    _said_goodbye: bool
    _audio_writes: set[asyncio.Task[Any]]

    if TYPE_CHECKING:  # the session's helpers this part calls

        @property
        def call_id(self) -> str: ...

        def seconds(self) -> int: ...

        def _max_seconds(self) -> int: ...

        def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]: ...

        def _guard(self) -> GuardContext: ...

        def _push_state(self) -> None: ...

        def _caption_msg(self, line: Line) -> dict[str, Any]: ...

        def _busy(self) -> bool: ...

        async def _audit(self, step: str, outcome: str = "ok", detail: str = "") -> None: ...

        async def _meter_model(self, part: str, completion: Completion | None) -> None: ...

        async def _meter_speech(self, option: str, kind: Kind, units: float) -> None: ...

        async def _send_desk(self, msg: Dtmf) -> bool: ...

        async def _notice(self, text: str) -> None: ...

        async def _speak(
            self, text: str, lang: str, *, english: str, required: bool = True
        ) -> None: ...

        async def cap(self, reason: EndReason) -> None: ...

        async def end(
            self,
            reason: EndReason,
            *,
            outcome: str | None = None,
            say_goodbye: bool = True,
            phone_ended: bool = False,
        ) -> None: ...

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

    def _close_utterance(self) -> None:
        if self.record.speech_mode is not SpeechMode.CLOUD:
            return
        pcm, self._utter = bytes(self._utter), bytearray()
        if len(pcm) * SAMPLE_SECONDS < MIN_UTTERANCE_S:
            return
        self._spawn(self._hear(pcm))

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
        if lang not in self.allowed and conf >= SWITCH_CONFIDENCE and not self.taken_over:
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
        if lang != self.lang and confidence >= SWITCH_CONFIDENCE and not self.taken_over:
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
        if english and OBJECTION.search(english):
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
            if line.who == "them" and OBJECTION.search(line.english):
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
        if self._audio_writes:  # a chunk on its way lands before the delete, never after it
            await asyncio.gather(*list(self._audio_writes), return_exceptions=True)
        await self._audit("objection")
        try:
            await self.d.records.objection(self.uid, self.call_id)
        except Exception as exc:  # noqa: BLE001 - said; retried by the retention job's delete
            log.error("recording not deleted", extra={"error": type(exc).__name__})
        self._push_state()


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


__all__ = [
    "MAX_BRAIN_FAILURES",
    "NOTES_MAX",
    "MAX_UTTERANCE_S",
    "OBJECTION",
    "SAMPLE_SECONDS",
    "SWITCH_CONFIDENCE",
    "Turns",
]
