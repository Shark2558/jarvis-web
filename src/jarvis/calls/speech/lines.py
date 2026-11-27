# src/jarvis/calls/speech/lines.py
"""The pre-made lines of every call, per language (R18 B; Layers 7, 8): made once, not per call.

The opening disclosure (brief, "Opening line") and the few lines every call may need, in the call's
language, translated once by the brain (`translate.Translator`, FAST tier) and spoken once by the
language's voice option, then kept:

    {prefix}call_lines/{lang}                     lines {key: text}, english (hash), made_at
    {prefix}call_line_audio/{lang}__{voice}__{key}  pcm (16 kHz PCM16), text (hash), made_at

A line is made again only when its English changes in code (the English hash), its spoken text
changes (the owner's first name, a new translation) or it is missing. English is never
translated. A translation the brain gets wrong is refused whole (`TranslationRefused`) and the
call falls back to English. Audio over MAX_AUDIO_BYTES (a Firestore document is at most 1 MiB) is
spoken but not kept. One make at a time per language and voice in this process.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType

from jarvis.calls.models import ENGLISH, LANGUAGE_NAMES, NAME_MAX, OPENING_LINE
from jarvis.calls.ports import Voice
from jarvis.calls.speech.translate import Translator
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)

LINES: MappingProxyType[str, str] = MappingProxyType(
    {
        "opening": OPENING_LINE,
        "hold": "One moment, please.",
        "goodbye": "Thank you for your time. Goodbye.",
        "handover": "{first_name} is joining the call now.",
        "call_back": "I will check with {first_name} and call you back.",
        "stop_recording": "Understood. I stop recording now.",
        "not_supported": (
            "Sorry, I cannot speak this language on this call. {first_name} will call you back."
        ),
    }
)
TEXT_COLL = "call_lines"
AUDIO_COLL = "call_line_audio"
MAX_AUDIO_BYTES = 900_000  # under Firestore's 1 MiB a document, with room for the fields


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


ENGLISH_HASH = _hash(json.dumps(dict(LINES), sort_keys=True))


def _name(first_name: str) -> str:
    name = " ".join(first_name.split())[:NAME_MAX]
    if not name:
        raise ValueError("the owner's first name is needed for the call lines")
    return name


class LinesCache:
    def __init__(self, docs: Docs, *, prefix: str, translator: Translator) -> None:
        self.docs = docs
        self.prefix = prefix
        self.translator = translator
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _text_path(self, lang: str) -> str:
        return f"{self.prefix}{TEXT_COLL}/{lang}"

    def _audio_path(self, lang: str, voice: str, key: str) -> str:
        return f"{self.prefix}{AUDIO_COLL}/{lang}__{voice}__{key}"

    async def texts(self, lang: str) -> dict[str, str]:
        """The lines in `lang`, with `{first_name}` still in them (translated once, then kept)."""
        if lang not in LANGUAGE_NAMES:
            raise ValueError("unknown call language")
        if lang == ENGLISH:
            return dict(LINES)
        stored = await self.docs.get(self._text_path(lang))
        if stored and stored.get("english") == ENGLISH_HASH:
            lines = stored.get("lines")
            if isinstance(lines, dict) and set(lines) == set(LINES):
                return {k: str(v) for k, v in lines.items()}
        made = await self.translator.translate(LINES, lang)
        lines = {k: t.text for k, t in made.items()}
        doc = {"lines": lines, "english": ENGLISH_HASH, "made_at": datetime.now(UTC).isoformat()}

        async def save(tx: DocTx) -> None:
            tx.set(self._text_path(lang), doc)

        await self.docs.transaction(save)
        return lines

    async def line(self, lang: str, key: str, first_name: str, voice: Voice) -> bytes:
        """The spoken line (PCM16 16 kHz mono), made once per language, voice and text."""
        if key not in LINES:
            raise KeyError(f"no call line {key!r}")
        lock = self._locks.setdefault((lang, voice.name), asyncio.Lock())
        async with lock:
            text = (await self.texts(lang))[key].replace("{first_name}", _name(first_name))
            path = self._audio_path(lang, voice.name, key)
            digest = _hash(lang, voice.name, text)
            stored = await self.docs.get(path)
            if stored and stored.get("text") == digest and isinstance(stored.get("pcm"), bytes):
                return bytes(stored["pcm"])
            pcm = await voice.speak(text, lang)
            await self._keep(path, digest, pcm, lang, voice.name, key)
            return pcm

    async def _keep(
        self, path: str, digest: str, pcm: bytes, lang: str, voice: str, key: str
    ) -> None:
        if len(pcm) > MAX_AUDIO_BYTES:
            log.warning("call line too long to keep", extra={"lang": lang, "key": key})
            return
        doc = {"pcm": pcm, "text": digest, "voice": voice, "made_at": datetime.now(UTC).isoformat()}

        async def save(tx: DocTx) -> None:
            tx.set(path, doc)

        await self.docs.transaction(save)
        log.info("call line made", extra={"lang": lang, "voice": voice, "key": key})

    async def prepare(self, lang: str, first_name: str, voice: Voice) -> Mapping[str, bytes]:
        """Every line of `lang`, made where missing (before a call, or by the language check)."""
        return {key: await self.line(lang, key, first_name, voice) for key in LINES}


__all__ = ["AUDIO_COLL", "ENGLISH_HASH", "LINES", "MAX_AUDIO_BYTES", "TEXT_COLL", "LinesCache"]
