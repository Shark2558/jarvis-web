"""R18 C: the call desk's audio format, framing, voice detector and key tones (no Windows needed).

The voice detector is the money gate of plan section 4 step 4: audio reaches the cloud only while
the other person speaks. These cases pin that silence, hiss and hum send nothing, speech sends its
start (the pre-roll) and its tail (the hangover), and that barge-in needs a longer onset.
"""

from __future__ import annotations

import math
import random
import struct

import pytest

from jarvis.calldesk import audio, dtmf, vad

RATE = audio.RATE


def _pcm(samples: list[float]) -> bytes:
    """Float samples in -1..1 -> PCM16 little-endian."""
    clipped = (max(-1.0, min(1.0, s)) for s in samples)
    return b"".join(struct.pack("<h", int(round(s * 32767))) for s in clipped)


def _tone(freq: float, ms: int, level: float) -> bytes:
    n = RATE * ms // 1000
    return _pcm([level * math.sin(2 * math.pi * freq * i / RATE) for i in range(n)])


def _speech(ms: int, level: float = 0.3, seed: int = 3) -> bytes:
    """Voiced, speech-like sound: a few harmonics of a wobbling 140 Hz pitch."""
    rng = random.Random(seed)
    n = RATE * ms // 1000
    out = []
    for i in range(n):
        t = i / RATE
        f0 = 140 + 20 * math.sin(2 * math.pi * 3 * t)
        s = sum(math.sin(2 * math.pi * f0 * k * t) / k for k in (1, 2, 3, 4))
        out.append(level * 0.5 * s + rng.gauss(0, 0.002))
    return _pcm(out)


