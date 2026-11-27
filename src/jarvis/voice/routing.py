# src/jarvis/voice/routing.py
"""Which engine serves the owner's console voice (R5.2 V2; plan 3.2, D7, 7a; I0 seams), for
`jarvis.voice.service.VoiceService`:

- listening follows `jarvis.voice.profile.listening_order`: the session's best, then Google, then
  the browser, each once; before a session the laptop's Whisper small first while the kit is
  healthy. Only a laptop engine is served here; Google stays the service's own path (its gate and
  meter), the browser the console's.
- the owner's voice is the laptop's while the kit is healthy.
- a kit that is off, slow or refusing answers None (the service falls back silently to Google,
  then the browser, with the existing messages); `LaptopUnavailable` never leaves this module. A
  recording the kit can't use is `BadAudio`, as Google's would be.
- the owner's corrections are applied after listening, whichever engine listened (`corrected`;
  `Correction` itself keeps them off numbers, money and codes).
- the profile is read within `read_s`; a failed or slow read is the default (no session yet) and
  is remembered `memo_s`, so a broken store never stops listening.

The laptop costs nothing: nothing here gates or meters. Nothing is logged but lengths, the engine
and the reason it fell back.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

from jarvis.localspeech.protocol import Kind
from jarvis.logging import get_logger
from jarvis.voice.laptop import GOOGLE, LaptopUnavailable, LaptopVoice
from jarvis.voice.ports import Transcript
from jarvis.voice.profile import ListenEngine, VoiceProfile, apply_corrections, listening_order
from jarvis.voice.profile_ports import ProfileStore

log = get_logger(__name__)


def corrected(
    text: str, alternatives: Sequence[str], profile: VoiceProfile
) -> tuple[str, list[str]]:
    """`text` and its alternatives with the owner's corrections (whole words, one pass)."""
    fixes = profile.corrections
    if not profile.corrections_on or not fixes or not text:
        return text, list(alternatives)
    out = apply_corrections(text, fixes)
    alts = [apply_corrections(a, fixes) for a in alternatives]
    return out, [a for a in dict.fromkeys(alts) if a != out]


class EngineRoute:
    def __init__(
        self,
        laptop: LaptopVoice | None,
        profiles: ProfileStore | None,
        *,
        clock: Callable[[], float],
        read_s: float,
        memo_s: float,
    ) -> None:
        self.laptop = laptop
        self.profiles = profiles
        self._clock = clock
        self._read_s = read_s
        self._memo_s = memo_s
        self._fail_until: dict[str, float] = {}

    async def profile_of(self, uid: str) -> VoiceProfile:
        """The owner's voice profile; never raises (the default on any failure)."""
        if self.profiles is None or self._clock() < self._fail_until.get(uid, 0.0):
            return VoiceProfile()
        try:
            return await asyncio.wait_for(self.profiles.get(uid), self._read_s)
        except Exception as exc:  # noqa: BLE001 — listening with the defaults beats not listening
            self._fail_until[uid] = self._clock() + self._memo_s
            log.warning(
                "voice profile unreadable; using the defaults",
                extra={"reason": type(exc).__name__},
            )
            return VoiceProfile()

    async def laptop_first(self, profile: VoiceProfile) -> ListenEngine | None:
        """D7: the first engine of his listening order, when it is on the laptop and ready."""
        laptop = self.laptop
        if laptop is None or laptop.kit is None:
            return None
        wanted = listening_order(profile, laptop_ready=True)[0]
        ready = wanted.on_laptop and await laptop.ready(Kind.STT, wanted.slot)
        first = listening_order(profile, laptop_ready=ready)[0]
        return first if first.on_laptop else None

    async def listen(
        self,
        engine: ListenEngine,
        pcm: bytes,
        *,
        sample_rate: int,
        language: str,
        phrases: tuple[str, ...],
    ) -> Transcript | None:
        """`engine` (from `laptop_first`) hears it on the laptop; None to fall back to Google."""
        if self.laptop is None or not engine.on_laptop:
            return None
        try:
            return await self.laptop.stt.recognize(
                pcm, sample_rate=sample_rate, language=language, phrases=phrases, slot=engine.slot
            )
        except LaptopUnavailable as exc:
            log.info(
                "voice: the laptop could not listen; Google listens", extra={"why": exc.reason}
            )
            return None

    async def speak(self, spoken: str, *, language: str, rate: float) -> tuple[bytes, str] | None:
        """The console's voice on the laptop while it is healthy: (MP3, engine) or None."""
        laptop = self.laptop
        if laptop is None or not await laptop.ready(Kind.TTS):
            return None
        try:
            audio = await laptop.tts.synthesize(spoken, voice="", language=language, rate=rate)
        except LaptopUnavailable as exc:
            log.info("voice: the laptop could not speak; Google speaks", extra={"why": exc.reason})
            return None
        return audio, laptop.last_served(Kind.TTS) or "laptop"

    def google_served(self, kind: Kind) -> None:
        """Google served `kind` for the owner: noted for the laptop's status and Vitals."""
        if self.laptop is not None:
            self.laptop.note_served(kind, GOOGLE)

    async def aclose(self) -> None:
        if self.laptop is not None:
            await self.laptop.aclose()


__all__ = ["EngineRoute", "corrected"]
