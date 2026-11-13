# tests/test_r11_1_b_voice.py -- R11.1 Part B (plan D9): both recognisers are asked for three
# alternatives, and the cloud recogniser gets per-turn hints (the names of the owner's waiting and
# attached files as they are said, his own turns' nouns) between the base list and his own "Words
# to recognise". The language stays en-IN, nothing new is a setting, and no hint is ever logged.
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from billing_fakes import NOW, UID, Clock, billing, registry
from httpx import ASGITransport, AsyncClient
from voice_fakes import FakeSTT, FakeTokens, FakeTTS, GoogleScript, pcm, wav

from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import PriceList
from jarvis.voice.commands import BASE_PHRASES
from jarvis.voice.google_cloud import MAX_ALTERNATIVES, GoogleSTT
from jarvis.voice.ports import Transcript, VoiceRejected
from jarvis.voice.service import VoiceEngines, VoiceService
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore

STATIC = Path(__file__).resolve().parents[1] / "src/jarvis/api/static"
PRICES = PriceList.from_settings(Settings(_env_file=None))
NEEDLE = "Zyxwvut plan"  # a made-up file stem that must never reach a log


# ---- three alternatives --------------------------------------------------------------------------


async def test_google_is_asked_for_three_alternatives_in_en_in() -> None:
    g = GoogleScript()
    await GoogleSTT(g.client(), FakeTokens()).recognize(
        pcm(0.5), sample_rate=16_000, language="en-IN", phrases=("JARVIS",)
    )
    config = g.body()["config"]
    assert config["maxAlternatives"] == MAX_ALTERNATIVES == 3 and config["languageCode"] == "en-IN"


async def test_the_other_alternatives_come_back_as_whole_sentences() -> None:
    g = GoogleScript()
    g.routes["/v1/speech:recognize"] = lambda r: httpx.Response(
        200,
        json={
            "results": [
                {
                    "alternatives": [
                        {"transcript": "add D csb file", "confidence": 0.71},
                        {"transcript": "add the CSV file"},
                        {"transcript": "at the CSB file"},
                        {"transcript": "a fourth one that is ignored"},
                    ]
                },
                {
                    "alternatives": [
                        {"transcript": " to my calendar"},
                        {"transcript": " Tu my calender"},
                    ]
                },
            ],
            "totalBilledTime": "3s",
        },
    )
    t = await GoogleSTT(g.client(), FakeTokens()).recognize(
        pcm(0.5), sample_rate=16_000, language="en-IN", phrases=()
    )
    assert t.text == "add D csb file to my calendar" and t.confidence == 0.71
    assert t.alternatives == ("add the CSV file Tu my calender", "at the CSB file to my calendar")


async def test_one_alternative_only_means_no_others() -> None:
    g = GoogleScript()
    t = await GoogleSTT(g.client(), FakeTokens()).recognize(
        pcm(0.5), sample_rate=16_000, language="en-IN", phrases=()
    )
    assert t.text == "hello jarvis" and t.alternatives == ()
    assert Transcript("x", None, None, None).alternatives == ()  # older callers still build one


# ---- per-turn hints in the service ---------------------------------------------------------------


class Rig:
    def __init__(self, stt: FakeSTT | None = None) -> None:
        self.docs = MemoryDocs()
        self.stt = stt or FakeSTT()
        self.svc = VoiceService(
            store=VoiceSettingsStore(self.docs),
            billing=billing(registry(), docs=self.docs, clock=Clock(NOW)),
            prices=PRICES,
            engines=VoiceEngines(tts=FakeTTS(), stt=self.stt, tokens=FakeTokens()),
            language="en-IN",
            honorific="Sir",
        )

    async def words(self, *words: str) -> None:
        await self.svc.update_settings(
            UID, VoiceSettingsPatch.model_validate({"phrases": list(words)})
        )

    @property
    def sent(self) -> tuple[str, ...]:
        return self.stt.calls[-1]["phrases"]


