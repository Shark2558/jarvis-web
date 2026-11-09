# tests/test_voice_privacy.py - R5 D16: the owner's "words to recognise" as a privacy category
# (look / export / delete). The integrator registers `voice_phrases_source` at I1.
from __future__ import annotations

from jarvis.storage.docs import MemoryDocs
from jarvis.voice.privacy import voice_phrases_source
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore

UID = "u_owner"
OTHER = "u_other"


def put(*words: str) -> VoiceSettingsPatch:
    return VoiceSettingsPatch.model_validate({"phrases": list(words)})


async def test_look_counts_only_this_owners_words_and_never_lists_them() -> None:
    store = VoiceSettingsStore(MemoryDocs())
    await store.update(UID, put("Trivandrum", "Kochi"))
    await store.update(OTHER, put("Other"))
    v = await voice_phrases_source(store).describe(UID)
    assert (v.id, v.count, v.export, v.delete) == ("voice_phrases", 2, True, "simple")
    assert "Trivandrum" not in v.model_dump_json()


async def test_look_with_no_words_offers_no_delete() -> None:
    v = await voice_phrases_source(VoiceSettingsStore(MemoryDocs())).describe(UID)
    assert v.count == 0 and v.delete == "none"


async def test_the_fingerprint_changes_when_the_words_change() -> None:
    store = VoiceSettingsStore(MemoryDocs())
    src = voice_phrases_source(store)
    await store.update(UID, put("Kochi"))
    a = (await src.describe(UID)).rev
    await store.update(UID, put("Kochi", "Delhi"))
    assert (await src.describe(UID)).rev != a


async def test_export_holds_the_words_and_only_them() -> None:
    store = VoiceSettingsStore(MemoryDocs())
    await store.update(UID, put("Trivandrum", "Kochi"))
    await store.update(UID, VoiceSettingsPatch(wit="extra"))
    assert await voice_phrases_source(store).export(UID) == {"phrases": ["Trivandrum", "Kochi"]}


async def test_delete_clears_only_the_words_and_only_this_owners() -> None:
    docs = MemoryDocs()
    store = VoiceSettingsStore(docs)
    await store.update(UID, VoiceSettingsPatch.model_validate({"wit": "extra", "phrases": ["A"]}))
    await store.update(OTHER, put("Keep"))
    src = voice_phrases_source(store)
    assert await src.delete(UID) == 1
    mine = await VoiceSettingsStore(docs).get(UID)
    assert mine.phrases == () and mine.wit == "extra"
    assert (await VoiceSettingsStore(docs).get(OTHER)).phrases == ("Keep",)
    assert (await src.describe(UID)).count == 0
    assert await src.delete(UID) == 0
