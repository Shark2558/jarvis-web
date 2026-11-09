# src/jarvis/voice/settings.py
"""The owner's voice settings (slice 9; Layer 7 storage via the `Docs` port).

    {prefix}voice_settings/{uid}   user_id, voice, rate, wit, updated_at

Read through an in-process cache (30 s; one instance runs) that a PUT refreshes at once. A stored
field that is not valid (hand-edited, a voice dropped from the catalogue, a bad phrase) reads as
its default, field by field. Writes are validated first (VoiceRejected → 422 input_rejected,
nothing written) and applied in a transaction on the stored value, so two tabs can't lose each
other's change. The owner's phrases (R5 D16) are speech hints for the cloud recogniser.
"""

from __future__ import annotations

import math
import time
import unicodedata
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
PHRASE_ITEMS = 50
PHRASE_CHARS = 40
PHRASE_RAW_CHARS = 400  # longer than this is refused before any cleaning work is done
PHRASE_PUNCT = frozenset("-'.&")
MAX_MARK_RUN = 4  # most combining marks in a row (a base letter with stacked accents)
_LOOKALIKE_APOSTROPHE = "\u2019"
_REJECT_COUNT = f"Add at most {PHRASE_ITEMS} words or names."
_REJECT_ITEM = (
    f"Each word or name needs 1 to {PHRASE_CHARS} characters, with at least one letter, and may "
    "use only letters, numbers, spaces and - ' . &"
)


class VoiceSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    voice: str = DEFAULT_VOICE
    rate: float = RATE_DEFAULT
    wit: str = DEFAULT_WIT
    phrases: tuple[str, ...] = ()


class VoiceSettingsPatch(BaseModel):
    """PUT /v1/voice/settings: any subset; values are checked by `apply`."""

    model_config = ConfigDict(extra="ignore")

    voice: str | None = Field(default=None, max_length=64)
    rate: float | None = None
    wit: str | None = Field(default=None, max_length=16)
    # entries are checked one by one by `apply` (plain-words 422 that never echoes them)
    phrases: list[Any] | None = Field(default=None, max_length=PHRASE_ITEMS)


def rate_ok(v: object) -> bool:
    return (
        isinstance(v, int | float)
        and not isinstance(v, bool)
        and math.isfinite(v)
        and RATE_MIN <= v <= RATE_MAX
    )


def clean_phrase(raw: object) -> str | None:
    """One word or name as it will be stored, or None when it is not acceptable (D16).

    NFC, invisible and control characters dropped, white space collapsed to single spaces; 1 to
    40 characters; at least one letter; only letters (with their marks), digits, spaces and -'.&.
    Nothing is trimmed to fit: too long is refused."""
    if not isinstance(raw, str) or len(raw) > PHRASE_RAW_CHARS:
        return None
    kept: list[str] = []
    for ch in unicodedata.normalize("NFC", raw.replace(_LOOKALIKE_APOSTROPHE, "'")):
        cat = unicodedata.category(ch)
        if ch.isspace():
            kept.append(" ")
        elif cat[0] == "C":  # control, format (zero-width, bidi), surrogate, private, unassigned
            continue
        else:
            kept.append(ch)
    text = " ".join("".join(kept).split())
    if not 1 <= len(text) <= PHRASE_CHARS:
        return None
    if not any(unicodedata.category(c)[0] == "L" for c in text):
        return None
    run = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if not (cat[0] in "LM" or cat == "Nd" or ch == " " or ch in PHRASE_PUNCT):
            return None
        run = run + 1 if cat[0] == "M" else 0
        if run > MAX_MARK_RUN:  # a stack of accents is noise, not a name
            return None
    return text


def _dedupe(words: list[str]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for w in words:
        seen.setdefault(unicodedata.normalize("NFKC", w).casefold(), w)
    return tuple(seen.values())


def _phrases_of(raw: list[Any]) -> tuple[str, ...]:
    if len(raw) > PHRASE_ITEMS:
        raise VoiceRejected(_REJECT_COUNT)
    cleaned = [clean_phrase(w) for w in raw]
    if any(c is None for c in cleaned):
        raise VoiceRejected(_REJECT_ITEM + ".")
    return _dedupe([c for c in cleaned if c is not None])


def _stored_phrases(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    good = [c for c in (clean_phrase(w) for w in raw) if c is not None]
    return _dedupe(good)[:PHRASE_ITEMS]


def apply(cur: VoiceSettings, patch: VoiceSettingsPatch) -> VoiceSettings:
    """The settings after `patch`, or VoiceRejected (plain words)."""
    if patch.voice is not None and find_voice(patch.voice) is None:
        raise VoiceRejected("Unknown voice: choose one from the list.")
    if patch.wit is not None and patch.wit not in WIT_IDS:
        raise VoiceRejected("Wit must be one of: " + ", ".join(WIT_IDS) + ".")
    if patch.rate is not None and not rate_ok(patch.rate):
        raise VoiceRejected(f"Speed must be between {RATE_MIN} and {RATE_MAX}.")
    phrases = _phrases_of(patch.phrases) if patch.phrases is not None else cur.phrases
    return VoiceSettings(
        voice=patch.voice if patch.voice is not None else cur.voice,
        rate=round(patch.rate, 2) if patch.rate is not None else cur.rate,
        wit=patch.wit if patch.wit is not None else cur.wit,
        phrases=phrases,
    )


def decode(doc: Any) -> VoiceSettings:
    if not isinstance(doc, dict):
        return VoiceSettings()
    voice, rate, wit = doc.get("voice"), doc.get("rate"), doc.get("wit")
    return VoiceSettings(
        voice=voice if isinstance(voice, str) and find_voice(voice) else DEFAULT_VOICE,
        rate=float(rate) if rate_ok(rate) else RATE_DEFAULT,  # type: ignore[arg-type]
        wit=wit if isinstance(wit, str) and wit in WIT_IDS else DEFAULT_WIT,
        phrases=_stored_phrases(doc.get("phrases")),
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

    async def stored_phrase_count(self, uid: str) -> int:
        """How many entries the stored document holds, valid or not (for the privacy delete,
        which must reach what read-time filtering hides). Bounded; never the words."""
        doc = await self._d.get(self._path(uid))
        raw = doc.get("phrases") if isinstance(doc, dict) else None
        return min(len(raw), PHRASE_ITEMS * 4) if isinstance(raw, list) else 0

    async def update(self, uid: str, patch: VoiceSettingsPatch) -> VoiceSettings:
        path = self._path(uid)
        apply(VoiceSettings(), patch)  # validate before touching storage
        at = datetime.now(UTC).isoformat()

        async def fn(tx: DocTx) -> VoiceSettings:
            new = apply(decode(await tx.get(path)), patch)
            body = {**new.model_dump(), "phrases": list(new.phrases)}
            tx.set(path, {"user_id": uid, **body, "updated_at": at})
            return new

        new = await self._d.transaction(fn)
        self._cache[uid] = (self._clock(), new)
        return new


__all__ = [
    "CACHE_S",
    "PHRASE_CHARS",
    "PHRASE_ITEMS",
    "VoiceSettings",
    "VoiceSettingsPatch",
    "VoiceSettingsStore",
    "apply",
    "clean_phrase",
    "decode",
    "rate_ok",
]
