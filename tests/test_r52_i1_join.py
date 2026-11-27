# tests/test_r52_i1_join.py -- R5.2 I1: "Your voice" wired on the app (docs/plans/r5-2-integration/
# I1-NOTES.md). The slots (voice_laptop, voice_profiles, voice_wakeword, voice_profile_api) on the
# live app; the kit off without its address and key; R18's "laptop" option and Vitals' engine line
# from the same kit; V3's privacy rows; the delete route's wake-word choice; the session's Google
# comparison never routed to the laptop or corrected; the kit's server on V4's wake word; the
# wake-word eval in CI; the deploy script's address rule.
from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from billing_fakes import NOW, Clock, billing, registry
from httpx import ASGITransport, AsyncClient
from kit_fakes import make_service
from kit_fakes import pcm as kit_pcm
from pydantic import SecretStr
from r52_v3_fakes import pcm, wav
from voice_fakes import FakeSTT, FakeTokens, FakeTTS

from jarvis.api import create_app
from jarvis.api.r18_wiring import _SpeechFactory
from jarvis.api.r52_wiring import calls_laptop
from jarvis.api.selfcheck_wiring import vitals_sources
from jarvis.calls.models import SpeechOption
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.localspeech import protocol as p
from jarvis.localspeech.kitconfig import KitConfig
from jarvis.localspeech.wakejoin import KEY_FILE, FileSealer, kit_wakeword
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.calls_bridge import LaptopCallVoice, LaptopHearing
from jarvis.voice.catalogue import PriceList
from jarvis.voice.laptop import LaptopVoice
from jarvis.voice.profile import Correction, ListenEngine, VoiceProfile
from jarvis.voice.profile_store import DocProfileStore, MemoryProfileStore
from jarvis.voice.service import VoiceEngines, VoiceService
from jarvis.voice.session_api import ServiceGoogle, SessionApi
from jarvis.voice.session_privacy import SOURCE_IDS
from jarvis.voice.settings import VoiceSettingsStore
from jarvis.voice.wakeword_api import WakewordHandlers

ROOT = Path(__file__).resolve().parents[1]
H = {"X-Requested-With": "JARVIS"}
P = "/v1/voice/profile"
KIT_URL = "https://my-laptop.tail1234.ts.net:10000"
KIT_KEY = SecretStr("k" * 43)  # a test key, never a real one


async def _lifespan(s: Settings) -> AsyncIterator[Any]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def wired(settings: Settings) -> AsyncIterator[Any]:
    async for app in _lifespan(settings):
        yield app


@pytest.fixture
async def with_kit(settings: Settings) -> AsyncIterator[Any]:
    s = settings.model_copy(update={"local_speech_url": KIT_URL, "local_speech_key": KIT_KEY})
    async for app in _lifespan(s):
        yield app


# ---- the slots -----------------------------------------------------------------------------------
async def test_every_r52_slot_is_wired_and_the_kit_is_off_without_its_address(wired: Any) -> None:
    st = wired.state
    assert isinstance(st.voice_laptop, LaptopVoice) and st.voice_laptop.kit is None
    assert isinstance(st.voice_profiles, DocProfileStore)
    assert isinstance(st.voice_wakeword, WakewordHandlers)
    assert isinstance(st.voice_profile_api, SessionApi)
    assert st.voice.route.laptop is st.voice_laptop and st.voice.route.profiles is st.voice_profiles
    async with AsyncClient(transport=ASGITransport(app=wired), base_url="http://test") as c:
        laptop = await c.get(f"{P}/laptop", headers=H)
        wake = await c.get(f"{P}/wakeword", headers=H)
        profile = await c.get(P, headers=H)
        session = await c.get(f"{P}/session", headers=H)
    assert laptop.status_code == 200 and laptop.json()["state"] == "off"
    assert wake.status_code == 200 and wake.json()["available"] is False
    assert profile.status_code == 200 and session.status_code == 200
    assert laptop.headers["cache-control"] == "no-store"


async def test_the_profile_switched_off_leaves_the_slots_empty(settings: Settings) -> None:
    async for app in _lifespan(settings.model_copy(update={"voice_profile_enabled": False})):
        st = app.state
        assert st.voice_profile_api is None and st.voice_wakeword is None
        assert st.voice.route.profiles is None  # the usual listening order
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            got = await c.get(P, headers=H)
        assert got.status_code == 503 and got.json()["error"] == "voice_profile_off"


