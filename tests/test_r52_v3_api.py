# tests/test_r52_v3_api.py -- R5.2 V3: `ProfileApi` behind I0's /v1/voice/profile routes (strict
# bodies, plain views, no-store), and the production parts: Google through the voice service
# (his words, free-only inside the free minutes), his words through R5's one list, R18's
# normaliser found when the app is built.
from __future__ import annotations

import base64
import importlib.util
from typing import Any

import pytest
from billing_fakes import NOW, Clock, billing, put_raw, registry
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from r52_v3_fakes import FakeGoogle, FakeWords, normalise, pcm, sha, wav
from voice_fakes import FakeSTT, FakeTokens, FakeTTS

from jarvis.api import voice_profile_routes as vr
from jarvis.config import Settings
from jarvis.localspeech.memory import MemoryKit
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import PriceList
from jarvis.voice.profile_store import MemoryProfileStore
from jarvis.voice.service import VoiceEngines, VoiceService
from jarvis.voice.session import SessionParts, VoiceSessions
from jarvis.voice.session_api import (
    ServiceGoogle,
    SessionApi,
    SettingsWords,
    build_profile_api,
    r18_normalise,
)
from jarvis.voice.session_store import MemorySessionStore
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
P = "/v1/voice/profile"


class Rig:
    def __init__(self, settings: Settings, **google: Any) -> None:
        self.s = settings.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)})
        self.kit = MemoryKit()
        self.google = FakeGoogle(**google)
        self.words = FakeWords(["Zephyrine"])
        parts = SessionParts(
            kit=self.kit,
            profiles=MemoryProfileStore(),
            sessions=MemorySessionStore(),
            google=self.google,
            words=self.words,
            normalise=normalise,
        )
        self.app = FastAPI()
        self.app.state.settings = self.s
        self.app.state.voice_profile_api = SessionApi(VoiceSessions(parts))
        vr.install_voice_profile_routes(self.app)


def _clip(i: int, text: str, kit: MemoryKit, google: FakeGoogle) -> dict[str, Any]:
    data = pcm(i)
    kit.heard[sha(data)] = text
    google.heard[sha(data)] = text
    return {"audio": base64.b64encode(wav(data)).decode(), "browser_heard": text}


def test_the_profile_and_an_empty_session_before_anything_is_recorded(settings: Settings) -> None:
    rig = Rig(settings)
    with TestClient(rig.app) as c:
        prof = c.get(P, headers=AUTH)
        sess = c.get(f"{P}/session", headers=AUTH)
    assert prof.status_code == 200 and prof.headers["cache-control"] == "no-store"
    body = prof.json()
    assert body["state"] == "none" and body["chosen"] is None and body["laptop_ready"] is True
    assert body["order"] == ["laptop-whisper-small", "google", "browser"]
    assert body["order_labels"][0] == "Laptop: Whisper small"
    view = sess.json()
    assert view["state"] == "none" and len(view["blocks"]) == 4 and view["minutes"] == 20
    assert view["compare"]["mode"] == "free" and "₹0" in view["compare"]["words"]


def test_a_whole_session_through_the_routes(settings: Settings) -> None:
    rig = Rig(settings)
    with TestClient(rig.app) as c:
        started = c.post(f"{P}/session/start", json={"words": ["Quillon"]}, headers=AUTH).json()
        assert started["state"] == "recording" and started["total"] == 120
        first = started["prompts"][0]
        assert set(first) == {"id", "block", "kind", "text", "how", "compare", "wake"}
        for i, p in enumerate(started["prompts"]):
            put = c.put(
                f"{P}/session/clips/{p['id']}",
                json=_clip(i, p["text"], rig.kit, rig.google),
                headers=AUTH,
            )
            assert put.status_code == 200, put.text
        assert put.json()["done"] == 120 and put.json()["next"] is None
        assert "browser_heard" not in put.json() and "text" not in put.json()
        scored = c.post(f"{P}/session/score", json={}, headers=AUTH).json()
        assert scored["state"] == "done" and scored["words_added"] == ["Quillon"]
        profile = scored["profile"]
        assert profile["chosen"] == "laptop-whisper-small" and profile["meets_bar"] is True
        assert {r["engine"] for r in profile["ranking"]} == {
            "laptop-whisper-small",
            "google",
            "browser",
        }
        again = c.get(f"{P}/session/results", headers=AUTH).json()
        assert again["profile"]["ranking"] == profile["ranking"]
        assert c.post(f"{P}/recheck", json={}, headers=AUTH).json()["state"] == "done"
        changed = c.put(P, json={"chosen": "google", "corrections_on": False}, headers=AUTH)
        assert changed.json()["chosen"] == "google" and changed.json()["corrections_on"] is False
        gone = c.post(f"{P}/recordings/delete", json={"confirm": "DELETE"}, headers=AUTH)
        assert gone.json() == {
            "clips": 120,
            "wakeword_files": 0,
            "words": "Deleted 120 recordings from your laptop.",
        }
        assert c.get(f"{P}/session", headers=AUTH).json()["state"] == "none"
        assert c.get(P, headers=AUTH).json()["chosen"] == "google"  # results stay


def test_the_rupee_question_and_his_typed_yes(settings: Settings) -> None:
    rig = Rig(settings, free_left=0.0)
    with TestClient(rig.app) as c:
        asked = c.post(f"{P}/session/start", json={}, headers=AUTH)
        assert asked.status_code == 402 and asked.json()["error"] == "needs_yes"
        assert "at most about ₹46" in asked.json()["detail"]
        sess = c.get(f"{P}/session", headers=AUTH).json()
        assert sess["compare"]["mode"] == "needs_yes" and sess["compare"]["yes_word"] == "YES"
        lower = c.post(f"{P}/session/start", json={"yes": "yes"}, headers=AUTH)
        assert lower.status_code == 422 and lower.json()["error"] == "type_yes"
        ok = c.post(f"{P}/session/start", json={"yes": "YES"}, headers=AUTH).json()
        assert ok["compare"]["mode"] == "yes" and "at most about ₹46" in ok["compare"]["words"]


