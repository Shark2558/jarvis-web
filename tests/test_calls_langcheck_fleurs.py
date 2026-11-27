# tests/test_calls_langcheck_fleurs.py — R18 B: FLEURS test clips fetched at run time from
# Hugging Face's dataset viewer (mocked here): numbers first, untrusted URLs checked (https on
# Hugging Face's hosts, redirects too), size and length caps, no network said plainly.
from __future__ import annotations

from typing import Any

import httpx
import pytest
from calls_speech_fakes import no_sleep, tone

from jarvis.calls.langcheck.fleurs import (
    ROWS_URL,
    FleursClips,
    FleursUnavailable,
    hf_url,
    pick_rows,
)
from jarvis.calls.speech.audio import wav_from_pcm
from jarvis.calls.speech.rest import RetryPolicy

FAST = RetryPolicy(attempts=2, base_s=0.01, max_s=0.01, deadline_s=5.0)
ASSET = "https://datasets-server.huggingface.co/assets/google/fleurs/--/hi_in/test/{i}/audio.wav"


def row(i: int, text: str, src: str | None = None) -> dict[str, Any]:
    return {
        "row_idx": i,
        "row": {
            "raw_transcription": text,
            "transcription": text.lower(),
            "audio": [{"src": src or ASSET.format(i=i), "type": "audio/wav"}],
        },
    }


def test_only_hugging_face_https_urls_are_fetched() -> None:
    assert hf_url("https://datasets-server.huggingface.co/assets/x.wav")
    assert hf_url("https://cas-bridge.xethub.hf.co/x")
    assert not hf_url("http://huggingface.co/x")
    assert not hf_url("https://huggingface.co.evil.example/x")
    assert not hf_url("https://user@huggingface.co/x")
    assert not hf_url("https://169.254.169.254/latest")


def test_rows_with_numbers_come_first_up_to_sixty_percent() -> None:
    rows = [row(i, f"pickup at {i}:30" if i % 2 else "a plain sentence") for i in range(40)]
    picked = [text for text, _ in pick_rows(rows, 20)]
    assert len(picked) == 20
    assert all(":30" in text for text in picked[:12])  # 60 % of 20
    assert picked[12:] == ["a plain sentence"] * 8  # then the rest, in order


def test_bad_rows_are_skipped() -> None:
    rows: list[Any] = [
        "junk",
        {"row": None},
        row(1, ""),
        row(2, "ok", src="https://evil.example/a.wav"),
        {"row": {"raw_transcription": "no audio"}},
        row(3, "fine"),
    ]
    assert [t for t, _ in pick_rows(rows, 20)] == ["fine"]


def client(rows: list[dict[str, Any]], audio: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url).startswith(ROWS_URL):
            assert req.url.params["dataset"] == "google/fleurs"
            assert req.url.params["split"] == "test"
            return httpx.Response(200, json={"rows": rows})
        return audio.get(str(req.url), httpx.Response(404))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_clips_are_fetched_and_read_to_16khz() -> None:
    rows = [row(i, f"वाक्य {i}") for i in range(12)]
    audio = {
        ASSET.format(i=i): httpx.Response(200, content=wav_from_pcm(tone(1.0))) for i in range(12)
    }
    clips = await FleursClips(client(rows, audio), policy=FAST, sleep=no_sleep).clips("hi-IN")
    assert len(clips) == 12 and clips[0].text == "वाक्य 0" and clips[0].seconds == 1.0


async def test_oversize_unreadable_and_redirected_away_clips_are_skipped() -> None:
    rows = [row(i, f"s {i}") for i in range(14)]
    good = wav_from_pcm(tone(0.5))
    audio = {ASSET.format(i=i): httpx.Response(200, content=good) for i in range(10)}
    audio[ASSET.format(i=10)] = httpx.Response(200, content=b"x" * (4 * 1024 * 1024 + 1))
    audio[ASSET.format(i=11)] = httpx.Response(200, content=b"not a wav")
    audio[ASSET.format(i=12)] = httpx.Response(302, headers={"Location": "https://evil.example/a"})
    audio[ASSET.format(i=13)] = httpx.Response(200, content=wav_from_pcm(tone(31.0)))
    clips = await FleursClips(client(rows, audio), policy=FAST, sleep=no_sleep).clips("hi-IN")
    assert len(clips) == 10


async def test_no_network_is_said_plainly() -> None:
    def down(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    http = httpx.AsyncClient(transport=httpx.MockTransport(down))
    with pytest.raises(FleursUnavailable) as e:
        await FleursClips(http, policy=FAST, sleep=no_sleep).clips("ta-IN")
    assert "could not be fetched" in str(e.value)


async def test_too_few_clips_and_no_fleurs_set_are_not_checked() -> None:
    rows = [row(i, f"s {i}") for i in range(3)]
    audio = {
        ASSET.format(i=i): httpx.Response(200, content=wav_from_pcm(tone(0.5))) for i in range(3)
    }
    with pytest.raises(FleursUnavailable):
        await FleursClips(client(rows, audio), policy=FAST, sleep=no_sleep).clips("hi-IN")
    with pytest.raises(FleursUnavailable) as e:
        await FleursClips(client([], {}), policy=FAST).clips("kok-IN")
    assert "no open test clips" in str(e.value)
