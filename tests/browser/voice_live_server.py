# tests/browser/voice_live_server.py — the real app with fake Google speech engines, for
# test_voice_live.py: `python voice_live_server.py <port>` (environment as tests/browser/conftest.py
# sets it). Everything but Google is real: /v1/voice*, billing units, rate limits, the WAV check,
# the chat with channel "voice". Not a test module (pytest does not collect it).
from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/: voice_fakes
from voice_fakes import FakeSTT, FakeTokens, FakeTTS, wav  # noqa: E402

from jarvis.api.app import create_app  # noqa: E402
from jarvis.voice.service import VoiceEngines  # noqa: E402

TRANSCRIPT = "Turn on the lights. Then dim them to half."


class WavTTS(FakeTTS):
    """FakeTTS that answers with a short real WAV, so the browser can decode and play it."""

    async def synthesize(self, text: str, *, voice: str, language: str, rate: float) -> bytes:
        await super().synthesize(text, voice=voice, language=language, rate=rate)
        return wav(0.25)


def main() -> None:
    port = int(sys.argv[1])
    engines = VoiceEngines(tts=WavTTS(), stt=FakeSTT(text=TRANSCRIPT), tokens=FakeTokens())
    uvicorn.run(create_app(voice_engines=engines), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
