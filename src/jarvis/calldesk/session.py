# src/jarvis/calldesk/session.py
"""The desk's side of one connection to JARVIS (R18 build brief, "Desk <-> cloud"): what it does
for each cloud message, and what it tells the cloud.

    prepare        checks (cable, Phone Link, no Bluetooth headset, audio path), then the cable
                   as the default microphone (read back), notification sounds off, recording and
                   playback on; `state`, then `mic {owner_mic: false}`; any failure: `state` with
                   its problems and an `error`, and his microphone stays his
    0x02 audio     JARVIS's voice into CABLE Input (dropped after a takeover)
    say_text       laptop speech mode only: spoken here, then `played`
    dtmf           the key's tone into the call, then `dtmf_done`
    stop_speaking  playback cut at once
    takeover       his microphone back (`mic {owner_mic: true}`), JARVIS silent, the recording on
    release        everything restored, `mic`, a fresh `state`
    ping           `state` (the cached light check)

While a call is on, every 20 ms frame of the loopback recording goes through the voice detector:
`vad {speaking}` at each start and end of the other person's turn and their frames as 0x01 audio
in between (laptop mode: their turn is transcribed here and sent as `heard_text`). If they start
speaking while JARVIS talks, playback is cut at once (barge-in) and the `vad` tells the cloud.

Safety nets: a link lost for more than 20 s during a call, or a call longer than the longest one
the owner can allow (plus a margin), releases everything here without waiting for the cloud.
Nothing logged carries audio, text or a number.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from jarvis.calldesk import DESK_VERSION, dtmf
from jarvis.calldesk.audio import caller_messages
from jarvis.calldesk.checks import DeskCheck
from jarvis.calldesk.micguard import Outcome
from jarvis.calldesk.speech_local import LocalSpeech, LocalSpeechUnavailable, speech_modes
from jarvis.calldesk.vad import VoiceDetector
from jarvis.calls.models import CALL_MAX_MINUTES_CEILING, SpeechMode
from jarvis.calls.protocol import (
    TEXT_MAX,
    CloudToDesk,
    DeskError,
    DeskState,
    DeskTakeover,
    DeskToCloud,
    Dtmf,
    DtmfDone,
    HeardText,
    Hello,
    Mic,
    Ping,
    Played,
    Prepare,
    Release,
    SayText,
    StopSpeaking,
    Vad,
)

log = logging.getLogger(__name__)

T = TypeVar("T")
DISCONNECT_GRACE_S = 20.0
MAX_CALL_S = (CALL_MAX_MINUTES_CEILING + 5) * 60.0
MAX_TURN_BYTES = 30 * 16_000 * 2  # laptop mode: 30 s of their speech per turn at most
MAX_PROBLEMS = 10
PROBLEM_CHARS = 200

BUSY = "The call desk is already on another call."
NOT_READY = "The laptop is not ready for a call."
LAPTOP_SPEECH_OFF = "Laptop speech is not installed on this laptop; use cloud speech."
AUDIO_FAILED = "The laptop's sound stopped working during the call."
MIC_NOT_BACK = "Your microphone could not be switched back."
SPEECH_FAILED = "Laptop speech failed for this turn."
WRONG_MODE = "This call does not use laptop speech."


class Outbox(Protocol):
    def send(self, msg: DeskToCloud) -> None: ...

    def send_audio(self, message: bytes) -> None: ...


class Guard(Protocol):
    def switch_to_cable(self, call_id: str) -> Outcome: ...

    def restore(self, *, sounds: bool = True) -> Outcome: ...

    def mute_sounds(self) -> bool: ...


class Checks(Protocol):
    def run(self, *, probe_audio: bool = True) -> DeskCheck: ...


class Audio(Protocol):
    def start(
        self,
        on_frame: Callable[[bytes], None],
        on_marker: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None: ...

    def stop(self) -> None: ...

    def stop_speaking(self) -> None: ...

    def play(self, pcm: bytes) -> bool: ...

    def mark(self, token: str) -> None: ...

    def cut(self) -> bool: ...

    @property
    def busy(self) -> bool: ...


Blocking = Callable[..., Awaitable[Any]]


@dataclass
class _Call:
    call_id: str
    mode: SpeechMode
    languages: tuple[str, ...]
    vad: VoiceDetector = field(default_factory=VoiceDetector)
    owner: bool = False  # taken over: his microphone, JARVIS silent
    turn: bytearray = field(default_factory=bytearray)


def _trim(problems: Sequence[str]) -> tuple[str, ...]:
    return tuple(p[:PROBLEM_CHARS] for p in problems[:MAX_PROBLEMS])


class DeskSession:
    def __init__(
        self,
        outbox: Outbox,
        guard: Guard,
        checks: Checks,
        audio: Audio,
        local: LocalSpeech,
        *,
        blocking: Blocking = asyncio.to_thread,
        grace_s: float = DISCONNECT_GRACE_S,
        max_call_s: float = MAX_CALL_S,
    ) -> None:
        self._out = outbox
        self._guard = guard
        self._checks = checks
        self._audio = audio
        self._local = local
        self._blocking = blocking
        self._grace_s = grace_s
        self._max_call_s = max_call_s
        self._call: _Call | None = None
        self._last: DeskCheck | None = None
        self._markers: dict[str, DeskToCloud] = {}
        self._next_marker = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._grace: asyncio.Task[None] | None = None
        self._limit: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # ---- what the client calls -----------------------------------------------------------------

    @property
    def call_id(self) -> str | None:
        return self._call.call_id if self._call is not None else None

    async def connected(self) -> None:
        """A (re)connection: hello, a fresh state and, mid-call, where his microphone is."""
        self._cancel(self._grace)
        self._grace = None
        modes, languages = speech_modes(self._local)
        self._out.send(
            Hello.model_validate(
                {
                    "desk_version": DESK_VERSION,
                    "speech_modes": modes,
                    "local_languages": languages,
                }
            )
        )
        await self._send_state(probe=self._call is None)
        if self._call is not None:
            self._out.send(Mic(call_id=self._call.call_id, owner_mic=self._call.owner))

    def disconnected(self) -> None:
        if self._call is not None and self._grace is None:
            self._grace = self._spawn(self._grace_then_release(self._call.call_id))

    async def handle(self, msg: CloudToDesk) -> None:
        if isinstance(msg, Ping):
            await self._send_state(probe=False)
        elif isinstance(msg, Prepare):
            async with self._lock:
                await self._prepare(msg)
        elif isinstance(msg, Release):
            async with self._lock:
                await self._release(msg.call_id)
        elif isinstance(msg, DeskTakeover):
            async with self._lock:
                await self._takeover(msg.call_id)
        elif isinstance(msg, StopSpeaking):
            if self._is_current(msg.call_id):
                self._audio.cut()
        elif isinstance(msg, Dtmf):
            self._dtmf(msg)
        elif isinstance(msg, SayText):
            self._say_text(msg)

    def jarvis_audio(self, pcm: bytes) -> None:
        """A 0x02 message's PCM (whole frames, checked by the protocol)."""
        call = self._call
        if call is None or call.owner:
            return
        if not self._audio.play(pcm):
            log.warning("JARVIS's voice arrived faster than it plays; some was dropped")

    async def light_check(self) -> None:
        """Periodic: a state without the audio probe, sent only when something changed."""
        before = self._last
        check = await self._blocking(self._checks.run, probe_audio=False)
        self._last = check
        if check != before:
            self._out.send(self._state(check))

    async def shutdown(self) -> None:
        """The desk is stopping: everything restored, every timer off."""
        async with self._lock:
            if self._call is not None:
                await self._release(self._call.call_id)
            else:
                await self._blocking(self._guard.restore)
        for task in tuple(self._tasks):
            task.cancel()

    # ---- prepare / takeover / release ----------------------------------------------------------

    async def _prepare(self, msg: Prepare) -> None:
        if self._call is not None:
            if self._call.call_id == msg.call_id:  # asked again after a reconnect
                await self._send_state(probe=False)
                self._out.send(Mic(call_id=msg.call_id, owner_mic=self._call.owner))
                return
            self._error(msg.call_id, "desk_busy", BUSY)
            return
        if msg.mode is SpeechMode.LAPTOP and not self._local.status().installed:
            self._out.send(self._state(self._last, extra=(LAPTOP_SPEECH_OFF,), ready=False))
            self._error(msg.call_id, "laptop_speech_not_installed", LAPTOP_SPEECH_OFF)
            return
        check = await self._send_state(probe=True)
        if not check.ready:
            self._error(
                msg.call_id, "not_ready", check.problems[0] if check.problems else NOT_READY
            )
            return
        switched = await self._blocking(self._guard.switch_to_cable, msg.call_id)
        if not switched.ok:
            self._out.send(self._state(check, extra=switched.problems, ready=False))
            self._error(msg.call_id, "mic_switch_failed", (*switched.problems, NOT_READY)[0])
            return
        self._call = _Call(msg.call_id, msg.mode, tuple(msg.languages))  # release restores now
        try:
            await self._blocking(self._guard.mute_sounds)
            self._audio.start(self._on_frame, self._on_marker, self._on_audio_error)
        except Exception:  # noqa: BLE001 - any failure here: his microphone back first
            log.exception("the call's audio could not start")
            await self._release(msg.call_id, notify=False)
            self._out.send(self._state(check, extra=(AUDIO_FAILED,), ready=False))
            self._error(msg.call_id, "audio_failed", AUDIO_FAILED)
            return
        self._limit = self._spawn(self._limit_then_release(msg.call_id))
        log.info("call desk ready for a call")
        self._out.send(Mic(call_id=msg.call_id, owner_mic=False))

    async def _takeover(self, call_id: str) -> None:
        call = self._call
        if call is None or call.call_id != call_id:
            return
        if not call.owner:
            call.owner = True
            self._audio.cut()
            self._audio.stop_speaking()
            self._markers.clear()
        restored = await self._blocking(self._guard.restore, sounds=False)
        self._out.send(Mic(call_id=call_id, owner_mic=restored.ok))
        if not restored.ok:
            self._out.send(self._state(self._last, extra=restored.problems))
            self._error(call_id, "mic_restore_failed", MIC_NOT_BACK)

    async def _release(self, call_id: str, *, notify: bool = True) -> None:
        call = self._call
        if call is not None and call.call_id != call_id:
            return  # a late release for an older call: this one goes on
        self._call = None
        self._markers.clear()
        self._cancel(self._limit)
        self._limit = None
        self._audio.stop()
        restored = await self._blocking(self._guard.restore)
        if not notify:
            return
        self._out.send(Mic(call_id=call_id, owner_mic=restored.ok))
        if restored.ok:
            await self._send_state(probe=False)
        else:
            self._out.send(self._state(self._last, extra=restored.problems))
            self._error(call_id, "mic_restore_failed", MIC_NOT_BACK)

    # ---- in-call messages ----------------------------------------------------------------------

    def _is_current(self, call_id: str) -> bool:
        return self._call is not None and self._call.call_id == call_id

    def _speaking_allowed(self, call_id: str) -> bool:
        return self._call is not None and self._call.call_id == call_id and not self._call.owner

    def _dtmf(self, msg: Dtmf) -> None:
        if not self._speaking_allowed(msg.call_id):
            return
        self._audio.play(dtmf.tone(msg.digit))
        self._marker(DtmfDone(call_id=msg.call_id, digit=msg.digit))

    def _say_text(self, msg: SayText) -> None:
        call = self._call
        if call is None or call.call_id != msg.call_id or call.owner:
            return
        if call.mode is not SpeechMode.LAPTOP:
            self._error(msg.call_id, "wrong_mode", WRONG_MODE)
            return
        self._spawn(self._speak(msg))

    async def _speak(self, msg: SayText) -> None:
        try:
            pcm = await self._local.speak(msg.text, msg.lang)
        except LocalSpeechUnavailable:
            self._error(msg.call_id, "laptop_speech_failed", SPEECH_FAILED)
            return
        if self._speaking_allowed(msg.call_id):
            self._audio.play(pcm)
            self._marker(Played(call_id=msg.call_id, utterance_id=msg.utterance_id))

    def _marker(self, then: DeskToCloud) -> None:
        self._next_marker += 1
        token = f"m{self._next_marker}"
        self._markers[token] = then
        self._audio.mark(token)

    # ---- from the audio threads (on the event loop) --------------------------------------------

    def _on_marker(self, token: str) -> None:
        msg = self._markers.pop(token, None)
        if msg is not None:
            self._out.send(msg)

    def _on_audio_error(self, words: str) -> None:
        call = self._call
        if call is None:
            return
        log.warning("the call's audio failed")
        self._out.send(self._state(self._last, extra=(AUDIO_FAILED,), ready=False))
        self._error(call.call_id, "audio_failed", AUDIO_FAILED)

    def _on_frame(self, frame: bytes) -> None:
        call = self._call
        if call is None:
            return
        jarvis_talking = self._audio.busy and not call.owner
        step = call.vad.push(frame, jarvis_speaking=jarvis_talking)
        if step.started:
            if jarvis_talking and self._audio.cut():
                self._markers.clear()  # what was cut is not "played"
            self._out.send(Vad(call_id=call.call_id, speaking=True))
        if step.frames:
            self._heard(call, step.frames)
        if step.stopped:
            self._out.send(Vad(call_id=call.call_id, speaking=False))
            if call.mode is SpeechMode.LAPTOP:
                self._transcribe_turn(call)

    def _heard(self, call: _Call, frames: Sequence[bytes]) -> None:
        if call.mode is SpeechMode.LAPTOP:
            room = MAX_TURN_BYTES - len(call.turn)
            if room > 0:
                call.turn.extend(b"".join(frames)[:room])
            return
        for message in caller_messages(frames):
            self._out.send_audio(message)

    def _transcribe_turn(self, call: _Call) -> None:
        pcm = bytes(call.turn)
        call.turn.clear()
        if pcm:
            self._spawn(self._transcribe(call.call_id, pcm, call.languages))

    async def _transcribe(self, call_id: str, pcm: bytes, languages: Sequence[str]) -> None:
        try:
            heard = await self._local.transcribe(pcm, languages)
        except LocalSpeechUnavailable:
            self._error(call_id, "laptop_speech_failed", SPEECH_FAILED)
            return
        if self._is_current(call_id) and heard.text.strip():
            self._out.send(
                HeardText(
                    call_id=call_id,
                    lang=heard.lang,
                    text=heard.text[:TEXT_MAX],
                    confidence=max(0.0, min(1.0, heard.confidence)),
                )
            )

    # ---- state, errors, timers -----------------------------------------------------------------

    async def _send_state(self, *, probe: bool) -> DeskCheck:
        if probe or self._last is None:
            self._last = await self._blocking(self._checks.run, probe_audio=probe)
        check = self._last
        self._out.send(self._state(check))
        return check

    @staticmethod
    def _state(
        check: DeskCheck | None, *, extra: Sequence[str] = (), ready: bool | None = None
    ) -> DeskState:
        if check is None:
            return DeskState(
                ready=False, problems=_trim(extra), bt_headset=False, cable=False, phone_link=False
            )
        return DeskState(
            ready=check.ready if ready is None else ready,
            problems=_trim((*check.problems, *extra)),
            bt_headset=check.bt_headset,
            cable=check.cable,
            phone_link=check.phone_link,
        )

    def _error(self, call_id: str | None, code: str, words: str) -> None:
        self._out.send(DeskError(call_id=call_id, code=code, message=words[:PROBLEM_CHARS]))

    def _spawn(self, coro: Awaitable[None]) -> asyncio.Task[None]:
        task: asyncio.Task[None] = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    @staticmethod
    def _cancel(task: asyncio.Task[None] | None) -> None:
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    async def _grace_then_release(self, call_id: str) -> None:
        await asyncio.sleep(self._grace_s)
        log.warning("the link to JARVIS was lost during a call; restoring the laptop's audio")
        async with self._lock:
            await self._release(call_id, notify=False)
        self._grace = None

    async def _limit_then_release(self, call_id: str) -> None:
        await asyncio.sleep(self._max_call_s)
        log.warning("a call ran past the longest allowed; restoring the laptop's audio")
        async with self._lock:
            await self._release(call_id)

    async def settle(self) -> None:
        """Wait for the work spawned so far (speaking, transcribing), not the timers."""
        work = self._tasks - {self._grace, self._limit}
        if work:
            await asyncio.gather(*work, return_exceptions=True)


__all__ = ["DISCONNECT_GRACE_S", "MAX_CALL_S", "Audio", "Checks", "DeskSession", "Guard", "Outbox"]
