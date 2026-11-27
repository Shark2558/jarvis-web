# tests/test_r52_v2_service_routing.py -- R5.2 V2: the voice service's engine routing (plan 3.2,
# D7, 7a; I0 seams). Listening follows `jarvis.voice.profile.listening_order`: the session's best,
# then Google, then the browser; before a session the laptop's Whisper small first while the kit is
# healthy. The owner's corrections are applied after listening (`Correction` keeps them off
# numbers, money and codes). The console's voice is the laptop's while it is healthy (never for a
# preview of a Google voice). A kit that is off, slow or refusing falls back to Google, then the
# browser, with the existing messages: a kit failure is never shown as a Google error. The laptop
# costs nothing and is never metered; a build book guest never reaches the laptop or the profile.
from __future__ import annotations

import asyncio
import hashlib

import pytest
from billing_fakes import NOW, UID, Clock, billing, registry
from voice_fakes import FakeSTT, FakeTokens, FakeTTS, pcm, wav

from jarvis.config import Settings
from jarvis.localspeech import protocol as p
from jarvis.localspeech.memory import MemoryKit
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import PriceList
from jarvis.voice.laptop import LaptopVoice
from jarvis.voice.ports import BadAudio, VoiceUnavailable
from jarvis.voice.profile import Correction, ListenEngine, VoiceProfile
from jarvis.voice.profile_store import MemoryProfileStore
from jarvis.voice.service import SpeakRequest, VoiceEngines, VoiceService, build_voice_service
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore

PRICES = PriceList.from_settings(Settings(_env_file=None))
CLIP = pcm(1.2)


class Rig:
    def __init__(self, *, google: bool = True, kit: MemoryKit | None = None) -> None:
        self.docs = MemoryDocs()
        self.tts, self.stt = FakeTTS(), FakeSTT()
        self.kit = (
            kit
            if kit is not None
            else MemoryKit(heard={hashlib.sha256(CLIP).hexdigest(): "open java's notes"})
        )
        self.laptop = LaptopVoice(self.kit, health_s=30)
        self.profiles = MemoryProfileStore()
        self.billing = billing(registry(), docs=self.docs, clock=Clock(NOW))
        engines = VoiceEngines(tts=self.tts, stt=self.stt, tokens=FakeTokens()) if google else None
        self.svc = VoiceService(
            store=VoiceSettingsStore(self.docs),
            billing=self.billing,
            prices=PRICES,
            engines=engines,
            language="en-IN",
            honorific="Sir",
            laptop=self.laptop,
            profiles=self.profiles,
        )

    async def profile(self, **kw: object) -> None:
        await self.profiles.save(UID, VoiceProfile.model_validate(kw))

    async def used(self, key: str) -> float:
        return (await self.billing.allowance((key,))).used(key)


# ---- listening -----------------------------------------------------------------------------------
async def test_before_a_session_the_laptop_listens_first_at_no_cost() -> None:
    r = Rig()
    out = await r.svc.transcribe(UID, wav(1.2))
    assert out.text == "open java's notes" and out.cost_inr == 0.0 and out.seconds == 1.2
    assert r.stt.calls == [] and "stt" in r.kit.calls
    assert await r.used("stt_seconds") == 0  # the laptop never touches Google's allowance
    assert r.laptop.last_served(p.Kind.STT) == "laptop-whisper-small"


async def test_the_sessions_best_laptop_engine_is_asked_for_by_name() -> None:
    r = Rig()
    await r.profile(chosen="laptop-whisper-medium")
    seen: list[p.SttRequest] = []
    original = r.kit.stt

    async def spy(req: p.SttRequest) -> p.SttResult:
        seen.append(req)
        return await original(req)

    r.kit.stt = spy  # type: ignore[method-assign]
    await r.svc.transcribe(UID, wav(1.2))
    assert seen[0].slot is p.EngineSlot.WHISPER_MEDIUM
    assert r.laptop.last_served(p.Kind.STT) == "laptop-whisper-medium"


@pytest.mark.parametrize("chosen", [ListenEngine.GOOGLE, ListenEngine.BROWSER])
async def test_when_google_or_the_browser_hears_him_best_the_laptop_is_not_asked(
    chosen: ListenEngine,
) -> None:
    r = Rig()
    await r.profile(chosen=chosen.value)
    out = await r.svc.transcribe(UID, wav(1.2))
    assert out.text == r.stt.text and len(r.stt.calls) == 1
    assert r.kit.calls == []  # not even its health
    assert r.laptop.last_served(p.Kind.STT) == "google"


