# src/jarvis/calldesk/dtmf.py
"""Key tones played into the call as sound (plan section 4 step 10; S0's Test C).

The standard pair of frequencies per key, 250 ms of tone and 150 ms of silence (what S0 tests),
5 ms fades so there is no click, at 16 kHz PCM16: exactly 20 frames per key.
"""

from __future__ import annotations

import math

from jarvis.calldesk.audio import RATE, float_to_pcm16

TONE_S = 0.25
GAP_S = 0.15
AMPLITUDE = 0.4  # per frequency: the sum peaks at 0.8 of full scale
FADE_S = 0.005

DTMF_HZ: dict[str, tuple[int, int]] = {
    "1": (697, 1209),
    "2": (697, 1336),
    "3": (697, 1477),
    "4": (770, 1209),
    "5": (770, 1336),
    "6": (770, 1477),
    "7": (852, 1209),
    "8": (852, 1336),
    "9": (852, 1477),
    "*": (941, 1209),
    "0": (941, 1336),
    "#": (941, 1477),
}


def tone(digit: str) -> bytes:
    """One key's tone and the silence after it, as PCM16 at 16 kHz."""
    if digit not in DTMF_HZ:
        raise ValueError("not a phone key")
    low, high = DTMF_HZ[digit]
    n = int(RATE * TONE_S)
    fade = int(RATE * FADE_S)
    samples = []
    for i in range(n):
        t = i / RATE
        gain = min(1.0, i / fade, (n - 1 - i) / fade)
        value = math.sin(2 * math.pi * low * t) + math.sin(2 * math.pi * high * t)
        samples.append(AMPLITUDE * gain * value)
    return float_to_pcm16(samples) + b"\x00\x00" * int(RATE * GAP_S)


__all__ = ["AMPLITUDE", "DTMF_HZ", "GAP_S", "TONE_S", "tone"]
