# tests/test_r52_review_words.py -- R5.2 combined review (the Workshop's notes, BOOK-LIST 4): words
# that no longer said what the code does. R18's speech builder said the laptop option comes from
# the call desk; since R5.2 it is the laptop speech kit, handed in by `api/r52_wiring.calls_laptop`
# through R18's wiring, and its "not offered" reason (shown in Calls -> Languages) says so. The
# session screen sends each clip by PUT to its own prompt's address.
from __future__ import annotations

import ast
from pathlib import Path

import httpx
from calls_speech_fakes import UID, billing

from jarvis.calls.speech import build
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.config import Settings

ROOT = Path(__file__).resolve().parents[1]


async def _yes() -> bool:
    return True


def test_review_the_laptop_options_reason_names_the_speech_kit() -> None:
    s = Settings(_env_file=None, voice_cloud=False)
    out = build.build_speech(
        s, SpeechMeter(billing(), UID), http=httpx.AsyncClient(), google_tokens=None, sarvam_on=_yes
    )
    words = out.missing["laptop"]
    assert "laptop speech kit" in words and "call desk" not in words
    doc = ast.get_docstring(ast.parse(Path(build.__file__).read_text(encoding="utf-8"))) or ""
    assert "laptop speech kit" in doc and "call desk's local models" not in doc


def test_review_the_session_screen_says_clips_go_by_put() -> None:
    js = (ROOT / "src/jarvis/api/static/console-voice-session.js").read_text(encoding="utf-8")
    header = "\n".join(ln for ln in js.splitlines() if ln.startswith("//"))
    assert "POST .../session/clips" not in header
    assert "PUT .../session/clips/<prompt id>" in header
    assert all(len(ln) <= 100 for ln in js.splitlines()[:20])
