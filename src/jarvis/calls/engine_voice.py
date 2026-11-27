# src/jarvis/calls/engine_voice.py
"""JARVIS's voice in one call (R18 A2; docs/plans/r18-calls.md 4.4 and 4.7; Layer 8).

One line at a time (a lock), in the call's speech mode:
- cloud: the language's `Voice` makes the PCM, which goes to the desk as 0x02 audio a few frames a
  message, at most `Timing.lead_s` ahead of real time, and into the mixer for live listeners;
- laptop: `say_text` to the desk, which speaks it itself; done at its `played` (or the timeout).
`interrupt()` (the other person barged in, a takeover, a cap, the end) stops the line at the next
chunk; `hush()` waits until JARVIS is quiet. Every line is metered by its characters through the
session's callback. A line the voice can't make returns False: the session decides (a required
line ends the call; an optional one, such as the Hindi half of the unsupported-language line, is
skipped). Nothing here logs the text or the audio.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

from jarvis.calls.engine_ports import SpeechKit, Timing
from jarvis.calls.live import FRAME_S, Mixer
from jarvis.calls.models import SpeechMode
from jarvis.calls.protocol import CloudToDesk, SayText, split_frames
from jarvis.logging import get_logger

log = get_logger(__name__)

FRAMES_PER_MESSAGE = 5  # 100 ms of audio a desk message
SendDesk = Callable[[CloudToDesk], Awaitable[bool]]
SendAudio = Callable[[bytes], Awaitable[bool]]
MeterVoice = Callable[[str, int], Awaitable[None]]  # (option, characters)


class CallVoice:
    def __init__(
        self,
        *,
        call_id: str,
        mode: SpeechMode,
        speech: SpeechKit,
        timing: Timing,
        mixer: Mixer,
        send_desk: SendDesk,
        send_audio: SendAudio,
        meter: MeterVoice,
        cut: Callable[[], bool],
    ) -> None:
        self._call_id = call_id
        self._mode = mode
        self._speech = speech
        self._timing = timing
        self._mixer = mixer
        self._send_desk = send_desk
        self._send_audio = send_audio
        self._meter = meter
        self._cut = cut  # True: the desk is gone or the call is over: say nothing
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._quiet = asyncio.Event()
        self._quiet.set()
        self._played: dict[str, asyncio.Event] = {}
        self._seq = 0
        self.speaking = False

    def interrupt(self) -> bool:
        """Stop the line being spoken. True when one was."""
        self._stop.set()
        return self.speaking

    def on_played(self, utterance_id: str) -> None:
        ev = self._played.get(utterance_id)
        if ev is not None:
            ev.set()

    async def hush(self) -> None:
        """Stop the line being spoken (if any) and wait until JARVIS is quiet."""
        if self.speaking:
            self._stop.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._quiet.wait(), self._timing.laptop_say_s)

    async def say(
        self, text: str, lang: str, *, announce: Callable[[], Awaitable[None]] | None = None
    ) -> bool:
        """Say one line; `announce` runs first, under the same lock (the transcript keeps the
        lines in the order they are spoken). False when the voice could not make it."""
        async with self._lock:
            if self._cut():
                return True
            if announce is not None:
                await announce()
            self._stop.clear()
            self.speaking = True
            self._quiet.clear()
            try:
                if self._mode is SpeechMode.LAPTOP:
                    await self._on_laptop(text, lang)
                    return True
                return await self._in_cloud(text, lang)
            finally:
                self.speaking = False
                self._quiet.set()

    async def _wait(self, other: asyncio.Event | None, timeout: float) -> None:
        """Until `other` is set, the line is interrupted, or `timeout`."""
        waits = {asyncio.ensure_future(self._stop.wait())}
        if other is not None:
            waits.add(asyncio.ensure_future(other.wait()))
        try:
            await asyncio.wait(waits, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waits:
                w.cancel()

    async def _on_laptop(self, text: str, lang: str) -> None:
        self._seq += 1
        utt = f"u{self._seq}"
        played = asyncio.Event()
        self._played[utt] = played
        try:
            msg = SayText(call_id=self._call_id, utterance_id=utt, lang=lang, text=text[:2000])
            if await self._send_desk(msg):
                await self._wait(played, self._timing.laptop_say_s)
        finally:
            self._played.pop(utt, None)

    async def _in_cloud(self, text: str, lang: str) -> bool:
        try:
            voice = self._speech.voice(lang)
            pcm = await voice.speak(text, lang)
            frames = split_frames(pcm) if pcm else []
        except Exception as exc:  # noqa: BLE001 - the session decides what a failed line means
            log.error("call voice failed", extra={"error": type(exc).__name__})
            return False
        await self._meter(voice.name, len(text))
        if not self._stop.is_set():
            await self._paced(frames)
        return True

    async def _paced(self, frames: list[bytes]) -> None:
        timing = self._timing
        start = time.monotonic()
        for i in range(0, len(frames), FRAMES_PER_MESSAGE):
            if self._stop.is_set() or self._cut():
                return
            chunk = frames[i : i + FRAMES_PER_MESSAGE]
            if not await self._send_audio(b"".join(chunk)):
                return
            for frame in chunk:
                self._mixer.jarvis(frame)
            if timing.pace:
                ahead = start + (i + len(chunk)) * FRAME_S - timing.lead_s - time.monotonic()
                if ahead > 0:
                    await self._wait(None, ahead)
        if timing.pace and not self._stop.is_set():
            await self._wait(None, timing.lead_s)


__all__ = ["FRAMES_PER_MESSAGE", "CallVoice"]
