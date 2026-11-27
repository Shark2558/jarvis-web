# tests/test_r52_i1_desk.py -- R5.2 I1: the call desk gets the laptop speech kit (R18's `local=`).
# The kit's key comes from the desk's own environment or its own private folder (never the kit
# folder or the repository); a short or unreadable key is no key (cloud speech); the desk hands
# V2's `desk_speech` to its session and closes it at the end; the kit ships the client.
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import SecretStr

from jarvis.calldesk import app, config
from jarvis.localspeech.desk import KitLocalSpeech

KEY = "k" * 43  # a test key, never a real one


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    (tmp_path / "kit").mkdir(exist_ok=True)
    (tmp_path / "kit" / config.DESK_ENV).write_text("JARVIS_URL=https://jarvis.example\n")
    return {"JARVIS_DESK_DATA": str(tmp_path / "data"), **extra}


def test_the_desk_reads_the_kits_key_from_its_own_folder(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert config.load(tmp_path / "kit", env).speech_key is None  # no kit: cloud speech
    data = tmp_path / "data"
    data.mkdir()
    (data / config.SPEECH_KEY_FILE).write_text(KEY + "\n")
    cfg = config.load(tmp_path / "kit", env)
    assert cfg.speech_key is not None and cfg.speech_key.get_secret_value() == KEY
    assert KEY not in repr(cfg) and KEY not in str(cfg)


def test_the_environment_wins_and_a_short_key_is_no_key(tmp_path: Path) -> None:
    other = "e" * 40
    env = _env(tmp_path, JARVIS_LOCAL_SPEECH_KEY=other)
    got = config.load(tmp_path / "kit", env).speech_key
    assert got is not None and got.get_secret_value() == other
    short = _env(tmp_path, JARVIS_LOCAL_SPEECH_KEY="too-short")
    assert config.load(tmp_path / "kit", short).speech_key is None


def test_without_a_key_the_desk_offers_no_laptop_speech(tmp_path: Path) -> None:
    cfg = config.load(tmp_path / "kit", _env(tmp_path))
    assert app.local_speech(cfg) is None


def test_with_a_key_the_desk_speaks_through_the_kits_loopback_gate(tmp_path: Path) -> None:
    cfg = config.DeskConfig(
        jarvis_url="https://jarvis.example",
        data_dir=tmp_path,
        kit_dir=tmp_path,
        speech_key=SecretStr(KEY),
    )
    local = app.local_speech(cfg)
    assert isinstance(local, KitLocalSpeech)
    assert "loopback" in repr(local.kit) and KEY not in repr(local.kit)
    assert local.status().installed is False  # not checked yet: nothing offered
    asyncio.run(local.aclose())


def test_the_desk_kit_never_ships_the_speech_key() -> None:
    assert config.SPEECH_KEY_FILE.endswith(".key")
    from jarvis.calldesk import kit

    assert config.SPEECH_KEY_FILE in kit.SKIP_NAMES
    assert {"jarvis.localspeech.desk", "jarvis.localspeech.client"} <= kit.SAFE_JARVIS