async def test_turn_hints_sit_between_the_base_list_and_the_owners_own_words() -> None:
    r = Rig()
    await r.words("Trivandrum", "Kochi")
    await r.svc.transcribe(UID, wav(1.0), turn_hints=("study plan", "CSV", "Kerala"))
    base = len(dict.fromkeys(w.casefold() for w in (*BASE_PHRASES, "Sir")))
    assert r.sent[base:] == ("study plan", "CSV", "Kerala", "Trivandrum", "Kochi")
    assert r.sent[0] == "JARVIS" and r.stt.calls[-1]["language"] == "en-IN"


async def test_hints_never_repeat_a_word_already_in_the_list() -> None:
    r = Rig()
    await r.words("Kerala")
    await r.svc.transcribe(UID, wav(1.0), turn_hints=("jarvis", "kerala", "CSV", "csv"))
    names = [w.casefold() for w in r.sent]
    assert (
        len(names) == len(set(names))
        and names.count("kerala") == 1
        and names[-2:] == ["csv", "kerala"]
    )


async def test_the_transcript_carries_the_alternatives_to_the_console() -> None:
    class Three(FakeSTT):
        async def recognize(self, pcm: bytes, **kw: Any) -> Transcript:  # type: ignore[override]
            await super().recognize(pcm, **kw)
            return Transcript(
                "add D csb file", 0.64, 1.0, "en-in", ("add the CSV file", "at the CSB file")
            )

    view = await Rig(Three()).svc.transcribe(UID, wav(1.0))
    assert view.text == "add D csb file" and view.confidence == 0.64
    assert view.alternatives == ["add the CSV file", "at the CSB file"]


class RejectsHints(FakeSTT):
    """Google refuses any request that carries a word outside the base list."""

    def __init__(self, base: tuple[str, ...]) -> None:
        super().__init__()
        self.base = {w.casefold() for w in base}

    async def recognize(self, pcm: bytes, **kw: Any) -> Transcript:  # type: ignore[override]
        if any(w.casefold() not in self.base for w in kw["phrases"]):
            self.calls.append({"phrases": kw["phrases"]})
            raise VoiceRejected("Google rejected that voice or text.")
        return await super().recognize(pcm, **kw)