@pytest.mark.parametrize("why", ["offline", "slow", "busy", "unauthorized"])
async def test_a_kit_that_is_off_slow_or_refusing_falls_back_to_google(why: str) -> None:
    r = Rig()
    if why == "slow":
        r.kit.slow = True
    else:
        r.kit.down = why  # type: ignore[assignment]
    out = await r.svc.transcribe(UID, wav(1.2))
    assert out.text == r.stt.text and len(r.stt.calls) == 1
    assert out.cost_inr == 0.0 and await r.used("stt_seconds") == 2  # Google, metered as today


async def test_a_kit_that_fails_mid_listen_falls_back_and_is_remembered() -> None:
    r = Rig()
    assert await r.laptop.ready(p.Kind.STT)
    r.kit.down = "timeout"
    out = await r.svc.transcribe(UID, wav(1.2))
    assert out.text == r.stt.text
    r.kit.down = None
    before = len(r.kit.calls)
    await r.svc.transcribe(UID, wav(1.2))
    assert len(r.kit.calls) == before and len(r.stt.calls) == 2  # Google until the next check


async def test_a_kit_failure_without_google_is_the_browsers_existing_message() -> None:
    r = Rig(google=False)
    r.kit.down = "offline"
    with pytest.raises(VoiceUnavailable) as down:
        await r.svc.transcribe(UID, wav(1.2))
    assert down.value.reason == "not_configured"  # "...; the browser's voice is used."
    assert "Google" not in str(down.value)


async def test_without_google_a_healthy_laptop_still_listens() -> None:
    r = Rig(google=False)
    out = await r.svc.transcribe(UID, wav(1.2))
    assert out.text == "open java's notes"


async def test_google_failing_after_the_kit_shows_googles_own_words() -> None:
    r = Rig()
    r.kit.down = "offline"
    r.stt.fail = VoiceUnavailable("upstream_error")
    with pytest.raises(VoiceUnavailable) as down:
        await r.svc.transcribe(UID, wav(1.2))
    assert down.value.reason == "upstream_error"


async def test_a_recording_the_kit_cant_use_is_bad_audio() -> None:
    class Refusing(MemoryKit):
        async def stt(self, req: p.SttRequest) -> p.SttResult:
            raise p.KitRefused("bad_audio", "no")

    r = Rig(kit=Refusing())
    with pytest.raises(BadAudio):
        await r.svc.transcribe(UID, wav(1.2))


async def test_the_owners_words_reach_the_kit() -> None:
    r = Rig()
    await r.svc.update_settings(UID, VoiceSettingsPatch(phrases=["Priya", "Shimla"]))
    seen: list[p.SttRequest] = []
    original = r.kit.stt

    async def spy(req: p.SttRequest) -> p.SttResult:
        seen.append(req)
        return await original(req)

    r.kit.stt = spy  # type: ignore[method-assign]
    await r.svc.transcribe(UID, wav(1.2), turn_hints=("budget.xlsx",))
    words = seen[0].phrases
    assert words[:2] == ("JARVIS", "Hey Jarvis") and {"Priya", "Shimla", "budget.xlsx"} <= set(
        words
    )


# ---- corrections after listening -----------------------------------------------------------------
async def test_corrections_apply_after_any_engine_listens() -> None:
    r = Rig()
    await r.profile(corrections=[{"heard": "java's", "meant": "JARVIS's"}])
    laptop = await r.svc.transcribe(UID, wav(1.2))
    assert laptop.text == "open JARVIS's notes"
    r.kit.down = "offline"
    r.stt.text = "Java's reminder for two rupees"
    google = await r.svc.transcribe(UID, wav(1.2))
    assert google.text == "JARVIS's reminder for two rupees"  # numbers and money untouched


async def test_corrections_switched_off_are_not_applied() -> None:
    r = Rig()
    await r.profile(corrections=[{"heard": "java's", "meant": "JARVIS"}], corrections_on=False)
    assert (await r.svc.transcribe(UID, wav(1.2))).text == "open java's notes"


def test_a_correction_can_never_touch_numbers_money_or_codes() -> None:
    for heard, meant in (("two", "to"), ("rupees", "rupes"), ("otp", "opt"), ("4", "for")):
        with pytest.raises(ValueError):
            Correction(heard=heard, meant=meant)


