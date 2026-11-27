# src/jarvis/calldesk/sound.py
"""The call's audio while a JARVIS call is on (R18 C): two worker threads around the blocking
devices of `ports.SoundDevices`, handing results to the event loop.

- Hearing: a thread reads 20 ms frames of the loopback recording and passes each to `on_frame`
  on the event loop (a stalled loop drops frames rather than growing a queue).
- Speaking: a thread plays queued PCM into CABLE Input, one 20 ms frame at a time, so `cut()`
  (stop_speaking, barge-in) silences JARVIS within a frame: everything queued is dropped and the
  frame being written is the last. A marker queued after an utterance fires `on_marker` once
  everything before it has been played (that is the `played` message); a cut drops its markers.

Errors from a device end that thread and reach `on_error` with plain words (never audio).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.calldesk.audio import FRAME_BYTES, Framer
from jarvis.calldesk.ports import AudioDeviceError, Capture, Player, SoundDevices

log = logging.getLogger(__name__)

MAX_QUEUED_FRAMES = 50 * 120  # two minutes of JARVIS's voice
_WAIT_S = 0.1


@dataclass(frozen=True)
class _Marker:
    token: str


def _post(loop: asyncio.AbstractEventLoop, fn: Callable[..., None], *args: object) -> None:
    try:
        loop.call_soon_threadsafe(fn, *args)
    except RuntimeError:  # the loop is closed: the desk is stopping
        pass


class Hearing:
    """The loopback recording thread."""

    def __init__(
        self,
        devices: SoundDevices,
        loop: asyncio.AbstractEventLoop,
        on_frame: Callable[[bytes], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._devices = devices
        self._loop = loop
        self._on_frame = on_frame
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="calldesk-hearing", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    def _run(self) -> None:
        capture: Capture | None = None
        try:
            capture = self._devices.open_loopback()
            while not self._stop.is_set():
                frame = capture.read()
                if len(frame) != FRAME_BYTES:
                    raise AudioDeviceError("the speaker recording gave a broken frame")
                if not self._stop.is_set():
                    _post(self._loop, self._on_frame, frame)
        except AudioDeviceError as exc:
            log.warning("the speaker recording stopped")
            _post(self._loop, self._on_error, str(exc))
        finally:
            if capture is not None:
                _close(capture)


class Speaking:
    """The CABLE Input playback thread."""

    def __init__(
        self,
        devices: SoundDevices,
        loop: asyncio.AbstractEventLoop,
        on_marker: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._devices = devices
        self._loop = loop
        self._on_marker = on_marker
        self._on_error = on_error
        self._items: deque[bytes | _Marker] = deque()
        self._frames = 0
        self._cond = threading.Condition()
        self._stop = False
        self._writing = False
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def busy(self) -> bool:
        """JARVIS is talking (or about to): the voice detector's barge-in onset applies."""
        with self._cond:
            return self._writing or self._frames > 0

    def start(self) -> None:
        if self.running:
            return
        with self._cond:
            self._stop = False
        self._thread = threading.Thread(target=self._run, name="calldesk-speaking", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        with self._cond:
            self._stop = True
            self._items.clear()
            self._frames = 0
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    def play(self, pcm: bytes) -> bool:
        """Queue PCM (any length); False when the queue is full (the audio is dropped)."""
        framer = Framer()
        frames = framer.push(pcm[: len(pcm) - len(pcm) % 2])
        tail = framer.flush()
        if tail:
            frames.append(tail)
        with self._cond:
            if self._frames + len(frames) > MAX_QUEUED_FRAMES:
                return False
            self._items.extend(frames)
            self._frames += len(frames)
            self._cond.notify_all()
        return True

    def mark(self, token: str) -> None:
        with self._cond:
            self._items.append(_Marker(token))
            self._cond.notify_all()

    def cut(self) -> bool:
        """Drop everything queued (and its markers). True when JARVIS was talking."""
        with self._cond:
            was = self._writing or self._frames > 0
            self._items.clear()
            self._frames = 0
            return was

    def _next(self) -> bytes | _Marker | None:
        with self._cond:
            while not self._items and not self._stop:
                self._writing = False
                self._cond.wait(_WAIT_S)
            if self._stop:
                self._writing = False
                return None
            item = self._items.popleft()
            if isinstance(item, bytes):
                self._frames -= 1
                self._writing = True
            return item

    def _run(self) -> None:
        player: Player | None = None
        try:
            player = self._devices.open_cable_player()
            while True:
                item = self._next()
                if item is None:
                    return
                if isinstance(item, _Marker):
                    _post(self._loop, self._on_marker, item.token)
                    continue
                player.write(item)
        except AudioDeviceError as exc:
            log.warning("playback into CABLE Input stopped")
            _post(self._loop, self._on_error, str(exc))
        finally:
            with self._cond:
                self._writing = False
            if player is not None:
                _close(player)


def _close(device: Capture | Player) -> None:
    try:
        device.close()
    except AudioDeviceError:
        log.warning("a sound device did not close cleanly")


class CallAudio:
    """Hearing and speaking together, for one call (what the desk session drives)."""

    def __init__(self, devices: SoundDevices, loop: asyncio.AbstractEventLoop) -> None:
        self._devices = devices
        self._loop = loop
        self._hearing: Hearing | None = None
        self._speaking: Speaking | None = None

    def start(
        self,
        on_frame: Callable[[bytes], None],
        on_marker: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self.stop()
        self._hearing = Hearing(self._devices, self._loop, on_frame, on_error)
        self._speaking = Speaking(self._devices, self._loop, on_marker, on_error)
        self._speaking.start()
        self._hearing.start()

    def stop(self) -> None:
        if self._speaking is not None:
            self._speaking.stop()
        if self._hearing is not None:
            self._hearing.stop()
        self._hearing = self._speaking = None

    def stop_speaking(self) -> None:
        """Takeover: JARVIS goes quiet for good; the recording runs on."""
        if self._speaking is not None:
            self._speaking.stop()
        self._speaking = None

    def play(self, pcm: bytes) -> bool:
        return self._speaking.play(pcm) if self._speaking is not None else False

    def mark(self, token: str) -> None:
        if self._speaking is not None:
            self._speaking.mark(token)

    def cut(self) -> bool:
        return self._speaking.cut() if self._speaking is not None else False

    @property
    def busy(self) -> bool:
        return self._speaking.busy if self._speaking is not None else False


__all__ = ["MAX_QUEUED_FRAMES", "CallAudio", "Hearing", "Speaking"]
