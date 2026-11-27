# src/jarvis/calldesk/audio.py
"""The call desk's view of the audio format (R18 build brief, "Audio format everywhere").

The format and the binary framing are `jarvis.calls.protocol`'s (16 kHz mono PCM16, 20 ms frames
of 640 bytes, one tag byte per message: 0x01 the other person, 0x02 JARVIS's voice); the kit ships
a copy of that file made at kit-build time, so there is no second definition here. What the desk
adds: a stream cutter for chunks of any size, batching of frames into messages, and float samples
to PCM16. Standard library only (the tests run on Python 3.11 without NumPy).
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence

from jarvis.calls.protocol import (
    FRAME_BYTES,
    MAX_FRAMES_PER_MESSAGE,
    SAMPLE_BYTES,
    SAMPLE_RATE,
    AudioKind,
    pack_audio,
)

RATE = SAMPLE_RATE
FRAME_SAMPLES = FRAME_BYTES // SAMPLE_BYTES  # 320
_FULL_SCALE = 32767


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


def caller_messages(frames: Sequence[bytes]) -> list[bytes]:
    """The other person's frames as 0x01 binary messages of at most one second each."""
    step = MAX_FRAMES_PER_MESSAGE
    return [
        pack_audio(AudioKind.THEM, b"".join(frames[i : i + step]))
        for i in range(0, len(frames), step)
    ]


__all__ = ["FRAME_BYTES", "FRAME_SAMPLES", "RATE", "Framer", "caller_messages", "float_to_pcm16"]
