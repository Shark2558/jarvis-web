# src/jarvis/voice/wav.py
"""Strict WAV reader for transcribe (slice 9 §2; Layer 2 input processing).

Accepted: RIFF/WAVE, a `fmt ` chunk of PCM (format 1), 16-bit, mono, 16,000 Hz (byte rate and
block align consistent), then a `data` chunk wholly inside the file, of whole samples, lasting
0.3–60 s. Other chunks (LIST, …) are skipped. Anything else — MP3, Ogg, stereo, 44.1/48 kHz,
8-bit, float, WAVE_FORMAT_EXTENSIBLE, truncated or inconsistent sizes — is `BadAudio`, before any
cloud call. The samples are returned as-is (never stored, never logged).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from jarvis.voice.ports import BadAudio

SAMPLE_RATE = 16_000
BITS = 16
CHANNELS = 1
PCM_FORMAT = 1
MIN_SECONDS = 0.3
MAX_SECONDS = 60
MAX_CHUNKS = 32  # a real recording has 2–4; a crafted file can't make us walk forever
_BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * BITS // 8

MSG_FORMAT = "Send a WAV recording: 16-bit PCM, mono, 16,000 Hz."


@dataclass(frozen=True)
class Audio:
    pcm: bytes
    sample_rate: int
    seconds: float


def _fmt_ok(body: bytes) -> bool:
    if len(body) < 16:
        return False
    fmt, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", body)
    return bool(
        fmt == PCM_FORMAT
        and channels == CHANNELS
        and rate == SAMPLE_RATE
        and bits == BITS
        and align == CHANNELS * BITS // 8
        and byte_rate == _BYTES_PER_SECOND
    )


def parse_wav(blob: bytes) -> Audio:
    """The PCM samples of a valid recording, else BadAudio (plain words, no details echoed)."""
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise BadAudio(MSG_FORMAT)
    (riff_size,) = struct.unpack_from("<I", blob, 4)
    end = 8 + riff_size
    if end > len(blob):
        raise BadAudio("The recording is cut short.")
    pos, fmt_seen = 12, False
    for _ in range(MAX_CHUNKS):
        if pos + 8 > end:
            break
        cid = blob[pos : pos + 4]
        (size,) = struct.unpack_from("<I", blob, pos + 4)
        start = pos + 8
        if start + size > end:
            raise BadAudio("The recording is cut short.")
        if cid == b"fmt ":
            if not _fmt_ok(blob[start : start + size]):
                raise BadAudio(MSG_FORMAT)
            fmt_seen = True
        elif cid == b"data":
            if not fmt_seen:
                raise BadAudio(MSG_FORMAT)
            return _audio(blob[start : start + size])
        pos = start + size + (size & 1)  # chunks are padded to an even length
    raise BadAudio(MSG_FORMAT)


def _audio(data: bytes) -> Audio:
    if len(data) % (BITS // 8):
        raise BadAudio(MSG_FORMAT)
    seconds = len(data) / _BYTES_PER_SECOND
    if seconds < MIN_SECONDS:
        raise BadAudio("That recording is too short to hear anything.")
    if seconds > MAX_SECONDS:
        raise BadAudio(f"Recordings are limited to {MAX_SECONDS} seconds.")
    return Audio(pcm=data, sample_rate=SAMPLE_RATE, seconds=seconds)


__all__ = ["MAX_SECONDS", "MIN_SECONDS", "SAMPLE_RATE", "Audio", "parse_wav"]
