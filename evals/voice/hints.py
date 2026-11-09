# evals/voice/hints.py
"""R5 mock suite "hints" (docs/plans/r5-voice.md D16): the owner's words to recognise reach the
speech engine bounded and de-duplicated, and an unacceptable list is refused (422, nothing written,
the words never echoed). Hard gate (100 %). Negative control: with the list validation switched off
an oversized or unclean list MUST reach the engine, and the suite MUST fail."""

from __future__ import annotations

import math
from typing import Any

from harness import WAV, ScriptedTTS, Tokens, app_client, wav

from jarvis.voice import settings as voice_settings
from jarvis.voice.commands import BASE_PHRASES
from jarvis.voice.ports import Transcript
from jarvis.voice.service import VoiceEngines
from jarvis.voice.settings import PHRASE_CHARS, PHRASE_ITEMS

MALAYALAM = "തിരുവനന്തപുരം"
MANY = [f"Name{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(PHRASE_ITEMS + 1)]
MIN_CASES = 12


class RecordingSTT:
    def __init__(self) -> None:
        self.phrases: list[tuple[str, ...]] = []

    async def recognize(
        self, pcm: bytes, *, sample_rate: int, language: str, phrases: tuple[str, ...]
    ) -> Transcript:
        self.phrases.append(phrases)
        return Transcript("ok", 0.9, float(math.ceil(len(pcm) / (2 * sample_rate))), None)


# (id, why, phrases to PUT or None for no PUT, accepted?, words expected at the end of the hints)
CASES: list[tuple[str, str, list[Any] | None, bool, list[str]]] = [
    ("h01", "no words: base hints only", None, True, []),
    (
        "h02",
        "plain names reach the engine last",
        ["Trivandrum", "Kochi"],
        True,
        ["Trivandrum", "Kochi"],
    ),
    ("h03", "a Malayalam word is accepted", [MALAYALAM], True, [MALAYALAM]),
    ("h04", "exactly 50 words are accepted", MANY[:PHRASE_ITEMS], True, MANY[:PHRASE_ITEMS]),
    ("h05", "51 words are refused", MANY, False, []),
    ("h06", "a 40-character word is accepted", ["a" * PHRASE_CHARS], True, ["a" * PHRASE_CHARS]),
    ("h07", "a 41-character word is refused", ["a" * (PHRASE_CHARS + 1)], False, []),
    ("h08", "markup is refused", ["<script>alert</script>"], False, []),
    ("h09", "digits only (no letter) is refused", ["12345"], False, []),
    ("h10", "a non-string entry is refused", ["Kochi", 7], False, []),
    ("h11", "zero-width characters are stripped", ["Tri​van‍drum"], True, ["Trivandrum"]),
    ("h12", "a case duplicate of the name is sent once", ["jarvis", "Kochi"], True, ["Kochi"]),
    ("h13", "white space only is refused", ["   "], False, []),
    ("h14", "an empty list clears the words", [], True, []),
    ("h15", "an emoji is refused", ["Kochi \U0001f600"], False, []),
]


async def _run(
    phrases: list[Any] | None, accepted: bool, tail: list[str]
) -> tuple[list[str], tuple[str, ...]]:
    fails: list[str] = []
    stt = RecordingSTT()
    engines = VoiceEngines(tts=ScriptedTTS(), stt=stt, tokens=Tokens())  # type: ignore[arg-type]
    async with app_client(engines) as c:
        if phrases is not None:
            r = await c.put("/v1/voice/settings", json={"phrases": phrases})
            if accepted and r.status_code != 200:
                fails.append(f"PUT {r.status_code}")
            if not accepted:
                fails += _refusal_faults(r, phrases)
        t = await c.post("/v1/voice/transcribe", content=wav(1.0), headers=WAV)
        if t.status_code != 200:
            fails.append(f"transcribe {t.status_code}")
    sent = stt.phrases[-1] if stt.phrases else ()
    return fails, sent


def _refusal_faults(r: Any, phrases: list[Any]) -> list[str]:
    fails: list[str] = []
    if r.status_code != 422:
        fails.append(f"PUT {r.status_code}, expected 422")
    for w in phrases:
        if isinstance(w, str) and len(w.strip()) > 4 and w in r.text:
            fails.append("the refusal echoes the input")
    return fails


def _hint_faults(sent: tuple[str, ...], accepted: bool, tail: list[str]) -> list[str]:
    fails: list[str] = []
    low = [w.casefold() for w in sent]
    if len(low) != len(set(low)):
        fails.append("duplicate hints")
    if not set(w.casefold() for w in BASE_PHRASES) <= set(low):
        fails.append("a base hint is missing")
    owner = sent[len(sent) - len(tail) :] if tail else ()
    if list(owner) != tail:
        fails.append(f"owner words {len(owner)} != expected {len(tail)}")
    if not accepted and len(sent) > len(BASE_PHRASES) + 1:
        fails.append("a refused list reached the engine")
    if len(sent) > len(BASE_PHRASES) + 1 + PHRASE_ITEMS:
        fails.append("more hints than the limit allows")
    return fails


async def run_cases() -> list[dict[str, Any]]:
    results = []
    for cid, why, phrases, accepted, tail in CASES:
        fails, sent = await _run(phrases, accepted, tail)
        fails += _hint_faults(sent, accepted, tail)
        results.append({"id": cid, "why": why, "passed": not fails, "failures": fails})
    return results


def _unvalidated(raw: list[Any]) -> tuple[str, ...]:
    return tuple(str(w) for w in raw)


async def suite_hints() -> dict[str, Any]:
    results = await run_cases()
    rate = sum(r["passed"] for r in results) / len(results)
    original = voice_settings._phrases_of
    voice_settings._phrases_of = _unvalidated  # type: ignore[assignment]
    try:
        control = await run_cases()
    finally:
        voice_settings._phrases_of = original  # type: ignore[assignment]
    failed = [r["id"] for r in control if not r["passed"]]
    return {
        "cases": len(results),
        "pass_rate": rate,
        "gate": rate == 1 and len(results) >= MIN_CASES and bool(failed),
        "negative_control": {"suite_failed": bool(failed), "failed_cases": len(failed)},
        "results": results,
    }


__all__ = ["suite_hints"]