async def test_one_kit_client_serves_voice_calls_the_session_and_the_wake_word(
    with_kit: Any,
) -> None:
    st = with_kit.state
    kit = st.voice_laptop.kit
    assert kit is not None and "tailscale" in repr(kit) and "my-laptop" not in repr(kit)
    hearing, voice = calls_laptop(with_kit)
    assert isinstance(hearing, LaptopHearing) and isinstance(voice, LaptopCallVoice)
    assert st.voice_profile_api.s.p.kit is kit  # V3's session
    assert st.voice_wakeword._kit is kit  # V4's wake word
    assert vitals_sources(with_kit).voice is st.voice_laptop  # Vitals' engine line, ₹0


async def test_r18s_speech_options_list_the_laptop_only_with_the_kit(
    wired: Any, with_kit: Any
) -> None:
    async with httpx.AsyncClient() as http:
        for app, has in ((wired, False), (with_kit, True)):
            store: Any = None  # read only when Sarvam is asked about, never here
            factory = _SpeechFactory(app, app.state.settings, store, http)
            options = factory.options(SpeechMeter(app.state.billing, "u_owner"))
            assert (SpeechOption.LAPTOP in options.hearing) is has
            assert (SpeechOption.LAPTOP in options.voices) is has
            assert (SpeechOption.LAPTOP in options.missing) is not has


async def test_v3s_privacy_rows_are_on_the_dashboard(wired: Any) -> None:
    ids = wired.state.privacy.registry.ids()
    assert set(SOURCE_IDS) <= set(ids)
    assert ids.index("voice_profile") > ids.index("voice_phrases")  # after R5's words row


async def test_the_speaker_checks_model_route_is_mounted(wired: Any) -> None:
    url = wired.url_path_for("speaker_model", release="spk-1", name="model.onnx")
    assert url == "/static/vendor/speaker/spk-1/model.onnx"
    async with AsyncClient(transport=ASGITransport(app=wired), base_url="http://test") as c:
        got = await c.get(url)
    assert got.status_code == 404  # no model is pinned yet: the console keeps today's barge-in


# ---- the delete route's wake-word choice -------------------------------------------------------
class _Api:
    def __init__(self) -> None:
        self.asked: list[bool] = []

    async def delete_recordings(self, uid: str, *, wakeword: bool = False) -> dict[str, Any]:
        self.asked.append(wakeword)
        return {"clips": 0, "wakeword_files": int(wakeword)}


async def test_delete_my_recordings_passes_the_wake_word_choice_and_nothing_else(
    wired: Any,
) -> None:
    api = _Api()
    wired.state.voice_profile_api = api
    url = f"{P}/recordings/delete"
    async with AsyncClient(transport=ASGITransport(app=wired), base_url="http://test") as c:
        both = await c.post(url, json={"confirm": "DELETE", "wakeword": True}, headers=H)
        only = await c.post(url, json={"confirm": "DELETE"}, headers=H)
        odd = await c.post(url, json={"confirm": "DELETE", "wakeword": "yes"}, headers=H)
        extra = await c.post(url, json={"confirm": "DELETE", "all": True}, headers=H)
    assert both.status_code == 200 and both.json()["wakeword_files"] == 1
    assert only.status_code == 200 and api.asked == [True, False]
    assert odd.status_code == 422 and extra.status_code == 422


# ---- the comparison is Google's alone ------------------------------------------------------
class _ReadyLaptop:
    """A laptop that is always ready and would hear "LAPTOP": the comparison must never ask it."""

    kit = object()
    asked = 0

    async def ready(self, kind: Any, slot: Any = None) -> bool:
        return True

    def note_served(self, kind: Any, engine: str) -> None: ...

    async def aclose(self) -> None: ...


