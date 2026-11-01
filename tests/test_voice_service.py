# tests/test_voice_service.py — slice 9 review fixes in VoiceService: the gate → Google → meter
# sequence is atomic per owner and kind (concurrent calls at the allowance edge or the limit can't
# all pass), a call cut short while Google may have it is still metered, and the settings reads
# that speak / the view / the persona make are time-bounded with a failure memo a PUT clears.
from __future__ import annotations

import asyncio

import httpx
import pytest
from billing_fakes import NOW, UID, Clock, billing, put_raw, registry
from voice_fakes import FakeSTT, FakeTokens, FakeTTS, GoogleScript, wav

from jarvis.billing import BudgetReached
from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import DEFAULT_VOICE, PriceList
from jarvis.voice.google_cloud import GoogleTTS
from jarvis.voice.service import SpeakRequest, VoiceEngines, VoiceService
from jarvis.voice.settings import VoiceSettings, VoiceSettingsPatch, VoiceSettingsStore

ALLOW = "jarvis_allowance/2026-11"
MONTH = f"jarvis_usage/{UID}_2026-11"
PRICES = PriceList.from_settings(Settings(_env_file=None))
FREE_CHARS = PRICES.chirp3_hd.free_units
FREE_SECONDS = PRICES.stt.free_units


class Rig:
    def __init__(self) -> None:
        self.docs = MemoryDocs()
        self.tts = FakeTTS()
        self.stt = FakeSTT()
        self.billing = billing(registry(), docs=self.docs, clock=Clock(NOW))
        self.svc = VoiceService(
            store=VoiceSettingsStore(self.docs),
            billing=self.billing,
            prices=PRICES,
            engines=VoiceEngines(tts=self.tts, stt=self.stt, tokens=FakeTokens()),
            language="en-IN",
            honorific="Sir",
        )

    async def at_the_limit(self, key: str, used: float) -> None:
        await put_raw(self.docs, ALLOW, {"units": {key: used}})
        await put_raw(self.docs, MONTH, {"inr_total": 600.0})
        await put_raw(self.docs, f"jarvis_budget/{UID}", {"monthly_limit_inr": 500})

    async def used(self, key: str) -> float:
        return (await self.billing.allowance((key,))).used(key)


# ---- review item 3: gate → call → meter is atomic per owner and kind ----------------------------


async def test_concurrent_speech_at_the_allowance_edge_cannot_all_pass_the_gate() -> None:
    r = Rig()
    r.tts.delay = 0.05  # both calls would be in flight together without the lock
    await r.at_the_limit("tts_chirp3-hd", FREE_CHARS - 10)
    req = SpeakRequest(text="Ten chars.")  # exactly the last 10 free characters
    out = await asyncio.gather(*(r.svc.speak(UID, req) for _ in range(3)), return_exceptions=True)
    assert sum(not isinstance(o, BaseException) for o in out) == 1
    assert sum(isinstance(o, BudgetReached) for o in out) == 2
    assert len(r.tts.calls) == 1 and await r.used("tts_chirp3-hd") == FREE_CHARS


async def test_concurrent_transcriptions_at_the_edge_cannot_all_pass_the_gate() -> None:
    r = Rig()
    r.stt.delay = 0.05
    await r.at_the_limit("stt_seconds", FREE_SECONDS - 2)
    clip = wav(1.5)  # ceil → 2 s: exactly the last free seconds
    out = await asyncio.gather(
        *(r.svc.transcribe(UID, clip) for _ in range(3)), return_exceptions=True
    )
    assert sum(isinstance(o, BudgetReached) for o in out) == 2
    assert len(r.stt.calls) == 1


async def test_the_lock_is_per_kind_so_speaking_never_waits_for_listening() -> None:
    r = Rig()
    r.stt.delay = 0.3
    listening = asyncio.ensure_future(r.svc.transcribe(UID, wav(1.0)))
    await asyncio.sleep(0.01)
    spoke = await asyncio.wait_for(r.svc.speak(UID, SpeakRequest(text="Quick.")), 0.2)
    assert spoke.chars == len("Quick.")
    await listening


# ---- review item 1: a call cut short while Google may have it is metered -------------------------


async def test_a_speak_cancelled_mid_call_is_still_metered() -> None:
    r = Rig()
    r.tts.delay = 5.0
    task = asyncio.ensure_future(r.svc.speak(UID, SpeakRequest(text="Cut short.")))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await r.used("tts_chirp3-hd") == len("Cut short.")


