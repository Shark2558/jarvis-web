# src/jarvis/calls/live.py
"""Live listeners of a call (R18 A2; docs/plans/r18-calls.md 4.7; Layers 1 and 8).

A listener is one owner's browser (the console's Calls panel, or the console page in the phone's
browser) on `GET /api/calls/{call_id}/live`. It gets, from the server:
- JSON text messages: `caption {who, lang, text, english}` and `state {...}`. These always arrive,
  in order. A listener more than `TEXT_BACKLOG` messages behind is too slow and is closed
  (`WS_TOO_SLOW`); it can reconnect and read the transcript afterwards.
- binary frames `0x03` + 640 bytes (20 ms of 16 kHz mono PCM16, both sides mixed), only after it
  asked for audio (`listen {audio: true}`; "Captions only" is the default). Audio is droppable: a
  slow listener loses its oldest frames (`AUDIO_BACKLOG_FRAMES`, 500 ms), never the call.
Every send has a timeout: a socket that stalls is closed. Each listener has its own sender task
(`LiveListener.run`), so one slow phone never holds up the call or another listener.

The `Mixer` sums the other person's frames (0x01, from the desk) and JARVIS's frames (0x02, as
they are paced out to the desk) into one stream, one frame from each side per 20 ms tick, with
saturation. Nothing here logs audio or text.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from array import array
from collections import deque
from collections.abc import Mapping
from typing import Any, Protocol

from jarvis.logging import get_logger

log = get_logger(__name__)

FRAME_BYTES = 640  # 20 ms of 16 kHz mono signed 16-bit PCM
FRAME_S = 0.020
LIVE_AUDIO = 0x03  # the prefix of a mixed live-audio frame (cloud -> listener)
AUDIO_BACKLOG_FRAMES = 25  # 500 ms
TEXT_BACKLOG = 200
SEND_TIMEOUT_S = 5.0
WS_TOO_SLOW = 1013  # "try again later"
_MIN, _MAX = -32768, 32767


class ListenerSink(Protocol):
    """The socket side of a listener (Starlette's WebSocket fits)."""

    async def send_text(self, data: str) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def close(self, code: int) -> None: ...


def _samples(frame: bytes) -> array[int]:
    if len(frame) != FRAME_BYTES:
        raise ValueError("a frame is 640 bytes")
    out = array("h")
    out.frombytes(frame)
    if sys.byteorder == "big":
        out.byteswap()
    return out


def mix(a: bytes, b: bytes) -> bytes:
    """Two 20 ms frames summed, clipped to 16 bits."""
    x, y = _samples(a), _samples(b)
    out = array("h", (max(_MIN, min(_MAX, p + q)) for p, q in zip(x, y, strict=True)))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


class Mixer:
    """Both sides of a call into one stream: one frame from each side per tick."""

    def __init__(self, backlog: int = AUDIO_BACKLOG_FRAMES) -> None:
        self._them: deque[bytes] = deque(maxlen=backlog)
        self._jarvis: deque[bytes] = deque(maxlen=backlog)
        self.dropped = 0

    def _put(self, side: deque[bytes], frame: bytes) -> None:
        if len(frame) != FRAME_BYTES:
            self.dropped += 1
            return
        if len(side) == side.maxlen:
            self.dropped += 1
        side.append(frame)

    def them(self, frame: bytes) -> None:
        self._put(self._them, frame)

    def jarvis(self, frame: bytes) -> None:
        self._put(self._jarvis, frame)

    def backlog(self) -> int:
        return max(len(self._them), len(self._jarvis))

    def tick(self) -> bytes | None:
        a = self._them.popleft() if self._them else None
        b = self._jarvis.popleft() if self._jarvis else None
        if a is not None and b is not None:
            return mix(a, b)
        return a if a is not None else b

    def clear(self) -> None:
        self._them.clear()
        self._jarvis.clear()


class LiveListener:
    def __init__(
        self,
        sink: ListenerSink,
        *,
        audio: bool = False,
        send_timeout_s: float = SEND_TIMEOUT_S,
    ) -> None:
        self._sink = sink
        self._audio_on = audio
        self._timeout = send_timeout_s
        self._text: deque[str] = deque()
        self._audio: deque[bytes] = deque(maxlen=AUDIO_BACKLOG_FRAMES)
        self._wake = asyncio.Event()
        self.closed = False
        self.close_code = 1000
        self.dropped_audio = 0
        self._broken = False  # a send failed: nothing more is sent

    @property
    def wants_audio(self) -> bool:
        return self._audio_on and not self.closed

    def set_audio(self, on: bool) -> None:
        self._audio_on = bool(on)
        if not on:
            self._audio.clear()

    def audio_backlog(self) -> int:
        return len(self._audio)

    def push_json(self, msg: Mapping[str, Any]) -> bool:
        """Queue one text message; False when the listener is (now) closed."""
        if self.closed:
            return False
        if len(self._text) >= TEXT_BACKLOG:
            log.info("live listener too slow; closed", extra={"backlog": len(self._text)})
            self.close(WS_TOO_SLOW)
            return False
        self._text.append(json.dumps(dict(msg), ensure_ascii=False, separators=(",", ":")))
        self._wake.set()
        return True

    def push_audio(self, frame: bytes) -> None:
        if not self.wants_audio:
            return
        if len(self._audio) == self._audio.maxlen:
            self.dropped_audio += 1
        self._audio.append(frame)
        self._wake.set()

    def close(self, code: int = 1000) -> None:
        if not self.closed:
            self.closed = True
            self.close_code = code
        self._wake.set()

    async def _send(self, text: str | None, frame: bytes | None) -> bool:
        try:
            if text is not None:
                await asyncio.wait_for(self._sink.send_text(text), self._timeout)
            elif frame is not None:
                payload = bytes([LIVE_AUDIO]) + frame
                await asyncio.wait_for(self._sink.send_bytes(payload), self._timeout)
        except TimeoutError:
            log.info("live listener stalled; closed")
            self._broken = True
            self.close(WS_TOO_SLOW)
            return False
        except Exception as exc:  # noqa: BLE001 - the socket went away
            log.info("live listener gone", extra={"error": type(exc).__name__})
            self._broken = True
            self.close(1000)
            return False
        return True

    async def run(self) -> None:
        """Send until closed, text before audio; then close the socket once. A normal close
        (the call ended) first sends the text still queued, such as the last state."""
        while not self.closed:
            if self._text:
                await self._send(self._text.popleft(), None)
            elif self._audio:
                await self._send(None, self._audio.popleft())
            else:
                self._wake.clear()
                await self._wake.wait()
        self._audio.clear()
        while self._text and self.close_code == 1000 and not self._broken:
            await self._send(self._text.popleft(), None)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._sink.close(self.close_code), self._timeout)