async def test_a_refused_hint_is_retried_once_with_the_base_list_alone(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = Rig(RejectsHints(Rig().svc.base_phrases))
    with caplog.at_level(logging.DEBUG):
        view = await r.svc.transcribe(UID, wav(1.0), turn_hints=(NEEDLE,))
    assert view.text and len(r.stt.calls) == 2
    assert NEEDLE in r.stt.calls[0]["phrases"] and NEEDLE not in r.stt.calls[1]["phrases"]
    assert NEEDLE not in caplog.text


# ---- through the API: the hints come from the owner's own files and turns ------------------------


@pytest.fixture
async def vc() -> AsyncIterator[AsyncClient]:
    s = Settings(_env_file=None, env="dev", auth_mode=AuthMode.TOKEN, voice_cloud=True)
    app = create_app(
        s,
        provider=MockProvider(),
        store=InMemorySessionStore(),
        voice_engines=VoiceEngines(tts=FakeTTS(), stt=FakeSTT(), tokens=FakeTokens()),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def attach(c: AsyncClient, name: str, data: bytes = b"Session,Topic\n1,Made-up\n") -> str:
    r = await c.post(
        "/v1/attachments",
        content=data,
        headers={"X-Jarvis-Filename": name, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def sent(c: AsyncClient) -> tuple[str, ...]:
    return c.app.state.voice.engines.stt.calls[-1]["phrases"]  # type: ignore[attr-defined,no-any-return]


async def test_a_waiting_files_name_reaches_the_recogniser_as_it_is_said(
    vc: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    await attach(vc, "Zyxwvut-plan.csv")
    await vc.put("/v1/voice/settings", json={"phrases": ["Trivandrum"]})
    with caplog.at_level(logging.DEBUG):
        r = await vc.post(
            "/v1/voice/transcribe", content=wav(1.0), headers={"Content-Type": "audio/wav"}
        )
    assert r.status_code == 200 and r.json()["alternatives"] == []
    phrases = sent(vc)
    assert NEEDLE in phrases and "CSV" in phrases and phrases[-1] == "Trivandrum"
    assert phrases.index("mic off") < phrases.index(NEEDLE) < phrases.index("Trivandrum")
    assert "Zyxwvut" not in caplog.text  # a file's name is never logged


async def test_the_conversations_own_nouns_and_attached_files_are_hints_for_that_conversation(
    vc: AsyncClient,
) -> None:
    aid = await attach(vc, "kerala-registry.csv")
    r = await vc.post(
        "/v1/chat", json={"message": "Plan the Quillon review from this", "attachments": [aid]}
    )
    sid = r.json()["session_id"]
    await vc.post("/v1/chat", json={"message": "the Quillon review again", "session_id": sid})
    await vc.post(
        "/v1/voice/transcribe",
        content=wav(1.0),
        headers={"Content-Type": "audio/wav", "X-Jarvis-Session": sid},
    )
    here = sent(vc)
    assert "kerala registry" in here and "Quillon" in here and "review" in here
    await vc.post("/v1/voice/transcribe", content=wav(1.0), headers={"Content-Type": "audio/wav"})
    assert "Quillon" not in sent(vc) and "kerala registry" not in sent(vc)  # another conversation
    r = await vc.get("/v1/input/hints", params={"session_id": sid})
    assert r.status_code == 200 and "Quillon" in r.json()["hints"]
    assert (await vc.get("/v1/input/hints")).json()["hints"] == []


async def test_no_hints_at_all_when_the_owner_sets_the_count_to_zero() -> None:
    s = Settings(
        _env_file=None, env="dev", auth_mode=AuthMode.TOKEN, voice_cloud=True, voice_hint_words=0
    )
    app = create_app(
        s,
        provider=MockProvider(),
        store=InMemorySessionStore(),
        voice_engines=VoiceEngines(tts=FakeTTS(), stt=FakeSTT(), tokens=FakeTokens()),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            await attach(c, "Zyxwvut-plan.csv")
            await c.post(
                "/v1/voice/transcribe", content=wav(1.0), headers={"Content-Type": "audio/wav"}
            )
            assert NEEDLE not in sent(c)


async def test_a_bad_session_header_is_ignored_not_an_error(vc: AsyncClient) -> None:
    for sid in ("x" * 200, "../../etc", "sess_nope"):
        r = await vc.post(
            "/v1/voice/transcribe",
            content=wav(1.0),
            headers={"Content-Type": "audio/wav", "X-Jarvis-Session": sid},
        )
        assert r.status_code == 200


# ---- the browser recogniser (static checks; the browser test drives it) -------------------------


def test_the_browser_recogniser_asks_for_three_and_keeps_the_owners_language() -> None:
    loop = (STATIC / "console-voice-loop-browser.js").read_text(encoding="utf-8")
    assert "rec.maxAlternatives = 3" in loop and "rec.maxAlternatives = 1" not in loop
    assert "rec.lang = V.language()" in loop  # en-IN from the server's setting: no new setting
    voice = (STATIC / "console-voice.js").read_text(encoding="utf-8")
    assert "'en-IN'" in voice
    mic = (STATIC / "console-voice-mic.js").read_text(encoding="utf-8")
    assert "alternatives" in mic and "'X-Jarvis-Session'" in mic
    phrases = (STATIC / "console-voice-phrases.js").read_text(encoding="utf-8")
    assert "turnHints().concat(list())" in phrases and "F.hints()" in phrases
    files = (STATIC / "console-r111-files.js").read_text(encoding="utf-8")
    assert "'/v1/input/hints'" in files and "hints: () => turnHints.slice()" in files
