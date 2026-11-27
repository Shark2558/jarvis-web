# src/jarvis/calldesk/audio.py
"""The audio format on the call desk's link (R18 build brief, "Audio format everywhere").

16 kHz, mono, signed 16-bit little-endian PCM in 20 ms frames (640 bytes). On the WebSocket each
binary message is one tag byte and then PCM: 0x01 the other person (desk -> cloud), 0x02 JARVIS's
voice (cloud -> desk), 0x03 mixed live audio (cloud -> listener; the desk never sends or takes it).
Standard library only: the desk's tests run on Linux and on Python 3.11 without NumPy.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable

RATE = 16_000
CHANNELS = 1
SAMPLE_BYTES = 2
FRAME_MS = 20
FRAME_SAMPLES = RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_BYTES  # 640
TAG_CALLER = 0x01
TAG_JARVIS = 0x02
TAG_LIVE = 0x03
TAGS = frozenset({TAG_CALLER, TAG_JARVIS, TAG_LIVE})
MAX_AUDIO_BYTES = 64 * 1024  # one binary message: 2 s of audio at most
_FULL_SCALE = 32767


class AudioFormatError(ValueError):
    """A binary message is not tagged PCM16 of an allowed size (no audio in the message)."""


def tag(kind: int, pcm: bytes) -> bytes:
    """One binary WebSocket message."""
    if kind not in TAGS:
        raise AudioFormatError("unknown audio tag")
    _check_pcm(pcm)
    return bytes((kind,)) + pcm


def untag(message: bytes) -> tuple[int, bytes]:
    """(tag, pcm) of one binary message, or AudioFormatError."""
    if not message:
        raise AudioFormatError("empty audio message")
    kind = message[0]
    if kind not in TAGS:
        raise AudioFormatError("unknown audio tag")
    pcm = bytes(message[1:])
    _check_pcm(pcm)
    return kind, pcm


def _check_pcm(pcm: bytes) -> None:
    if len(pcm) % SAMPLE_BYTES:
        raise AudioFormatError("audio is not 16-bit samples")
    if len(pcm) > MAX_AUDIO_BYTES:
        raise AudioFormatError("audio message too large")


def float_to_pcm16(samples: Iterable[float]) -> bytes:
    """Float samples in -1..1 (clipped) -> PCM16 little-endian."""
    values = [int(round(max(-1.0, min(1.0, s)) * _FULL_SCALE)) for s in samples]
    return struct.pack(f"<{len(values)}h", *values)


class Framer:
    """Cuts a stream of PCM chunks of any size into whole 20 ms frames."""

    def __init__(self) -> None:
        self._buf = bytearray()

    @property
    def pending(self) -> int:
        return len(self._buf)

    def push(self, pcm: bytes) -> list[bytes]:
        self._buf.extend(pcm)
        whole = len(self._buf) - len(self._buf) % FRAME_BYTES
        frames = [bytes(self._buf[i : i + FRAME_BYTES]) for i in range(0, whole, FRAME_BYTES)]
        del self._buf[:whole]
        return frames

    def flush(self) -> bytes:
        """The last partial frame padded with silence (b"" when nothing is left)."""
        if not self._buf:
            return b""
        frame = bytes(self._buf) + b"\x00" * (FRAME_BYTES - len(self._buf))
        self._buf.clear()
        return frame


def split_frames(pcm: bytes) -> list[bytes]:
    """All of `pcm` as whole frames, the last padded with silence."""
    framer = Framer()
    frames = framer.push(pcm)
    tail = framer.flush()
    return [*frames, tail] if tail else frames


__all__ = [
    "CHANNELS",
    "FRAME_BYTES",
    "FRAME_MS",
    "FRAME_SAMPLES",
    "MAX_AUDIO_BYTES",
    "RATE",
    "SAMPLE_BYTES",
    "TAGS",
    "TAG_CALLER",
    "TAG_JARVIS",
    "TAG_LIVE",
    "AudioFormatError",
    "Framer",
    "float_to_pcm16",
    "split_frames",
    "tag",
    "untag",
]
