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

A turn (hearing, the brain, the guard, the actions) is `engine_turns.Turns`; the voice is
`engine_voice.CallVoice`; the seams are `engine_ports`. Caps: the call's minutes and ₹ and the
month's calls ₹; at a cap JARVIS says the goodbye line and ends. Every ₹ is added to the record's
`cost_parts`. Nothing here logs or audits audio, transcripts or numbers.
"""

from __future__ import annotations

import asyncio
import contextlib
import time as clock_time
from collections.abc import Awaitable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.calls.brain import (
    Line,
    LineKind,
)
from jarvis.calls.engine_ports import (
    BookedSlot,
    EngineDeps,
    Kind,
    brief_for,
    card_texts,
    desk_problems,
)
from jarvis.calls.engine_turns import (
    MAX_BRAIN_FAILURES,
    MAX_UTTERANCE_S,
    NOTES_MAX,
    SAMPLE_SECONDS,
    SWITCH_CONFIDENCE,
    Turns,
)
from jarvis.calls.engine_voice import CallVoice
from jarvis.calls.guard import (
    GuardContext,
    card_values,
    heard_values,
)
from jarvis.calls.live import FRAME_S, LiveListener, LiveRoom, Mixer
from jarvis.calls.models import (
    ENGLISH,
    QUIET_ZONE,
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
    LiveCaption,
    LiveState,
    PhoneCommand,
    Prepare,
    Release,
    StopSpeaking,
    split_frames,
)
from jarvis.calls.summary import CallSummary, fallback_summary, final_state, outcome_for
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import Completion
from jarvis.logging import get_logger
from jarvis.tools.card import one_line

log = get_logger(__name__)

OWNER_LINES_MAX = 10
MIXER_BACKLOG_FRAMES = 100  # 2 s: one desk message carries up to 1 s
RECORD_CHUNK_FRAMES = 50  # one second of mixed audio per write to the records sink
TAP_PHONE = (
    "JARVIS handed the call to you. If the sound stays on the laptop, tap Phone on your phone's "
    "call screen."
)


class CallSession(Turns):
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
        self._dtmf_done: asyncio.Event = asyncio.Event()
        self._prepared = asyncio.Event()
        self._phone: asyncio.Future[str] | None = None
        self._told = asyncio.Event()
        self._gen = 0
        self._reply_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._ending = False  # no new work: a goodbye or the end is under way
        self._closed = False  # `end` / `_finish` has started (once)
        self._month_spent = 0.0
        self._said_goodbye = False
        self._failures = 0
        self._unsupported_count = 0
        self._slot_retry = False
        self._still_asked = False
        self._last_activity = clock_time.monotonic()
        self._rec_buf = bytearray()
        self._desk_lost_at: float | None = None
        self.voice = CallVoice(
            call_id=record.id,
            mode=record.speech_mode,
            speech=deps.speech,
            timing=deps.timing,
            mixer=self.mixer,
            send_desk=self._send_desk,
            send_audio=self._send_audio,
            meter=self._meter_voice,
            cut=lambda: self._desk_lost_at is not None or self.state.terminal,
        )

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
        problems = desk_problems(self.d.desk.state(), connected=self.d.desk.is_ready())
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
            if self.voice.speaking:
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
        self.voice.on_played(utterance_id)

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
        self.voice.interrupt()
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
        self.voice.interrupt()
        self._spawn(self._send_desk(StopSpeaking(call_id=self.call_id)))

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
        return running or self.voice.speaking or self._them_speaking

    # ---- speaking ------------------------------------------------------------------------------
    async def _hush(self) -> None:
        if self.voice.speaking:
            self._barge_in()
        await self.voice.hush()

    async def _speak(self, text: str, lang: str, *, english: str, required: bool = True) -> None:
        """Say one line (already guarded, or a fixed line) and keep it in the transcript."""

        async def announce() -> None:
            line = Line(who="jarvis", lang=lang, text=text, english=english)
            self.lines.append(line)
            self.room.send(self._caption_msg(line))
            await self.d.records.line(self.uid, self.call_id, line)

        ok = await self.voice.say(text, lang, announce=announce)
        self._touch()
        if not ok and required and not self._closed:
            self._spawn(self.end(EndReason.ERROR, outcome="failed", say_goodbye=False))

    async def _meter_voice(self, option: str, chars: int) -> None:
        await self._meter_speech(option, "voice", chars)

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

    async def _finish(
        self, reason: EndReason, *, outcome: str | None = None, note: str = ""
    ) -> None:
        """Summary, record, ₹, the vault and the owner's note; then the listeners close."""
        self._ending = self._closed = True
        self.end_reason = reason
        self.outcome = outcome or outcome_for(
            reason, taken_over=self.taken_over, answering=self.card is None
        )
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
        final = final_state(reason, connected=connected)
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
    "CallSession",
]