def _noise(ms: int, level: float, seed: int = 5) -> bytes:
    rng = random.Random(seed)
    return _pcm([rng.gauss(0, level) for _ in range(RATE * ms // 1000)])


def _frames(pcm: bytes) -> list[bytes]:
    return audio.split_frames(pcm)


def _run(det: vad.VoiceDetector, pcm: bytes, *, jarvis_speaking: bool = False) -> list[vad.Step]:
    return [det.push(f, jarvis_speaking=jarvis_speaking) for f in _frames(pcm)]


# ---- the format --------------------------------------------------------------------------------


def test_frame_is_20_ms_of_16_khz_mono_pcm16() -> None:
    assert (audio.RATE, audio.FRAME_SAMPLES, audio.FRAME_BYTES) == (16000, 320, 640)


def test_framer_cuts_any_chunks_into_whole_frames_and_keeps_the_rest() -> None:
    framer = audio.Framer()
    assert framer.push(b"\x01" * 600) == []
    frames = framer.push(b"\x02" * 700)
    assert [len(f) for f in frames] == [640, 640][: len(frames)]
    assert len(frames) == 2 and framer.pending == 600 + 700 - 1280
    tail = framer.flush()
    assert len(tail) == 640 and tail.endswith(b"\x00") and framer.pending == 0
    assert framer.flush() == b""


def test_split_frames_pads_the_last_frame_with_silence() -> None:
    frames = audio.split_frames(b"\x05" * 700)
    assert [len(f) for f in frames] == [640, 640]
    assert frames[1][:60] == b"\x05" * 60 and frames[1][60:] == b"\x00" * 580


def test_tagged_audio_round_trip_and_refusals() -> None:
    msg = audio.tag(audio.TAG_CALLER, b"\x00\x01" * 320)
    assert msg[0] == 0x01 and len(msg) == 641
    assert audio.untag(msg) == (audio.TAG_CALLER, b"\x00\x01" * 320)
    with pytest.raises(audio.AudioFormatError):
        audio.untag(b"")
    with pytest.raises(audio.AudioFormatError):
        audio.untag(b"\x09" + b"\x00" * 640)  # unknown tag
    with pytest.raises(audio.AudioFormatError):
        audio.untag(b"\x02" + b"\x00" * 3)  # odd: not PCM16
    with pytest.raises(audio.AudioFormatError):
        audio.untag(b"\x02" + b"\x00" * (audio.MAX_AUDIO_BYTES + 2))
    with pytest.raises(audio.AudioFormatError):
        audio.tag(0x07, b"\x00\x00")


def test_float_to_pcm16_clips_and_rounds() -> None:
    assert audio.float_to_pcm16([0.0, 1.0, -1.0, 2.0, -2.0]) == struct.pack(
        "<5h", 0, 32767, -32767, 32767, -32767
    )


# ---- the voice detector ------------------------------------------------------------------------


def test_frame_stats_level_and_zero_crossings() -> None:
    silent = vad.frame_stats(b"\x00" * 640)
    assert silent.level_dbfs == vad.FLOOR_DBFS and silent.zcr == 0.0
    loud = vad.frame_stats(_tone(1000, 20, 0.5))
    assert -10.0 < loud.level_dbfs < -8.0  # a 0.5 sine is -9 dBFS rms
    assert 0.11 < loud.zcr < 0.14  # 2000 crossings a second / 16000 samples


def test_silence_sends_nothing() -> None:
    det = vad.VoiceDetector()
    steps = _run(det, b"\x00" * 640 * 100)
    assert not any(s.frames for s in steps) and not det.speaking


def test_quiet_hiss_and_mains_hum_send_nothing() -> None:
    det = vad.VoiceDetector()
    hiss = _run(det, _noise(2000, 0.002))
    hum = _run(det, _tone(50, 2000, 0.3))  # loud but almost no zero crossings
    loud_hiss = _run(det, _noise(1000, 0.3))  # broadband: crossings above speech's
    assert not any(s.frames for s in hiss + hum + loud_hiss)


def test_speech_starts_with_its_preroll_and_ends_after_the_hangover() -> None:
    det = vad.VoiceDetector()
    _run(det, _noise(1000, 0.001))  # learn the line's floor
    talk = _run(det, _speech(600))
    started = [i for i, s in enumerate(talk) if s.started]
    assert started == [vad.DEFAULTS.onset_frames - 1]
    first = talk[started[0]]
    # the frames just before the onset (the pre-roll, onset frames included) go with the first send
    assert len(first.frames) == vad.DEFAULTS.preroll_frames
    assert first.frames[-1] == _frames(_speech(600))[started[0]]
    assert all(len(s.frames) == 1 for s in talk[started[0] + 1 :])
    tail = _run(det, b"\x00" * 640 * 40)
    stopped = [i for i, s in enumerate(tail) if s.stopped]
    assert stopped == [vad.DEFAULTS.hangover_frames - 1]
    assert all(len(s.frames) == 1 for s in tail[: stopped[0]])
    assert not tail[stopped[0]].frames and not any(s.frames for s in tail[stopped[0] + 1 :])
    assert not det.speaking


def test_a_click_shorter_than_the_onset_sends_nothing() -> None:
    det = vad.VoiceDetector()
    _run(det, _noise(500, 0.001))
    steps = _run(det, _speech(20 * (vad.DEFAULTS.onset_frames - 1)) + b"\x00" * 640 * 10)
    assert not any(s.frames for s in steps)


def test_barge_in_needs_a_longer_onset_while_jarvis_speaks() -> None:
    det = vad.VoiceDetector()
    _run(det, _noise(500, 0.001))
    short = 20 * (vad.DEFAULTS.barge_in_onset_frames - 1)
    steps = _run(det, _speech(short), jarvis_speaking=True)
    assert not any(s.started for s in steps)
    det.reset()
    _run(det, _noise(500, 0.001))
    steps = _run(det, _speech(400), jarvis_speaking=True)
    assert [i for i, s in enumerate(steps) if s.started] == [vad.DEFAULTS.barge_in_onset_frames - 1]


def test_noise_floor_rises_so_a_steady_loud_noise_stops_counting_as_speech() -> None:
    det = vad.VoiceDetector()
    # a steady fan-like rumble with speech-band crossings: speech at first, then it is the floor
    rumble = _speech(30_000, level=0.05, seed=9)
    steps = _run(det, rumble)
    assert steps[-1].frames == () and not det.speaking


def test_settings_are_checked() -> None:
    with pytest.raises(ValueError):
        vad.VadSettings(onset_frames=0)
    with pytest.raises(ValueError):
        vad.VadSettings(zcr_min=0.5, zcr_max=0.1)
    with pytest.raises(ValueError):
        vad.VoiceDetector().push(b"\x00" * 10)


# ---- key tones ---------------------------------------------------------------------------------


def _goertzel(pcm: bytes, freq: float) -> float:
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm)
    k = 2 * math.cos(2 * math.pi * freq / RATE)
    s1 = s2 = 0.0
    for x in samples:
        s1, s2 = x + k * s1 - s2, s1
    return s1 * s1 + s2 * s2 - k * s1 * s2


@pytest.mark.parametrize("digit", list("0123456789*#"))
def test_each_key_tone_holds_its_two_frequencies(digit: str) -> None:
    pcm = dtmf.tone(digit)
    assert len(pcm) % audio.FRAME_BYTES == 0
    tone = pcm[: int(RATE * dtmf.TONE_S) * 2]
    low, high = dtmf.DTMF_HZ[digit]
    others = {f for pair in dtmf.DTMF_HZ.values() for f in pair} - {low, high}
    strong = min(_goertzel(tone, low), _goertzel(tone, high))
    assert all(strong > 50 * _goertzel(tone, f) for f in others)
    gap = pcm[int(RATE * dtmf.TONE_S) * 2 :]
    assert max(abs(v) for v in struct.unpack(f"<{len(gap) // 2}h", gap)) == 0


def test_key_tone_never_clips_and_refuses_other_keys() -> None:
    pcm = dtmf.tone("5")
    peak = max(abs(v) for v in struct.unpack(f"<{len(pcm) // 2}h", pcm))
    assert 20000 < peak <= 32767
    for bad in ("", "55", "A", "x", " "):
        with pytest.raises(ValueError):
            dtmf.tone(bad)
