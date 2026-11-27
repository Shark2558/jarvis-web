# src/jarvis/calldesk/speech_local.py
"""Laptop speech mode hooks (plan section 5, "laptop": local models on the desk, text only to the
cloud). Shipped OFF: no model is downloaded or loaded by default, and the desk tells the cloud
it offers cloud speech only. The language check (builder B) decides later which languages, if
any, run on the laptop; a model is then plugged in behind `LocalSpeech`.

With laptop speech on, the desk transcribes each turn of the other person itself and sends
`heard_text`, and it speaks `say_text` itself; no audio leaves the laptop.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

NOT_INSTALLED = "Laptop speech is not installed on this laptop; calls use cloud speech."


class LocalSpeechUnavailable(Exception):
    """Laptop speech was asked for but isn't installed or ready (plain words)."""


@dataclass(frozen=True)
class LocalStatus:
    installed: bool
    languages: tuple[str, ...]  # BCP-47 codes it can hear and speak
    reason: str = ""


@dataclass(frozen=True)
class LocalHeard:
    lang: str
    text: str
    confidence: float


class LocalSpeech(Protocol):
    def status(self) -> LocalStatus: ...

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> LocalHeard: ...

    async def speak(self, text: str, lang: str) -> bytes:
        """PCM16, 16 kHz, mono."""
        ...


class NotInstalled:
    """The default: laptop speech is off, and says so."""

    def status(self) -> LocalStatus:
        return LocalStatus(installed=False, languages=(), reason=NOT_INSTALLED)

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> LocalHeard:
        raise LocalSpeechUnavailable(NOT_INSTALLED)

    async def speak(self, text: str, lang: str) -> bytes:
        raise LocalSpeechUnavailable(NOT_INSTALLED)


def speech_modes(local: LocalSpeech) -> tuple[list[str], list[str]]:
    """(speech_modes, local_languages) for the `hello` message."""
    status = local.status()
    if status.installed and status.languages:
        return ["cloud", "laptop"], list(status.languages)
    return ["cloud"], []


__all__ = [
    "NOT_INSTALLED",
    "LocalHeard",
    "LocalSpeech",
    "LocalSpeechUnavailable",
    "LocalStatus",
    "NotInstalled",
    "speech_modes",
]
