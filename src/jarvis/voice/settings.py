# src/jarvis/voice/settings.py
"""The owner's voice settings (slice 9; Layer 7 storage via the `Docs` port).

    {prefix}voice_settings/{uid}   user_id, voice, rate, wit, updated_at

Read through an in-process cache (30 s; one instance runs) that a PUT refreshes at once. A stored
field that is not valid (hand-edited, a voice dropped from the catalogue) reads as its default,
field by field. Writes are validated first (VoiceRejected → 422 input_rejected, nothing written)
and applied in a transaction on the stored value, so two tabs can't lose each other's change.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jarvis.core.prompts import DEFAULT_WIT, WIT_IDS
from jarvis.storage.docs import Docs, DocTx
from jarvis.storage.sessions import safe_id
from jarvis.voice.catalogue import DEFAULT_VOICE, RATE_DEFAULT, RATE_MAX, RATE_MIN, find_voice
from jarvis.voice.ports import VoiceRejected

CACHE_S = 30.0


class VoiceSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    voice: str = DEFAULT_VOICE
    rate: float = RATE_DEFAULT
    wit: str = DEFAULT_WIT


class VoiceSettingsPatch(BaseModel):
    """PUT /v1/voice/settings: any subset; values are checked by `apply`."""

    model_config = ConfigDict(extra="ignore")

    voice: str | None = Field(default=None, max_length=64)
    rate: float | None = None
    wit: str | None = Field(default=None, max_length=16)


def _rate_ok(v: object) -> bool:
    return (
        isinstance(v, int | float)
        and not isinstance(v, bool)
        and math.isfinite(v)
        and RATE_MIN <= v <= RATE_MAX
    )


def apply(cur: VoiceSettings, patch: VoiceSettingsPatch) -> VoiceSettings:
    """The settings after `patch`, or VoiceRejected (plain words)."""
    if patch.voice is not None and find_voice(patch.voice) is None:
        raise VoiceRejected("Unknown voice: choose one from the list.")
    if patch.wit is not None and patch.wit not in WIT_IDS:
        raise VoiceRejected("Wit must be one of: " + ", ".join(WIT_IDS) + ".")
    if patch.rate is not None and not _rate_ok(patch.rate):
        raise VoiceRejected(f"Speed must be between {RATE_MIN} and {RATE_MAX}.")
    return VoiceSettings(
        voice=patch.voice if patch.voice is not None else cur.voice,
        rate=round(patch.rate, 2) if patch.rate is not None else cur.rate,
        wit=patch.wit if patch.wit is not None else cur.wit,
    )


def decode(doc: Any) -> VoiceSettings:
    if not isinstance(doc, dict):
        return VoiceSettings()
    voice, rate, wit = doc.get("voice"), doc.get("rate"), doc.get("wit")
    return VoiceSettings(
        voice=voice if isinstance(voice, str) and find_voice(voice) else DEFAULT_VOICE,
        rate=float(rate) if _rate_ok(rate) else RATE_DEFAULT,  # type: ignore[arg-type]
        wit=wit if isinstance(wit, str) and wit in WIT_IDS else DEFAULT_WIT,
    )


class VoiceSettingsStore:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._d = docs
        self._col = f"{prefix}voice_settings"
        self._clock = clock
        self._cache: dict[str, tuple[float, VoiceSettings]] = {}

    def _path(self, uid: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> VoiceSettings:
        """The owner's settings (defaults when none are stored). Storage errors propagate."""
        path = self._path(uid)
        hit = self._cache.get(uid)
        if hit is not None and self._clock() - hit[0] < CACHE_S:
            return hit[1]
        settings = decode(await self._d.get(path))
        self._cache[uid] = (self._clock(), settings)
        return settings

    async def update(self, uid: str, patch: VoiceSettingsPatch) -> VoiceSettings:
        path = self._path(uid)
        apply(VoiceSettings(), patch)  # validate before touching storage
        at = datetime.now(UTC).isoformat()

        async def fn(tx: DocTx) -> VoiceSettings:
            new = apply(decode(await tx.get(path)), patch)
            tx.set(path, {"user_id": uid, **new.model_dump(), "updated_at": at})
            return new

        new = await self._d.transaction(fn)
        self._cache[uid] = (self._clock(), new)
        return new


__all__ = [
    "CACHE_S",
    "VoiceSettings",
    "VoiceSettingsPatch",
    "VoiceSettingsStore",
    "apply",
    "decode",
]
