"""R18 C: the call desk's settings file and the laptop-speech hooks (shipped off)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.calldesk import config, speech_local


def test_load_reads_the_address_and_puts_data_in_the_profile(tmp_path: Path) -> None:
    (tmp_path / "desk.env").write_text(
        "﻿# written by the kit download\nJARVIS_URL=https://jarvis.example.run.app/\n"
        "junk line\nlower=ignored\n",
        encoding="utf-8",
    )
    cfg = config.load(tmp_path, {"LOCALAPPDATA": "/profile/AppData/Local"})
    assert cfg.jarvis_url == "https://jarvis.example.run.app"
    assert cfg.data_dir == Path("/profile/AppData/Local/JARVIS/CallDesk")
    assert cfg.audio_state.name == "audio-state.json" and cfg.secret.name == "secret.json"
    assert cfg.stop_request.name == "stop.request" and cfg.log_file.name == "calldesk.log"


def test_overrides_and_fallbacks(tmp_path: Path) -> None:
    env = {"JARVIS_URL": "https://other.example", "JARVIS_DESK_DATA": str(tmp_path / "d")}
    cfg = config.load(tmp_path, env)
    assert cfg.jarvis_url == "https://other.example" and cfg.data_dir == tmp_path / "d"
    assert config.default_data_dir({}) == Path.home() / ".jarvis-calldesk"


@pytest.mark.parametrize(
    "url",
    [
        "http://jarvis.example",
        "https://user:pw@jarvis.example",
        "https://jarvis.example/path",
        "https://jarvis.example?x=1",
        "https://bad_host!",
        "ftp://jarvis.example",
    ],
)
def test_bad_addresses_are_refused_without_repeating_them(tmp_path: Path, url: str) -> None:
    with pytest.raises(config.ConfigError) as err:
        config.load(tmp_path, {"JARVIS_URL": url})
    assert url not in str(err.value)


def test_missing_address(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="missing"):
        config.load(tmp_path, {})


async def test_laptop_speech_ships_off_and_says_so() -> None:
    local = speech_local.NotInstalled()
    status = local.status()
    assert not status.installed and status.languages == () and "not installed" in status.reason
    assert speech_local.speech_modes(local) == (["cloud"], [])
    with pytest.raises(speech_local.LocalSpeechUnavailable):
        await local.transcribe(b"\x00" * 640, ["en-IN"])
    with pytest.raises(speech_local.LocalSpeechUnavailable):
        await local.speak("hello", "en-IN")


def test_an_installed_laptop_speech_offers_its_languages() -> None:
    class Installed(speech_local.NotInstalled):
        def status(self) -> speech_local.LocalStatus:
            return speech_local.LocalStatus(True, ("en-IN", "hi-IN"))

    assert speech_local.speech_modes(Installed()) == (["cloud", "laptop"], ["en-IN", "hi-IN"])
