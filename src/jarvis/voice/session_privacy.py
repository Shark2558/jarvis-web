# src/jarvis/voice/session_privacy.py
"""R5.2's voice data on the privacy dashboard (plan 3.3, 5 "Privacy"; D4), the `settings_source`
pattern of `jarvis.privacy.sources`: a fixed description plus look / export / delete built from
the voice session's own parts. Wired by the integrator where `settings_source(` is.

    voice_profile         the cloud's profile: the engines' scores for his voice, the chosen one,
                          the corrections (Firestore). Deleting it goes back to the usual order.
    voice_recordings      the session's clips, on his laptop only (encrypted by the speech kit),
                          and the comparison's transcripts here. "Delete my recordings".
    voice_wakeword_files  the wake-word files trained from those clips, on the laptop; deleting
                          them deletes the recordings too (the kit deletes them together).

No audio or voice print is ever in the cloud, so none is ever exported: the export is the
profile's fields and the transcripts of the comparison lines. A laptop that can't be reached is
"Couldn't check right now" (look) or a failed delete: nothing claims to be gone that isn't.
"""

from __future__ import annotations

from typing import Any, Final

from jarvis.privacy.sources import SEC_SAFETY, CallbackSource, Look, Spec
from jarvis.voice.profile import VoiceProfile
from jarvis.voice.session import VoiceSessions

PROFILE_ID: Final = "voice_profile"
RECORDINGS_ID: Final = "voice_recordings"
WAKEWORD_ID: Final = "voice_wakeword_files"
SOURCE_IDS: Final = (PROFILE_ID, RECORDINGS_ID, WAKEWORD_ID)
LAPTOP: Final = "On your laptop, encrypted by the speech kit"


def _learned(p: VoiceProfile) -> int:
    return len(p.ranking) + len(p.corrections) + (p.chosen is not None)


def profile_source(sessions: VoiceSessions) -> CallbackSource:
    async def look(uid: str) -> Look:
        p = await sessions.profile(uid)
        basis = (
            p.chosen,
            [(s.engine, s.wer, s.commands) for s in p.ranking],
            [(c.heard, c.meant) for c in p.corrections],
            p.corrections_on,
        )
        return Look(_learned(p), basis, deletable=p != VoiceProfile())

    async def export(uid: str) -> dict[str, Any]:
        p = await sessions.profile(uid)
        return {"voice_profile": p.model_dump(mode="json", exclude={"session_id"})}

    async def delete(uid: str) -> int:
        n = _learned(await sessions.profile(uid))
        await sessions.p.profiles.delete(uid)
        return n

    return CallbackSource(
        Spec(
            PROFILE_ID,
            SEC_SAFETY,
            "Your voice profile",
            "Which listening engine understands you best, each engine's score on your voice, and "
            "the mishearings JARVIS corrects.",
            "learned items",
            "Until you delete it or record a new voice session.",
            "Firestore",
            delete="simple",
            note=(
                "No audio is in it. Deleting it puts JARVIS back on the usual listening order; "
                "a new voice session learns it again."
            ),
        ),
        look,
        export,
        delete,
    )


def recordings_source(sessions: VoiceSessions) -> CallbackSource:
    async def look(uid: str) -> Look:
        p, doc = await sessions.profile(uid), await sessions.current(uid)
        held = 0 if doc is None else len(doc.browser) + len(doc.google)
        basis = (p.clips, None if doc is None else doc.session_id, held)
        return Look(p.clips, basis, deletable=p.clips > 0 or doc is not None)

    async def export(uid: str) -> dict[str, Any]:
        p, doc = await sessions.profile(uid), await sessions.current(uid)
        out: dict[str, Any] = {"recordings_on_laptop": p.clips}
        if doc is not None:
            text = {x.id: x.text for x in doc.prompts}
            out["comparison_lines"] = [
                {
                    "prompt": text[pid],
                    "browser_heard": doc.browser.get(pid),
                    "google_heard": doc.google.get(pid),
                }
                for pid in doc.done
                if pid in doc.browser or pid in doc.google
            ]
        return out

    async def delete(uid: str) -> int:
        return (await sessions.delete_recordings(uid)).clips

    return CallbackSource(
        Spec(
            RECORDINGS_ID,
            SEC_SAFETY,
            "Voice session recordings",
            "The lines you read aloud in the voice session, and what each listening engine heard "
            "for the comparison lines.",
            "recordings",
            "Until you delete them or start a new voice session.",
            f"{LAPTOP}; the comparison's words in Firestore",
            delete="confirm",
            note=(
                "The recordings never leave your laptop; they can only be deleted while it is on. "
                "Your voice profile stays (delete it on its own row). The wake-word files made "
                "from them are on the next row."
            ),
        ),
        look,
        export,
        delete,
    )


def wakeword_files_source(sessions: VoiceSessions) -> CallbackSource:
    async def look(uid: str) -> Look:
        files = await sessions.wakeword_files()
        return Look(files, files, deletable=files > 0)

    async def delete(uid: str) -> int:
        return (await sessions.delete_recordings(uid, wakeword=True)).wakeword_files

    return CallbackSource(
        Spec(
            WAKEWORD_ID,
            SEC_SAFETY,
            "Wake-word files from your voice",
            'Your own "Hey Jarvis" check, trained on your laptop from your session recordings.',
            "files",
            "Until you delete them.",
            LAPTOP,
            delete="confirm",
            note=(
                "Deleting them also deletes the session recordings they were made from, on your "
                "laptop. Your voice profile stays."
            ),
        ),
        look,
        None,
        delete,
    )


def voice_session_sources(sessions: VoiceSessions) -> list[CallbackSource]:
    """The three rows, in the order the panel shows them."""
    return [
        profile_source(sessions),
        recordings_source(sessions),
        wakeword_files_source(sessions),
    ]


__all__ = [
    "PROFILE_ID",
    "RECORDINGS_ID",
    "SOURCE_IDS",
    "WAKEWORD_ID",
    "profile_source",
    "recordings_source",
    "voice_session_sources",
    "wakeword_files_source",
]
