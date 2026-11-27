# src/jarvis/api/r52_wiring.py
"""R5.2 "Your voice" on the app: the I1 join (docs/plans/r5-2-voice.md;
docs/plans/r5-2-integration/I1-NOTES.md). The parts are V2's, V3's and V4's; this module only
builds them on `app.state` and hands R18 its laptop option.

- `voice_service(app, s, docs, engines)` (in `_wire_core`, in place of `build_voice_service`):
  the laptop kit (`voice_laptop`, V2's `LaptopVoice`: state "off", no client, without the kit's
  https address and key), the one profile store (`voice_profiles`, a `DocProfileStore`), the
  voice service with both (V2's engine routing), V4's wake word (`voice_wakeword`) and V3's
  profile API (`voice_profile_api`) over the kit's one client. With `voice_profile_enabled` off
  the routes answer 503 and the service listens in the usual order (no profile).
- `calls_laptop(app)`: R18's `build_speech(..., laptop=)` pair (V2's `calls_bridge`), (None, None)
  without the kit.
- `r52_privacy_sources(app)`: V3's three rows (the profile, the recordings, the wake-word files).

Nothing here makes a network call; nothing logs audio, a transcript, the kit's key or its name.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from jarvis.calls.ports import Hearing, Voice
from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.privacy.sources import CallbackSource
from jarvis.storage.docs import Docs
from jarvis.voice.calls_bridge import laptop_speech
from jarvis.voice.laptop import LaptopVoice, laptop_voice
from jarvis.voice.profile_store import DocProfileStore
from jarvis.voice.service import VoiceEngines, VoiceService, build_voice_service
from jarvis.voice.session_api import SessionApi, build_profile_api
from jarvis.voice.session_privacy import voice_session_sources
from jarvis.voice.wakeword_api import WakewordHandlers

log = get_logger(__name__)


def voice_service(
    app: FastAPI, s: Settings, docs: Docs, engines: VoiceEngines | None
) -> VoiceService:
    """The voice service with R5.2's parts, and those parts on `app.state` (see the docstring)."""
    st = app.state
    laptop = laptop_voice(s)
    profiles = DocProfileStore(docs, prefix=s.firestore_prefix) if s.voice_profile_enabled else None
    voice = build_voice_service(
        s, docs, st.billing, engines=engines, laptop=laptop, profiles=profiles
    )
    st.voice_laptop = laptop
    st.voice_profiles = profiles
    st.voice_wakeword = None if profiles is None else WakewordHandlers(laptop.kit, profiles)
    st.voice_profile_api = None if profiles is None else _profile_api(s, docs, voice, profiles)
    log.info(
        "R5.2 voice wired",
        extra={"laptop": laptop.kit is not None, "profile": profiles is not None},
    )
    return voice


def _profile_api(
    s: Settings, docs: Docs, voice: VoiceService, profiles: DocProfileStore
) -> SessionApi | None:
    laptop: LaptopVoice | None = voice.route.laptop
    try:
        return build_profile_api(
            s, docs=docs, voice=voice, profiles=profiles, kit=laptop.kit if laptop else None
        )
    except Exception as exc:  # noqa: BLE001 - one part never stops the app; the routes say 501
        log.error("R5.2 voice session not wired", extra={"error": type(exc).__name__})
        return None


def calls_laptop(app: FastAPI) -> tuple[Hearing | None, Voice | None]:
    """R18's `laptop=` for `build_speech`: the kit's hearing and voice, or (None, None)."""
    laptop: LaptopVoice | None = getattr(app.state, "voice_laptop", None)
    return (None, None) if laptop is None else laptop_speech(laptop)


def r52_privacy_sources(app: FastAPI) -> tuple[CallbackSource, ...]:
    api: Any = getattr(app.state, "voice_profile_api", None)
    sessions = getattr(api, "s", None)  # SessionApi's VoiceSessions
    return () if sessions is None else tuple(voice_session_sources(sessions))


__all__ = ["calls_laptop", "r52_privacy_sources", "voice_service"]
