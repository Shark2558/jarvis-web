# src/jarvis/voice/privacy.py
"""The owner's "words to recognise" as a privacy-dashboard category (R5 D16).

Follows the `settings_source` pattern in `jarvis.privacy.sources`: a fixed description plus three
small async functions built from the feature's own store. The words are the owner's data and go
only to the owner's own Google speech project; they are shown in the export (the owner's own
download), never in the look, the logs or the audit. R11.1 (D9): the card also says that each
spoken turn's hints (attached files' names, never with Documents on "Never", and words from the
owner's own messages) go to Google Speech too, and are not kept. Deleting clears the list and
nothing else (voice, speed and wit are changed in the Voice panel). Wired by the integrator
where `settings_source(` is.
"""

from __future__ import annotations

from typing import Any

from jarvis.privacy.sources import SEC_SAFETY, CallbackSource, Look, Spec
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore

SOURCE_ID = "voice_phrases"


def voice_phrases_source(store: VoiceSettingsStore) -> CallbackSource:
    async def words(uid: str) -> tuple[str, ...]:
        return (await store.get(uid)).phrases

    async def look(uid: str) -> Look:
        found = await words(uid)
        stored = await store.stored_phrase_count(uid)
        # the basis is only hashed, never shown: folded words so a swap changes the fingerprint
        return Look(len(found), [w.casefold() for w in found], deletable=bool(found) or stored > 0)

    async def export(uid: str) -> dict[str, Any]:
        return {"phrases": list(await words(uid))}

    async def delete(uid: str) -> int:
        n = max(len(await words(uid)), await store.stored_phrase_count(uid))
        if n:
            await store.update(uid, VoiceSettingsPatch(phrases=[]))
        return n

    return CallbackSource(
        Spec(
            SOURCE_ID,
            SEC_SAFETY,
            "Words to recognise",
            "Names and words you asked the cloud voice to listen for.",
            "words",
            "Until you change them.",
            "Firestore; sent to your own Google speech project when you talk",
            delete="simple",
            recoverable=True,
            note=(
                "Deleting clears this list only. Your voice, speed and wit stay as they are. "
                "While you talk, Google Speech is also given this turn's hints: the names of "
                "the files you attached (never with Documents on Never) and words from your "
                "own messages. Hints are not kept."
            ),
        ),
        look,
        export,
        delete,
    )


__all__ = ["SOURCE_ID", "voice_phrases_source"]
