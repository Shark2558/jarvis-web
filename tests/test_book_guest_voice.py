# tests/test_book_guest_voice.py -- R6 D1 for spoken questions: a guest's recording is transcribed
# with the base hints only, never biased toward the owner's own "words to recognise" (names,
# places); the owner's talk-through keeps them. The route asks for exactly that.
from __future__ import annotations

from typing import Any

from billing_fakes import NOW, UID, Clock, billing, registry
from book_app_fakes import book, book_app, open_book, register_passkey, sign_in
from voice_fakes import FakeSTT, FakeTokens, FakeTTS, wav

from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import PriceList
from jarvis.voice.service import VoiceEngines, VoiceService
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore


async def test_transcribe_can_leave_the_owners_words_out() -> None:
    docs, stt = MemoryDocs(), FakeSTT()
    svc = VoiceService(
        store=VoiceSettingsStore(docs),
        billing=billing(registry(), docs=docs, clock=Clock(NOW)),
        prices=PriceList.from_settings(Settings(_env_file=None)),
        engines=VoiceEngines(tts=FakeTTS(), stt=stt, tokens=FakeTokens()),
        language="en-IN",
        honorific="Sir",
    )
    patch = VoiceSettingsPatch.model_validate({"phrases": ["Trivandrum", "Kochi"]})
    await svc.update_settings(UID, patch)
    await svc.transcribe(UID, wav(1.0))
    assert stt.calls[-1]["phrases"][-2:] == ("Trivandrum", "Kochi")
    await svc.transcribe(UID, wav(1.0), owner_phrases=False)
    assert "Kochi" not in stt.calls[-1]["phrases"] and "Sir" in stt.calls[-1]["phrases"]


class Ears:
    """app.state.voice for the hear route: records how it was asked to transcribe."""

    def __init__(self) -> None:
        self.asked: list[bool] = []

    async def aclose(self) -> None:
        return None

    async def transcribe(self, uid: str, blob: bytes, *, owner_phrases: bool = True) -> Any:
        self.asked.append(owner_phrases)

        class Heard:
            text = "how does voice work"

        return Heard()


async def test_the_hear_route_drops_the_owners_words_for_a_guest(settings: Settings) -> None:
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00" * 16_000)
    async for app in book_app(settings):
        app.state.voice = ears = Ears()
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            for audience in ("owner", "guest"):
                h = {**book((await open_book(c, auth, audience))["token"])}
                h["Content-Type"] = "audio/wav"
                r = await c.post("/v1/book/show/hear", content=out.getvalue(), headers=h)
                assert r.status_code == 200 and r.json() == {"text": "how does voice work"}
        assert ears.asked == [True, False]
