# tests/test_voice_phrases.py - R5 D16 (docs/plans/r5-voice.md): the owner's "words to recognise".
# Settings validation (apply / decode), what transcribe() sends to Google, the API contract, the
# audit entry (a count, never the words), the privacy source and the no-logging rule.
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from billing_fakes import NOW, UID, Clock, billing, registry
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from voice_fakes import FakeSTT, FakeTokens, FakeTTS, wav

from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import args_hash
from jarvis.voice.catalogue import PriceList
from jarvis.voice.commands import BASE_PHRASES
from jarvis.voice.ports import VoiceRejected
from jarvis.voice.service import VoiceEngines, VoiceService
from jarvis.voice.settings import (
    PHRASE_CHARS,
    PHRASE_ITEMS,
    VoiceSettings,
    VoiceSettingsPatch,
    VoiceSettingsStore,
    apply,
    clean_phrase,
    decode,
)

PATH = f"jarvis_voice_settings/{UID}"
PRICES = PriceList.from_settings(Settings(_env_file=None))
NEEDLE = "Zyxwvut Quillon"  # a made-up word that must never reach a log or an audit entry


def patch(*words: object) -> VoiceSettingsPatch:
    return VoiceSettingsPatch.model_validate({"phrases": list(words)})


def fifty(n: int = 50) -> list[str]:
    return [f"Word{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(n)]


# ---- clean_phrase ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Thiruvananthapuram", "Thiruvananthapuram"),
        ("  Kerala   State  IT\tMission \n", "Kerala State IT Mission"),
        ("Tri​van‍drum", "Trivandrum"),  # zero-width characters are stripped
        ("Zoë", "Zoë"),  # NFC: e + combining diaeresis becomes one character
        ("O'Brien", "O'Brien"),
        ("O’Brien", "O'Brien"),  # a phone's curly apostrophe
        ("AT&T 5G-ready v2.0", "AT&T 5G-ready v2.0"),
        ("തിരുവനന്തപുരം",) * 2,
        ("a" * 40, "a" * 40),
        ("a\u0007b", "ab"),  # a control character is stripped
        ("a" * 40 + "​" * 10, "a" * 40),  # length is counted after cleaning
        ("line\nbreak ‮RTL", "line break RTL"),  # bidi override stripped
    ],
)
def test_clean_phrase_accepts_and_tidies(raw: str, clean: str) -> None:
    assert clean_phrase(raw) == clean


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "​‍",  # nothing is left after stripping
        "a" * 41,
        " ".join(["ab"] * 14),  # 41 characters
        "1234",  # needs a letter
        "- . &",  # needs a letter
        "<b>bold</b>",
        "semi;colon",
        "50% off",
        "name@host",
        "snow ☃",
        "x=y",
        "a/b",
        '"quoted"',
        "emoji \U0001f600",
    ],
)
def test_clean_phrase_rejects(raw: str) -> None:
    assert clean_phrase(raw) is None


# ---- apply / decode ---------------------------------------------------------------------------


def test_limits_are_the_plans_and_phrases_default_to_none() -> None:
    assert (PHRASE_ITEMS, PHRASE_CHARS) == (50, 40)
    assert VoiceSettings().phrases == ()


def test_a_patch_without_phrases_keeps_them_and_an_empty_list_clears_them() -> None:
    cur = VoiceSettings(phrases=("Trivandrum",))
    assert apply(cur, VoiceSettingsPatch(wit="extra")).phrases == ("Trivandrum",)
    assert apply(cur, patch()).phrases == ()


def test_apply_stores_cleaned_phrases_in_order_without_case_duplicates() -> None:
    s = apply(VoiceSettings(), patch("Trivandrum ", "Kochi", "trivandrum", "  KOCHI"))
    assert s.phrases == ("Trivandrum", "Kochi")


def test_exactly_fifty_phrases_are_accepted() -> None:
    assert len(apply(VoiceSettings(), patch(*fifty())).phrases) == 50


