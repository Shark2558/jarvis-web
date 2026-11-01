# tests/test_voice_settings.py — slice 9: the voice catalogue (§4) and the owner's voice settings
# on the Docs port (voice_settings/{uid}), cached 30 s and refreshed on PUT.
from __future__ import annotations

import math

import pytest
from billing_fakes import BrokenDocs, put_raw

from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import (
    DEFAULT_VOICE,
    RATE_MAX,
    RATE_MIN,
    SAMPLE_LINE,
    STT_KEY,
    VOICES,
    PriceList,
    find_voice,
)
from jarvis.voice.ports import VoiceRejected
from jarvis.voice.settings import CACHE_S, VoiceSettings, VoiceSettingsPatch, VoiceSettingsStore

UID = "u_owner"
PATH = f"jarvis_voice_settings/{UID}"


class Tick:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# ---- catalogue -------------------------------------------------------------------------------


def test_catalogue_matches_the_plan() -> None:
    assert [v.id for v in VOICES] == [
        "en-GB-Chirp3-HD-Algieba",
        "en-GB-Chirp3-HD-Sadaltager",
        "en-GB-Chirp3-HD-Charon",
        "en-GB-Chirp3-HD-Iapetus",
        "en-GB-Chirp3-HD-Schedar",
        "en-GB-Studio-B",
    ]
    assert DEFAULT_VOICE == "en-GB-Chirp3-HD-Algieba"
    assert {v.type for v in VOICES} == {"chirp3-hd", "studio"}
    assert (
        find_voice("en-GB-Studio-B") is not None and find_voice("en-GB-Studio-B").type == "studio"
    )  # type: ignore[union-attr]
    assert find_voice("en-US-Nope") is None
    assert all(v.language == "en-GB" and v.label and v.style for v in VOICES)
    assert (RATE_MIN, RATE_MAX) == (0.8, 1.25)
    assert "{honorific}" in SAMPLE_LINE and "Systems are running smoothly" in SAMPLE_LINE


def test_prices_and_allowances_come_from_settings() -> None:
    s = Settings(_env_file=None)
    p = PriceList.from_settings(s)
    chirp, studio, stt = p.tts("chirp3-hd"), p.tts("studio"), p.stt
    assert chirp.key == "tts_chirp3-hd" and chirp.free_units == 1_000_000
    assert chirp.usd_per_unit == pytest.approx(30 / 1_000_000)
    assert studio.key == "tts_studio" and studio.usd_per_unit == pytest.approx(160 / 1_000_000)
    assert stt.key == STT_KEY and stt.free_units == 3_600
    assert stt.usd_per_unit == pytest.approx(0.024 / 60)


# ---- settings --------------------------------------------------------------------------------


async def test_defaults_when_nothing_is_stored() -> None:
    s = await VoiceSettingsStore(MemoryDocs()).get(UID)
    assert s == VoiceSettings(voice=DEFAULT_VOICE, rate=1.0, wit="film")


async def test_update_merges_and_persists() -> None:
    docs = MemoryDocs()
    store = VoiceSettingsStore(docs)
    s = await store.update(UID, VoiceSettingsPatch(wit="extra"))
    assert s.wit == "extra" and s.voice == DEFAULT_VOICE
    s = await store.update(UID, VoiceSettingsPatch(voice="en-GB-Studio-B", rate=1.104))
    assert (s.voice, s.rate, s.wit) == ("en-GB-Studio-B", 1.1, "extra")
    doc = await docs.get(PATH)
    assert doc is not None
    assert {k: doc[k] for k in ("user_id", "voice", "rate", "wit")} == {
        "user_id": UID,
        "voice": "en-GB-Studio-B",
        "rate": 1.1,
        "wit": "extra",
    }
    assert "updated_at" in doc
    assert await VoiceSettingsStore(docs).get(UID) == s  # a cold store reads the same


@pytest.mark.parametrize(
    "patch",
    [
        {"voice": "en-US-Neural2-A"},
        {"voice": ""},
        {"wit": "slapstick"},
        {"rate": 0.79},
        {"rate": 1.26},
        {"rate": math.nan},
        {"rate": math.inf},
    ],
)
async def test_invalid_values_are_rejected_and_nothing_is_written(patch: dict[str, object]) -> None:
    docs = MemoryDocs()
    with pytest.raises(VoiceRejected):
        await VoiceSettingsStore(docs).update(UID, VoiceSettingsPatch.model_validate(patch))
    assert await docs.get(PATH) is None


async def test_reads_are_cached_30_seconds_and_put_refreshes() -> None:
    docs, tick = MemoryDocs(), Tick()
    store = VoiceSettingsStore(docs, clock=tick)
    await store.get(UID)
    reads = docs.reads
    await store.get(UID)
    assert docs.reads == reads  # cached
    await store.update(UID, VoiceSettingsPatch(wit="measured"))
    reads = docs.reads
    assert (await store.get(UID)).wit == "measured" and docs.reads == reads
    await put_raw(docs, PATH, {"voice": DEFAULT_VOICE, "rate": 1.0, "wit": "extra"})
    tick.t += CACHE_S - 1
    assert (await store.get(UID)).wit == "measured"
    tick.t += 2
    assert (await store.get(UID)).wit == "extra"


async def test_stored_nonsense_reads_as_defaults_field_by_field() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"voice": "evil", "rate": "fast", "wit": "extra"})
    s = await VoiceSettingsStore(docs).get(UID)
    assert (s.voice, s.rate, s.wit) == (DEFAULT_VOICE, 1.0, "extra")
    await put_raw(docs, PATH, {"voice": "en-GB-Studio-B", "rate": 9.0, "wit": 3})
    s = await VoiceSettingsStore(docs).get(UID)
    assert (s.voice, s.rate, s.wit) == ("en-GB-Studio-B", 1.0, "film")


async def test_storage_errors_propagate() -> None:
    with pytest.raises(RuntimeError):
        await VoiceSettingsStore(BrokenDocs(fail_reads=True)).get(UID)


async def test_a_bad_user_id_is_refused() -> None:
    with pytest.raises(ValueError):
        await VoiceSettingsStore(MemoryDocs()).get("../other")