class LiveRoom:
    """Every listener of one call."""

    def __init__(self) -> None:
        self._listeners: list[LiveListener] = []

    def _open(self) -> list[LiveListener]:
        self._listeners = [x for x in self._listeners if not x.closed]
        return self._listeners

    def __len__(self) -> int:
        return len(self._open())

    def add(self, listener: LiveListener) -> None:
        self._open().append(listener)

    def remove(self, listener: LiveListener) -> None:
        self._listeners = [x for x in self._listeners if x is not listener]

    def send(self, msg: Mapping[str, Any]) -> None:
        for listener in list(self._open()):
            listener.push_json(msg)

    def audio(self, frame: bytes) -> None:
        for listener in self._open():
            listener.push_audio(frame)

    def wants_audio(self) -> bool:
        return any(x.wants_audio for x in self._open())

    def close_all(self, code: int = 1000) -> None:
        for listener in self._open():
            listener.close(code)
        self._listeners = []


__all__ = [
    "AUDIO_BACKLOG_FRAMES",
    "FRAME_BYTES",
    "FRAME_S",
    "LIVE_AUDIO",
    "SEND_TIMEOUT_S",
    "TEXT_BACKLOG",
    "WS_TOO_SLOW",
    "ListenerSink",
    "LiveListener",
    "LiveRoom",
    "Mixer",
    "mix",
]