@pytest.mark.parametrize(
    "words",
    [
        ["a" * 41],
        ["fine", "1234"],
        ["fine", ""],
        ["fine", 7],
        ["fine", None],
        ["fine", ["nested"]],
        ["x" * 5000],
    ],
)
def test_apply_rejects_in_plain_words_and_never_echoes_the_input(words: list[Any]) -> None:
    with pytest.raises(VoiceRejected) as err:
        apply(VoiceSettings(), patch(*words))
    msg = str(err.value)
    assert msg.endswith(".") and len(msg) < 200
    for w in words:
        if isinstance(w, str) and len(w) > 4:
            assert w not in msg


def test_decode_drops_invalid_stored_phrases_one_by_one() -> None:
    doc = {"phrases": ["Trivandrum", "<script>", 5, "a" * 41, "kochi", "KOCHI", "", "ok"]}
    assert decode(doc).phrases == ("Trivandrum", "kochi", "ok")
    assert decode({"phrases": "Trivandrum"}).phrases == ()
    assert decode({"phrases": None}).phrases == ()
    assert decode({}).phrases == ()
    assert len(decode({"phrases": fifty(80)}).phrases) == 50


async def test_a_rejected_list_writes_nothing() -> None:
    docs = MemoryDocs()
    with pytest.raises(VoiceRejected):
        await VoiceSettingsStore(docs).update(UID, patch("fine", "a" * 41))
    assert await docs.get(PATH) is None


async def test_phrases_persist_as_a_list_and_read_back_cold() -> None:
    docs = MemoryDocs()
    s = await VoiceSettingsStore(docs).update(UID, patch("Trivandrum", "Kochi"))
    doc = await docs.get(PATH)
    assert doc is not None and doc["phrases"] == ["Trivandrum", "Kochi"]
    assert (await VoiceSettingsStore(docs).get(UID)).phrases == s.phrases


# ---- what transcribe() sends ------------------------------------------------------------------


class FailingStore(VoiceSettingsStore):
    def __init__(self, docs: MemoryDocs, *, delay: float = 0.0) -> None:
        super().__init__(docs)
        self.delay = delay

    async def get(self, uid: str) -> VoiceSettings:
        if self.delay:
            await asyncio.sleep(self.delay)
            return await super().get(uid)
        raise RuntimeError("storage down")


class Rig:
    def __init__(self, store: type[VoiceSettingsStore] = VoiceSettingsStore, **kw: Any) -> None:
        self.docs = MemoryDocs()
        self.stt = FakeSTT()
        self.store = store(self.docs, **kw) if kw else store(self.docs)
        self.svc = VoiceService(
            store=self.store,
            billing=billing(registry(), docs=self.docs, clock=Clock(NOW)),
            prices=PRICES,
            engines=VoiceEngines(tts=FakeTTS(), stt=self.stt, tokens=FakeTokens()),
            language="en-IN",
            honorific="Sir",
        )

    @property
    def sent(self) -> tuple[str, ...]:
        return self.stt.calls[-1]["phrases"]


def lowered(words: tuple[str, ...]) -> list[str]:
    return [w.lower() for w in words]


async def test_transcribe_sends_the_base_list_then_the_honorific_then_the_owners_words() -> None:
    r = Rig()
    await r.svc.update_settings(UID, patch("Trivandrum", "Kochi"))
    await r.svc.transcribe(UID, wav(1.0))
    assert r.sent[:2] == ("JARVIS", "Hey Jarvis")
    assert "Sir" in r.sent and "mic off" in r.sent
    assert r.sent[-2:] == ("Trivandrum", "Kochi")


async def test_the_list_has_no_case_duplicates_so_only_one_jarvis_is_sent() -> None:
    r = Rig()
    await r.svc.update_settings(UID, patch("JARVIS", "jarvis", "sir", "Kochi"))
    await r.svc.transcribe(UID, wav(1.0))
    names = lowered(r.sent)
    assert len(names) == len(set(names))
    assert names.count("jarvis") == 1 and names.count("sir") == 1
    assert "Jarvis" not in r.sent  # BASE_PHRASES holds both spellings; the first is kept
    assert r.sent[-1] == "Kochi"
    assert set(lowered(BASE_PHRASES)) <= set(names)


async def test_no_owner_words_means_the_base_hints_only() -> None:
    r = Rig()
    await r.svc.transcribe(UID, wav(1.0))
    assert lowered(r.sent) == [*dict.fromkeys(lowered((*BASE_PHRASES, "Sir")))]


