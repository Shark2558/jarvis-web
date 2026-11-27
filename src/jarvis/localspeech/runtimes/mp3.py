# src/jarvis/localspeech/runtimes/mp3.py
"""MP3 for the console's voice (`TtsRequest.format == "mp3"`; `POST /v1/voice/speak` answers
`audio/mpeg`). PyAV (BSD-3-Clause; its wheels bundle FFmpeg and LAME, LGPL, loaded unmodified) is
already a faster-whisper dependency, so no new package; imported only in `encode`.
"""

from __future__ import annotations

import io
from typing import Final

BIT_RATE: Final = 64_000  # plenty for one voice


class PyAvMp3:
    def encode(self, pcm: bytes, sample_rate: int) -> bytes:
        import av  # imported only here
        import numpy as np

        samples = np.frombuffer(pcm, dtype="<i2").reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = sample_rate
        out = io.BytesIO()
        with av.open(out, mode="w", format="mp3") as container:
            stream = container.add_stream("mp3", rate=sample_rate, layout="mono")
            stream.bit_rate = BIT_RATE
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        return out.getvalue()


__all__ = ["PyAvMp3"]