async def test_the_sessions_google_comparison_never_goes_to_the_laptop_or_is_corrected() -> None:
    docs, stt = MemoryDocs(), FakeSTT(text="jarvis lights")
    profiles = MemoryProfileStore()
    fix = Correction(heard="jarvis", meant="the hall")
    await profiles.save(
        "u_owner",
        VoiceProfile(chosen=ListenEngine.WHISPER_SMALL, corrections=(fix,), corrections_on=True),
    )
    prices = PriceList.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    voice = VoiceService(
        store=VoiceSettingsStore(docs),
        billing=billing(registry(), docs=docs, clock=Clock(NOW)),
        prices=prices,
        engines=VoiceEngines(tts=FakeTTS(), stt=stt, tokens=FakeTokens()),
        language="en-IN",
        honorific="Sir",
        laptop=_ReadyLaptop(),  # type: ignore[arg-type]
        profiles=profiles,
    )

    async def never(*_: Any, **__: Any) -> Any:
        raise AssertionError("the comparison asked the laptop")

    voice.route.listen = never  # type: ignore[method-assign]
    heard = await ServiceGoogle(voice).hear("u_owner", wav(pcm(1)), free_only=False)
    assert heard.text == "jarvis lights"  # Google's words, uncorrected
    assert len(stt.calls) == 1


# ---- the kit's server on V4's wake word ----------------------------------------------------
def test_the_wake_word_files_have_their_own_key(tmp_path: Path) -> None:
    sealer = FileSealer(tmp_path / KEY_FILE)
    sealed = sealer.seal(b'{"weights": [1, 2]}')
    assert sealer.unseal(sealed) == b'{"weights": [1, 2]}' and b"weights" not in sealed
    assert FileSealer(tmp_path / KEY_FILE).unseal(sealed) == b'{"weights": [1, 2]}'  # kept key
    with pytest.raises(ValueError):
        FileSealer(tmp_path / "other.secret").unseal(sealed)
    with pytest.raises(ValueError):
        sealer.unseal(b"JVW1" + bytes(40))


async def test_the_kit_refuses_too_few_wake_clips_before_a_job_and_keeps_files_apart(
    tmp_path: Path,
) -> None:
    cfg = KitConfig(data_dir=tmp_path, manifest=tmp_path / "models.json")
    service, _ = make_service(tmp_path)
    service.wakeword = kit_wakeword(cfg)
    sid = "vs_0123456789ab"
    for i in range(3):
        await service.put_clip(
            p.ClipIn(
                session_id=sid,
                prompt_id=f"wake_{i}",
                kind=p.PromptKind.WAKE,
                held_out=False,
                audio=p.encode_pcm(kit_pcm(1.0, i + 1)),
            )
        )
    with pytest.raises(p.KitRefused) as few:
        await service.wake_train(p.WakeTrainIn(artifact=p.WakeArtifact.VERIFIER, session_id=sid))
    assert few.value.code == "not_found" and "at least 10" in few.value.words
    status = await service.wake_status()
    assert status.verifier is None and status.jobs == ()  # nothing was queued
    gone = await service.delete(p.DeleteIn(session_id=None, wakeword=True))
    assert (gone.clips, gone.wakeword_files) == (3, 0)
    assert (tmp_path / "wakeword").exists() is False or not any((tmp_path / "wakeword").iterdir())


# ---- CI and the deploy script ------------------------------------------------------------------
def test_the_mock_evals_run_the_wake_word_suite() -> None:
    assert '"wakeword" / "run.py"' in (ROOT / "evals" / "run_all_mock.py").read_text()


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (KIT_URL, True),
        ("https://my-laptop.tail1234.ts.net", True),
        ("https://my-laptop.tail1234.ts.net:8443/", True),
        ("http://my-laptop.tail1234.ts.net:10000", False),
        ("https://my-laptop.tail1234.ts.net:1234", False),
        ("https://evil.example.com:10000", False),
        ("https://1.2.3.4:10000", False),
        ("https://my-laptop.tail1234.ts.net:10000/v1", False),
    ],
)
def test_the_deploy_script_takes_only_the_kits_tailscale_https_address(url: str, ok: bool) -> None:
    script = (ROOT / "deploy" / "cloudrun.sh").read_text(encoding="utf-8")
    start = script.index("ls_url_ok() {")
    fn = script[start : script.index("\n}\n", start) + 3]
    got = subprocess.run(["bash", "-c", f'{fn}\nls_url_ok "$1"', "_", url], check=False)
    assert (got.returncode == 0) is ok


def test_the_deploy_script_grants_and_mounts_the_kits_key() -> None:
    script = (ROOT / "deploy" / "cloudrun.sh").read_text(encoding="utf-8")
    assert "jarvis-telegram-webhook-secret jarvis-local-speech-key; do" in script
    assert script.count("${LS_SECRET}${WEB_SECRET}JARVIS_TOKEN_KEY=jarvis-token-key:latest") == 2
    assert 'INFRA_ENV="${INFRA_ENV},${LS_ENV}"' in script