async def test_an_unreadable_settings_store_gives_base_hints_and_never_fails_the_turn() -> None:
    r = Rig(FailingStore)
    t = await r.svc.transcribe(UID, wav(1.0))
    assert t.text and not t.no_speech
    assert "Sir" in r.sent and "Kochi" not in r.sent and len(r.sent) >= len(BASE_PHRASES) - 1


async def test_a_slow_settings_store_is_waited_for_at_most_a_second() -> None:
    r = Rig(FailingStore, delay=5.0)
    t = await asyncio.wait_for(r.svc.transcribe(UID, wav(1.0)), 2.5)
    assert t.text and "Sir" in r.sent


async def test_a_put_applies_to_the_next_transcription_at_once() -> None:
    r = Rig()
    await r.svc.transcribe(UID, wav(1.0))
    await r.svc.update_settings(UID, patch("Kochi"))
    await r.svc.transcribe(UID, wav(1.0))
    assert r.sent[-1] == "Kochi"


async def test_the_words_never_reach_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    r = Rig()
    with caplog.at_level(logging.DEBUG):
        await r.svc.update_settings(UID, patch(NEEDLE))
        await r.svc.transcribe(UID, wav(1.0))
        await r.svc.view(UID)
    assert NEEDLE not in caplog.text and NEEDLE.lower() not in caplog.text.lower()
    assert NEEDLE in r.sent  # ... while they do reach the engine


# ---- the API ----------------------------------------------------------------------------------


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


async def audit_entries(c: AsyncClient) -> list[Any]:
    return [e for e in (await c.app.state.gateway.audit.tail(50)).entries]  # type: ignore[attr-defined]


async def test_get_returns_the_phrases_and_their_limits(vc: AsyncClient) -> None:
    j = (await vc.get("/v1/voice")).json()
    assert j["settings"]["phrases"] == []
    assert j["phrase_limits"] == {"items": 50, "chars": 40}
    r = await vc.put("/v1/voice/settings", json={"phrases": ["Trivandrum", "Kochi"]})
    assert r.status_code == 200 and r.json()["phrases"] == ["Trivandrum", "Kochi"]
    assert (await vc.get("/v1/voice")).json()["settings"]["phrases"] == ["Trivandrum", "Kochi"]


async def test_put_without_phrases_does_not_touch_them(vc: AsyncClient) -> None:
    await vc.put("/v1/voice/settings", json={"phrases": ["Kochi"]})
    r = await vc.put("/v1/voice/settings", json={"wit": "extra"})
    assert r.json()["phrases"] == ["Kochi"]


@pytest.mark.parametrize("bad", [["a" * 41], ["1234"], ["ok", 3]])
async def test_put_rejects_bad_lists_with_a_plain_422_and_writes_nothing(
    vc: AsyncClient, bad: list[Any]
) -> None:
    await vc.put("/v1/voice/settings", json={"phrases": ["Kept"]})
    before = len(await audit_entries(vc))
    r = await vc.put("/v1/voice/settings", json={"phrases": bad})
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"
    for w in bad:
        if isinstance(w, str) and len(w) > 4:
            assert w not in r.text
    assert (await vc.get("/v1/voice")).json()["settings"]["phrases"] == ["Kept"]
    assert len(await audit_entries(vc)) == before


async def test_a_non_list_is_a_422_that_does_not_echo_it(vc: AsyncClient) -> None:
    r = await vc.put("/v1/voice/settings", json={"phrases": NEEDLE})
    assert r.status_code == 422 and NEEDLE not in r.text


async def test_changing_the_words_writes_one_audit_entry_holding_only_a_count(
    vc: AsyncClient,
) -> None:
    r = await vc.put("/v1/voice/settings", json={"phrases": [NEEDLE, "Kochi"]})
    assert r.status_code == 200
    mine = [e for e in await audit_entries(vc) if e.tool == "voice_phrases_set"]
    assert len(mine) == 1
    e = mine[0]
    assert e.agent == "owner" and e.outcome == "changed"
    assert e.args_hash == args_hash({"count": 2})
    assert NEEDLE not in repr(e) and "Kochi" not in repr(e)