async def test_a_transcription_cancelled_mid_call_is_still_metered() -> None:
    r = Rig()
    r.stt.delay = 5.0
    task = asyncio.ensure_future(r.svc.transcribe(UID, wav(2.5)))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await r.used("stt_seconds") == 3  # ceil(2.5 s), the estimate


# ---- review items 9 and 13: bounded settings reads, a failure memo a PUT clears -----------------


class SlowStore(VoiceSettingsStore):
    def __init__(self, docs: MemoryDocs) -> None:
        super().__init__(docs)
        self.slow = True
        self.reads = 0

    async def get(self, uid: str) -> VoiceSettings:
        self.reads += 1
        if self.slow:
            await asyncio.sleep(5)
        return await super().get(uid)


def _with_store(r: Rig, store: VoiceSettingsStore) -> VoiceService:
    return VoiceService(
        store=store,
        billing=r.billing,
        prices=PRICES,
        engines=r.svc.engines,
        language="en-IN",
        honorific="Sir",
    )


def _with_engines(r: Rig, engines: VoiceEngines) -> VoiceService:
    return VoiceService(
        store=r.svc.store,
        billing=r.billing,
        prices=PRICES,
        engines=engines,
        language="en-IN",
        honorific="Sir",
    )


async def test_speak_and_the_view_never_hang_on_a_slow_settings_read() -> None:
    r = Rig()
    store = SlowStore(r.docs)
    svc = _with_store(r, store)
    out = await asyncio.wait_for(svc.speak(UID, SpeakRequest(text="Hello.")), 2.5)
    assert out.voice == DEFAULT_VOICE and r.tts.calls[-1]["rate"] == 1.0  # the defaults
    view = await asyncio.wait_for(svc.view(UID), 1.0)  # the failure is remembered: no wait
    assert view.settings == VoiceSettings()
    assert await asyncio.wait_for(svc.wit_for(UID), 1.0) == "film"
    assert store.reads == 1


async def test_a_put_clears_the_failure_memo_so_the_new_wit_applies_at_once() -> None:
    r = Rig()
    store = SlowStore(r.docs)
    svc = _with_store(r, store)
    assert await svc.wit_for(UID) == "film"  # slow → remembered as a failure for 30 s
    store.slow = False
    await svc.update_settings(UID, VoiceSettingsPatch(wit="extra"))
    assert await svc.wit_for(UID) == "extra"
    assert (await svc.view(UID)).settings.wit == "extra"


# ---- review item 5: the view never waits long for Google's voice list --------------------------


async def test_the_view_waits_at_most_briefly_for_googles_voice_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.voice.service as service_module

    assert service_module.VOICE_LIST_WAIT_S <= 2.0
    monkeypatch.setattr(service_module, "VOICE_LIST_WAIT_S", 0.05)
    g = GoogleScript()
    answer = g.routes["/v1/voices"]

    async def slow_list(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)
        return answer(request)

    g.routes["/v1/voices"] = slow_list  # type: ignore[assignment]
    r = Rig()
    r.svc = _with_engines(r, VoiceEngines(tts=GoogleTTS(g.client(), FakeTokens()), stt=r.stt))
    view = await asyncio.wait_for(r.svc.view(UID), 0.25)
    # availability unknown: the catalogue is listed, nothing hidden
    assert len(view.voices) == 6 and all(v.available for v in view.voices)
    await asyncio.sleep(0.35)  # the one list request finished in the background …
    view = await asyncio.wait_for(r.svc.view(UID), 0.25)
    avail = {v.id: v.available for v in view.voices}
    # … and the adapter's 24 h cache now answers at once: Google lists Algieba and Studio-B
    assert avail[DEFAULT_VOICE] is True and avail["en-GB-Chirp3-HD-Charon"] is False
    assert len(g.requests) == 1


async def test_concurrent_views_share_one_voice_list_request() -> None:
    r = Rig()
    r.tts.voices_delay = 0.05
    await asyncio.gather(*(r.svc.view(UID) for _ in range(4)))
    assert r.tts.voice_lists == 1


async def test_closing_the_service_closes_the_credentials_transport() -> None:
    r = Rig()
    tokens = r.svc.engines.tokens  # type: ignore[union-attr]
    await r.svc.aclose()
    assert tokens.closed == 1  # type: ignore[union-attr]