@pytest.mark.parametrize(
    ("path", "method", "body"),
    [
        (f"{P}/session/start", "POST", {"surprise": 1}),
        (f"{P}/session/start", "POST", {"words": ["#!"]}),
        (f"{P}/session/start", "POST", {"words": ["x"] * 21}),
        (f"{P}/session/score", "POST", {"now": True}),
        (P, "PUT", {"chosen": "a-robot"}),
    ],
)
def test_bodies_are_strict_and_never_echoed(
    settings: Settings, path: str, method: str, body: dict[str, Any]
) -> None:
    rig = Rig(settings)
    with TestClient(rig.app) as c:
        got = c.request(method, path, json=body, headers=AUTH)
    assert got.status_code == 422, got.text
    assert "surprise" not in got.text and "#!" not in got.text and "a-robot" not in got.text


def test_clip_errors_are_plain(settings: Settings) -> None:
    rig = Rig(settings)
    with TestClient(rig.app) as c:
        none = c.put(f"{P}/session/clips/b1_comm_01", json={"audio": "AAAA"}, headers=AUTH)
        assert none.status_code == 409 and none.json()["error"] == "no_session"
        c.post(f"{P}/session/start", json={}, headers=AUTH)
        bad = c.put(f"{P}/session/clips/b1_comm_01", json={"audio": "%%%"}, headers=AUTH)
        assert bad.status_code == 422 and bad.json()["error"] == "bad_audio"
        extra = c.put(f"{P}/session/clips/b1_comm_01", json={"audio": "AAAA", "x": 1}, headers=AUTH)
        assert extra.json()["error"] == "input_rejected"
        few = c.post(f"{P}/session/score", json={}, headers=AUTH)
        assert few.status_code == 409 and few.json()["error"] == "too_few"
        rig.kit.down = "offline"
        off = c.post(f"{P}/recordings/delete", json={"confirm": "DELETE"}, headers=AUTH)
        assert off.status_code == 503 and off.json()["error"] == "laptop_unavailable"


# ---- the production parts ------------------------------------------------------------------------
PRICES = PriceList.from_settings(Settings(_env_file=None))


def _voice(docs: MemoryDocs, stt: FakeSTT, *, engines: bool = True) -> VoiceService:
    return VoiceService(
        store=VoiceSettingsStore(docs),
        billing=billing(registry(), docs=docs, clock=Clock(NOW)),
        prices=PRICES,
        engines=VoiceEngines(tts=FakeTTS(), stt=stt, tokens=FakeTokens()) if engines else None,
        language="en-IN",
        honorific="Sir",
    )


async def test_google_is_the_voice_services_with_his_words_and_free_only() -> None:
    docs, stt = MemoryDocs(), FakeSTT(text="mic off")
    voice = _voice(docs, stt)
    await voice.update_settings("u_owner", VoiceSettingsPatch(phrases=["Zephyrine"]))
    ear = ServiceGoogle(voice)
    assert ear.ready() and await ear.free_seconds_left() == PRICES.stt.free_units
    assert await ear.inr_per_minute() == pytest.approx(2.2858, abs=0.001)
    heard = await ear.hear("u_owner", wav(pcm(1)), free_only=True)
    assert heard.text == "mic off" and heard.ms is not None
    assert "Zephyrine" in stt.calls[-1]["phrases"]
    assert await ear.free_seconds_left() == PRICES.stt.free_units - 15  # a whole 15 s step held
    await put_raw(docs, "jarvis_allowance/2026-11", {"units": {"stt_seconds": 3_239.0}})
    assert await ear.free_seconds_left() == 1.0
    assert not ServiceGoogle(_voice(docs, stt, engines=False)).ready()


async def test_his_words_are_r5s_one_list_cleaned_and_capped() -> None:
    docs = MemoryDocs()
    voice = _voice(docs, FakeSTT())
    words = SettingsWords(voice)
    await voice.update_settings(
        "u_owner", VoiceSettingsPatch(phrases=[f"w{i}a" for i in range(48)])
    )
    added = await words.add("u_owner", ("Quillon", "quillon", "#!", "W0A", "Zeph", "Extra"))
    assert added == ("Quillon", "Zeph")  # deduped, cleaned, at most 50
    assert len(await words.read("u_owner")) == 50


def test_r18s_normaliser_is_found_when_merged() -> None:
    if importlib.util.find_spec("jarvis.calls.langcheck") is None:
        with pytest.raises(RuntimeError, match="not merged"):
            r18_normalise()
    else:
        assert r18_normalise()("Hello, World!") == "hello world"


def test_build_profile_api_offers_no_kit_unless_it_is_configured(settings: Settings) -> None:
    docs = MemoryDocs()
    voice = _voice(docs, FakeSTT())
    api = build_profile_api(
        settings,
        docs=docs,
        voice=voice,
        profiles=MemoryProfileStore(),
        kit=MemoryKit(),
        normalise=normalise,
    )
    assert api.s.p.kit is None and api.s.p.compare_minutes == 20
    on = settings.model_copy(
        update={
            "local_speech_url": "https://my-laptop.tail1234.ts.net:8443",
            "local_speech_key": SecretStr("k" * 32),
        }
    )
    kit = MemoryKit()
    api = build_profile_api(
        on, docs=docs, voice=voice, profiles=MemoryProfileStore(), kit=kit, normalise=normalise
    )
    assert api.s.p.kit is kit