async def test_a_put_that_leaves_the_words_alone_is_not_audited_as_a_phrase_change(
    vc: AsyncClient,
) -> None:
    await vc.put("/v1/voice/settings", json={"wit": "extra"})
    assert not [e for e in await audit_entries(vc) if e.tool == "voice_phrases_set"]


async def test_the_words_reach_the_engine_through_the_api(vc: AsyncClient) -> None:
    await vc.put("/v1/voice/settings", json={"phrases": ["Trivandrum"]})
    r = await vc.post(
        "/v1/voice/transcribe", content=wav(1.0), headers={"Content-Type": "audio/wav"}
    )
    assert r.status_code == 200
    stt = vc.app.state.voice.engines.stt  # type: ignore[attr-defined]
    assert stt.calls[-1]["phrases"][-1] == "Trivandrum"


# ---- fixer round: M2 retry with base hints, L1 schema bound, L5 normalisation ----------------


class RejectingOnOwnWords(FakeSTT):
    """Google refuses a request that carries any word outside the base list."""

    def __init__(self, base: tuple[str, ...], *, always: bool = False) -> None:
        super().__init__()
        self.base = {w.casefold() for w in base}
        self.always = always

    async def recognize(  # type: ignore[override]
        self, pcm: bytes, *, sample_rate: int, language: str, phrases: tuple[str, ...]
    ) -> Any:
        if self.always or any(w.casefold() not in self.base for w in phrases):
            self.calls.append({"phrases": phrases})
            raise VoiceRejected("Google rejected that voice or text.")
        return await super().recognize(
            pcm, sample_rate=sample_rate, language=language, phrases=phrases
        )


def rig_with(stt: FakeSTT) -> Rig:
    r = Rig()
    r.stt = stt
    r.svc = VoiceService(
        store=r.store,
        billing=billing(registry(), docs=r.docs, clock=Clock(NOW)),
        prices=PRICES,
        engines=VoiceEngines(tts=FakeTTS(), stt=stt, tokens=FakeTokens()),
        language="en-IN",
        honorific="Sir",
    )
    return r


async def test_a_rejected_owner_word_is_retried_once_with_base_hints_and_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = rig_with(RejectingOnOwnWords(Rig().svc.base_phrases))
    await r.svc.update_settings(UID, patch(NEEDLE))
    with caplog.at_level(logging.DEBUG):
        t = await r.svc.transcribe(UID, wav(1.0))
    assert t.text
    calls = r.stt.calls
    assert len(calls) == 2 and NEEDLE in calls[0]["phrases"] and NEEDLE not in calls[1]["phrases"]
    assert NEEDLE not in caplog.text and "retry" in caplog.text.lower()


async def test_rejected_even_with_base_hints_is_still_a_rejection() -> None:
    r = rig_with(RejectingOnOwnWords(Rig().svc.base_phrases, always=True))
    await r.svc.update_settings(UID, patch("Kochi"))
    with pytest.raises(VoiceRejected):
        await r.svc.transcribe(UID, wav(1.0))
    assert len(r.stt.calls) == 2


async def test_no_retry_when_the_owner_has_no_words() -> None:
    r = rig_with(RejectingOnOwnWords(Rig().svc.base_phrases, always=True))
    with pytest.raises(VoiceRejected):
        await r.svc.transcribe(UID, wav(1.0))
    assert len(r.stt.calls) == 1


async def test_a_huge_list_is_a_422_at_parse_and_is_not_echoed(vc: AsyncClient) -> None:
    r = await vc.put("/v1/voice/settings", json={"phrases": fifty(51)})
    assert r.status_code == 422 and "Wordaa" not in r.text


def test_the_schema_refuses_more_than_the_item_limit_before_looking_at_items() -> None:
    with pytest.raises(ValidationError):
        VoiceSettingsPatch.model_validate({"phrases": ["a"] * 51})


def test_duplicates_are_found_after_compatibility_normalisation() -> None:
    assert apply(VoiceSettings(), patch("Kochi", "Ｋochi", "KOCHI")).phrases == ("Kochi",)


def test_long_runs_of_combining_marks_are_refused() -> None:
    assert clean_phrase("a" + "́" * 7) is None
    assert clean_phrase("a" + "́" * 3) is not None