# ---- a guest and a broken profile store ----------------------------------------------------------
async def test_a_build_book_guest_never_reaches_the_laptop_or_the_profile() -> None:
    r = Rig()
    await r.profile(corrections=[{"heard": "calendar", "meant": "Calendar app"}])
    out = await r.svc.transcribe(UID, wav(1.2), owner_phrases=False)
    assert "Calendar app" not in out.text and r.kit.calls == []
    await r.svc.transcribe(UID, wav(1.2), free_only=True)
    assert r.kit.calls == [] and len(r.stt.calls) == 2


async def test_a_profile_store_that_fails_or_hangs_never_stops_listening() -> None:
    class Broken(MemoryProfileStore):
        hang = False

        async def get(self, uid: str) -> VoiceProfile:
            if self.hang:
                await asyncio.sleep(5)
            raise RuntimeError("store down")

    r = Rig()
    r.svc.route.profiles = Broken()
    assert (await r.svc.transcribe(UID, wav(1.2))).text == "open java's notes"
    broken = Broken()
    broken.hang = True
    r2 = Rig()
    r2.svc.route.profiles = broken
    out = await asyncio.wait_for(r2.svc.transcribe(UID, wav(1.2)), 2.0)
    assert out.text


# ---- speaking ------------------------------------------------------------------------------------
async def test_the_console_voice_is_the_laptops_while_it_is_healthy() -> None:
    r = Rig()
    out = await r.svc.speak(UID, SpeakRequest(text="Good evening, Sir."))
    assert out.audio.startswith(b"ID3") and out.cost_inr == 0.0 and out.engine == "laptop-kokoro"
    assert r.tts.calls == [] and await r.used("tts_chirp3-hd") == 0
    assert r.laptop.last_served(p.Kind.TTS) == "laptop-kokoro"


async def test_a_preview_of_a_google_voice_and_a_guest_use_google() -> None:
    r = Rig()
    await r.svc.speak(UID, SpeakRequest(preview=True))
    await r.svc.speak(UID, SpeakRequest(text="Hello."), free_only=True)
    assert len(r.tts.calls) == 2 and "tts" not in r.kit.calls


@pytest.mark.parametrize("why", ["offline", "slow", "timeout"])
async def test_speaking_falls_back_to_google(why: str) -> None:
    r = Rig()
    if why == "slow":
        r.kit.slow = True
    else:
        r.kit.down = why  # type: ignore[assignment]
    out = await r.svc.speak(UID, SpeakRequest(text="Hello."))
    assert out.engine == "google" and len(r.tts.calls) == 1
    assert r.laptop.last_served(p.Kind.TTS) == "google"


async def test_speaking_without_google_or_a_kit_is_the_existing_message() -> None:
    r = Rig(google=False)
    r.kit.down = "offline"
    with pytest.raises(VoiceUnavailable) as down:
        await r.svc.speak(UID, SpeakRequest(text="Hello."))
    assert down.value.reason == "not_configured"


# ---- wiring --------------------------------------------------------------------------------------
async def test_without_a_laptop_or_profiles_nothing_changes() -> None:
    r = Rig()
    plain = VoiceService(
        store=VoiceSettingsStore(r.docs),
        billing=r.billing,
        prices=PRICES,
        engines=VoiceEngines(tts=r.tts, stt=r.stt, tokens=FakeTokens()),
        language="en-IN",
        honorific="Sir",
    )
    out = await plain.transcribe(UID, wav(1.2))
    assert out.text == r.stt.text and out.cost_inr == 0.0
    assert (await plain.speak(UID, SpeakRequest(text="Hi."))).engine == "google"


async def test_build_and_close_with_the_laptop(settings: Settings) -> None:
    r = Rig()
    svc = build_voice_service(
        settings,
        r.docs,
        r.billing,
        engines=VoiceEngines(tts=r.tts, stt=r.stt, tokens=FakeTokens()),
        laptop=r.laptop,
        profiles=r.profiles,
    )
    assert svc.route.laptop is r.laptop and svc.route.profiles is r.profiles
    await svc.aclose()


def test_corrections_reach_the_alternatives_and_never_an_empty_text() -> None:
    from jarvis.voice.routing import corrected

    profile = VoiceProfile.model_validate({"corrections": [{"heard": "java's", "meant": "JARVIS"}]})
    text, alts = corrected("java's on", ["java's off", "JARVIS on"], profile)
    assert (text, alts) == ("JARVIS on", ["JARVIS off"])
    assert corrected("", ["java's"], profile) == ("", ["java's"])
