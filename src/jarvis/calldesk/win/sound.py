# src/jarvis/calldesk/win/sound.py
"""`ports.SoundDevices` on soundcard (BSD-3-Clause; WASAPI) and NumPy (Windows only; R18 C).

- Hearing: a loopback recorder on the default speaker (what Phone Link plays: the call), asked for
  16 kHz mono directly; WASAPI's own converter (soundcard opens shared-mode streams with
  AUTOCONVERTPCM and the better sample-rate converter) resamples and mixes the channels down, so
  no resampler runs in Python. 100 ms of device buffer; silence arrives as zeros.
- Speaking: a player on "CABLE Input" at 16 kHz mono, 100 ms of device buffer (so a late Python
  thread doesn't break JARVIS's voice up, and a cut is heard within about a tenth of a second).

Device failures become `AudioDeviceError` with plain words (no device names, no audio).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import soundcard as sc

from jarvis.calldesk.audio import FRAME_BYTES, FRAME_SAMPLES, RATE
from jarvis.calldesk.checks import CABLE_SPEAKER
from jarvis.calldesk.ports import AudioDeviceError, Capture, Player

BUFFER_FRAMES = RATE // 10  # 100 ms


class _Loopback:
    def __init__(self, recorder: Any) -> None:
        self._rec = recorder

    def read(self) -> bytes:
        try:
            data = self._rec.record(numframes=FRAME_SAMPLES)
        except Exception:  # noqa: BLE001 - WASAPI errors arrive as RuntimeError and others
            raise AudioDeviceError("The laptop's speaker recording stopped.") from None
        mono = np.asarray(data, dtype=np.float32).reshape(-1)[:FRAME_SAMPLES]
        pcm = (np.clip(mono, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        return pcm if len(pcm) == FRAME_BYTES else pcm.ljust(FRAME_BYTES, b"\x00")

    def close(self) -> None:
        try:
            self._rec.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            raise AudioDeviceError("The speaker recording did not close cleanly.") from None


class _CablePlayer:
    def __init__(self, player: Any) -> None:
        self._player = player

    def write(self, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        try:
            self._player.play(samples.reshape(-1, 1))
        except Exception:  # noqa: BLE001
            raise AudioDeviceError("Playing into CABLE Input stopped.") from None

    def close(self) -> None:
        try:
            self._player.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            raise AudioDeviceError("CABLE Input did not close cleanly.") from None


class WinSoundDevices:
    def open_loopback(self) -> Capture:
        try:
            speaker = sc.default_speaker()
            loopback = sc.get_microphone(id=str(speaker.id), include_loopback=True)
            recorder = loopback.recorder(samplerate=RATE, channels=1, blocksize=BUFFER_FRAMES)
            recorder.__enter__()
        except Exception:  # noqa: BLE001
            raise AudioDeviceError("The laptop's speaker could not be recorded.") from None
        return _Loopback(recorder)

    def open_cable_player(self) -> Player:
        try:
            cable = sc.get_speaker(CABLE_SPEAKER)
            player = cable.player(samplerate=RATE, channels=1, blocksize=BUFFER_FRAMES)
            player.__enter__()
        except Exception:  # noqa: BLE001
            raise AudioDeviceError("CABLE Input could not be opened.") from None
        return _CablePlayer(player)


__all__ = ["BUFFER_FRAMES", "WinSoundDevices"]
