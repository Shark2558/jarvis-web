# src/jarvis/calls/langcheck/fleurs.py
"""Test clips for the language check: Google FLEURS, fetched at run time (R18 B; plan 5.3).

FLEURS (`google/fleurs` on Hugging Face, CC BY 4.0: Conneau et al., 2022) has read-speech test
clips with their transcripts for English and the 12 major Indian languages (and Nepali, Sindhi).
Nothing of it is stored in the repository or the image: the check asks Hugging Face's dataset
viewer for rows of the test split and downloads each clip's audio.

    GET https://datasets-server.huggingface.co/rows?dataset=google/fleurs&config=hi_in
        &split=test&offset=0&length=100
    -> rows[i].row: {raw_transcription, transcription, audio: [{src, type}], ...}

Clips with numbers in their transcript come first (up to 60 % of the set: the key facts), the rest
in order; at most `n` (20). Everything that comes back is untrusted: an audio URL must be https on
Hugging Face's own hosts (huggingface.co, hf.co and their subdomains), every redirect hop checked
before it is followed (at most 3); a clip over
MAX_CLIP_BYTES or MAX_CLIP_S, or not a readable WAV, is skipped. Without the network (or when
Hugging Face refuses) `FleursUnavailable` says so in plain words and nothing is scored.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from jarvis.calls.langcheck.scoring import number_facts
from jarvis.calls.speech.audio import AudioFormatError, pcm_from_wav, pcm_seconds
from jarvis.calls.speech.catalogue import LANGUAGES
from jarvis.calls.speech.errors import SpeechError
from jarvis.calls.speech.rest import BATCH, RetryPolicy, Sleep, json_body, send
from jarvis.logging import get_logger

log = get_logger(__name__)

ROWS_URL = "https://datasets-server.huggingface.co/rows"
DATASET = "google/fleurs"
SOURCE = "google/fleurs test split (CC BY 4.0)"
CLIPS = 20
FETCH_ROWS = 100
NUMBERS_SHARE = 0.6
MAX_CLIP_BYTES = 4 * 1024 * 1024
MAX_CLIP_S = 30.0
MIN_CLIPS = 10  # fewer usable clips than this: no verdict
MAX_TEXT = 1_000
HF_HOSTS = ("huggingface.co", "hf.co")
AUDIO_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
MAX_REDIRECTS = 3


class FleursUnavailable(RuntimeError):
    """No test clips (no network, Hugging Face refused, no FLEURS set): plain words only."""


@dataclass(frozen=True)
class Clip:
    lang: str
    text: str  # the reference transcript (as read)
    pcm: bytes  # 16 kHz mono PCM16, clean (the check phone-simulates it)

    @property
    def seconds(self) -> float:
        return pcm_seconds(self.pcm)


class ClipSource(Protocol):
    async def clips(self, lang: str, n: int = CLIPS) -> list[Clip]: ...


def hf_url(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    on_hf = any(host == h or host.endswith("." + h) for h in HF_HOSTS)
    return parts.scheme == "https" and on_hf and parts.username is None


def _audio_src(cell: object) -> str | None:
    sources = cell if isinstance(cell, list) else [cell]
    found = [s for s in sources if isinstance(s, dict) and isinstance(s.get("src"), str)]
    wav = [s for s in found if s.get("type") == "audio/wav"]
    best = (wav or found)[:1]
    return str(best[0]["src"]) if best else None


def pick_rows(rows: Sequence[dict[str, Any]], n: int) -> list[tuple[str, str]]:
    """(reference, audio URL) for up to `n` rows: numbers first (up to 60 %), then in order."""
    usable: list[tuple[str, str]] = []
    for item in rows:
        row = item.get("row") if isinstance(item, dict) else None
        if not isinstance(row, dict):
            continue
        text = row.get("raw_transcription") or row.get("transcription")
        src = _audio_src(row.get("audio"))
        if isinstance(text, str) and text.strip() and src and hf_url(src):
            usable.append((" ".join(text.split())[:MAX_TEXT], src))
    with_numbers = [u for u in usable if number_facts(u[0])]
    first = with_numbers[: int(n * NUMBERS_SHARE)]
    rest = [u for u in usable if u not in first]
    return (first + rest)[:n]


class FleursClips:
    def __init__(
        self, http: httpx.AsyncClient, *, policy: RetryPolicy = BATCH, sleep: Sleep = asyncio.sleep
    ) -> None:
        self.http = http
        self.policy = policy
        self.sleep = sleep

    async def _rows(self, config: str) -> list[dict[str, Any]]:
        params = {
            "dataset": DATASET,
            "config": config,
            "split": "test",
            "offset": "0",
            "length": str(FETCH_ROWS),
        }
        try:
            r = await send(
                self.http, "GET", ROWS_URL, option="fleurs", api="rows", policy=self.policy,
                sleep=self.sleep, params=params,
            )  # fmt: skip
            rows = json_body(r, "fleurs").get("rows")
        except SpeechError:
            raise FleursUnavailable(
                "The test clips could not be fetched from Hugging Face (no network, or it "
                "refused). Nothing was checked; try again later."
            ) from None
        return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []

    async def _audio(self, url: str) -> bytes | None:
        """The clip's bytes; every hop (redirects followed by hand) checked before it is asked."""
        for _ in range(MAX_REDIRECTS + 1):
            if not hf_url(url):
                log.warning("test clip refused: not a Hugging Face URL")
                return None
            try:
                r = await self.http.get(url, follow_redirects=False, timeout=AUDIO_TIMEOUT)
            except httpx.HTTPError as exc:
                log.warning("test clip not fetched", extra={"why": type(exc).__name__})
                return None
            if r.is_redirect and "location" in r.headers:
                url = str(r.url.join(r.headers["location"]))
                continue
            if r.status_code != 200 or len(r.content) > MAX_CLIP_BYTES:
                log.warning("test clip refused", extra={"status": r.status_code})
                return None
            return r.content
        log.warning("test clip refused: too many redirects")
        return None

    async def clips(self, lang: str, n: int = CLIPS) -> list[Clip]:
        entry = LANGUAGES.get(lang)
        if entry is None or entry.fleurs is None:
            raise FleursUnavailable(f"There are no open test clips for {lang} yet.")
        out: list[Clip] = []
        for text, url in pick_rows(await self._rows(entry.fleurs), n):
            blob = await self._audio(url)
            if blob is None:
                continue
            try:
                pcm = pcm_from_wav(blob)
            except AudioFormatError:
                continue
            if 0 < pcm_seconds(pcm) <= MAX_CLIP_S:
                out.append(Clip(lang, text, pcm))
        if len(out) < min(MIN_CLIPS, n):
            raise FleursUnavailable(
                f"Only {len(out)} test clips for {lang} could be fetched; nothing was checked."
            )
        return out


__all__ = [
    "CLIPS",
    "DATASET",
    "ROWS_URL",
    "SOURCE",
    "Clip",
    "ClipSource",
    "FleursClips",
    "FleursUnavailable",
    "hf_url",
    "pick_rows",
]
