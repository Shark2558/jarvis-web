# tests/test_voice_privacy.py - R5 D16: the owner's "words to recognise" as a privacy category
# (look / export / delete). The integrator registers `voice_phrases_source` at I1.
from __future__ import annotations

from billing_fakes import put_raw

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


async def test_delete_clears_stored_entries_that_reading_hides() -> None:
    docs = MemoryDocs()
    store = VoiceSettingsStore(docs)
    await store.update(UID, VoiceSettingsPatch(wit="extra"))
    path = store._path(UID)
    doc = await docs.get(path)
    assert doc is not None
    await put_raw(docs, path, {**doc, "phrases": ["<script>", 5, "a" * 41]})
    assert (await store.get(UID)).phrases == ()  # hidden from every reader
    src = voice_phrases_source(store)
    assert (await src.describe(UID)).delete == "simple"
    assert await src.delete(UID) == 3
    raw = await docs.get(path)
    assert raw is not None and raw["phrases"] == [] and raw["wit"] == "extra"


async def test_the_fingerprint_changes_when_a_word_is_swapped_for_one_of_the_same_length() -> None:
    store = VoiceSettingsStore(MemoryDocs())
    src = voice_phrases_source(store)
    await store.update(UID, put("Kochi"))
    a = (await src.describe(UID)).rev
    await store.update(UID, put("Delhi"))
    assert (await src.describe(UID)).rev != a


async def test_the_card_says_file_names_and_own_words_go_to_google_speech_as_hints() -> None:
    """R11.1 security review L4: per-turn hints are sent to Google Speech too; the owner is
    told, and that file names never go with Documents on "Never"."""
    v = await voice_phrases_source(VoiceSettingsStore(MemoryDocs())).describe(UID)
    said = f"{v.what} {v.where} {v.note}"
    assert "Google Speech" in said and "hints" in said
    assert "names of the files" in said and "your own messages" in said
    assert "Never" in said
