# tests/test_r52_i0_seams.py -- R5.2 I0: the numbers one module repeats from another stay equal
# (the kit's key, the Funnel ports, the words list), the new modules sit in their layers, and the
# book's settings scanner reads R5.2's keys through `Settings`' base classes.
from __future__ import annotations

from pathlib import Path

from jarvis import config_voice
from jarvis.buildbook.gen.code import settings_fields
from jarvis.buildbook.gen.layers import LAYER_OF
from jarvis.buildbook.gen.repo import Repo
from jarvis.localspeech import protocol as p
from jarvis.offline.config import ALLOWED_PORTS
from jarvis.voice import profile as vp
from jarvis.voice.settings import PHRASE_CHARS, PHRASE_ITEMS

ROOT = Path(__file__).resolve().parents[1]


def test_repeated_numbers_stay_equal() -> None:
    assert config_voice.FUNNEL_PORTS == ALLOWED_PORTS
    assert config_voice.KIT_KEY_MIN_CHARS == p.KEY_MIN_CHARS
    assert p.PHRASES_MAX == PHRASE_ITEMS == vp.WORDS_MAX and p.PHRASE_CHARS == PHRASE_CHARS
    assert p.FUNNEL_PORT in ALLOWED_PORTS


def test_the_new_modules_have_their_layers() -> None:
    assert LAYER_OF["localspeech"] == "L6" and LAYER_OF["config_voice"] == "X"


def test_the_book_reads_r5_2s_settings() -> None:
    names = {name for name, _ in settings_fields(Repo.from_git(ROOT))}
    assert {"local_speech_url", "local_speech_key", "voice_profile_enabled"} <= names
    assert {"calls_enabled", "gemini_api_key"} <= names  # R18's base and Settings' own still read
