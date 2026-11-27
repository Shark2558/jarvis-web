# tests/test_r52_v1_cli.py -- R5.2 V1: the kit's commands. The server never starts without a key of
# 32+ characters; the model list says what was left out; "what this kit installed" lists models
# and the pinned packages; deleting recordings asks for DELETE first; the key only from the
# environment.
from __future__ import annotations

import json
from pathlib import Path

import pytest
from kit_fakes import KEY, pcm

from jarvis.localspeech import __main__ as cli
from jarvis.localspeech import protocol as p
from jarvis.localspeech.clips import ClipVault
from jarvis.localspeech.kitconfig import ENV_DIR, ENV_KEY, ENV_MANIFEST, KitConfig, KitConfigError

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "deploy" / "local-speech" / "models.json"


@pytest.fixture
def kit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(ENV_DIR, str(tmp_path))
    monkeypatch.setenv(ENV_MANIFEST, str(MANIFEST))
    monkeypatch.delenv(ENV_KEY, raising=False)
    return tmp_path


def run(argv: list[str]) -> tuple[int, str]:
    lines: list[str] = []
    code = cli.main(argv, out=lines.append)
    return code, "\n".join(lines)


def test_the_server_refuses_to_start_without_a_long_enough_key(
    kit_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, text = run(["serve"])
    assert code == 1 and "32 characters" in text
    monkeypatch.setenv(ENV_KEY, "tiny-key-xyz")
    code, text = run(["serve"])
    assert code == 1 and "tiny-key-xyz" not in text


def test_the_config_never_shows_its_key() -> None:
    config = KitConfig.from_env({ENV_KEY: KEY, ENV_DIR: "/tmp/kit"})
    assert KEY not in repr(config) and config.require_key() == KEY
    assert config.clips_dir == Path("/tmp/kit/clips") and config.key_file == Path("/tmp/kit/key")
    with pytest.raises(KitConfigError):
        KitConfig.from_env({ENV_DIR: "/tmp/kit", "JARVIS_SPEECH_KIT_DEVICE": "tpu"})


def test_the_model_list_says_what_was_left_out(
    kit_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, text = run(["models"])
    assert code == 0 and "whisper-small: faster-whisper small" in text and "(MIT)" in text
    assert "kokoro: left out" in text
    raw = json.loads(MANIFEST.read_text())  # I1: Whisper is pinned; a list with none installs none
    empty = kit_env / "none-pinned.json"
    empty.write_text(json.dumps({**raw, "models": []}))
    monkeypatch.setenv(ENV_MANIFEST, str(empty))
    code, text = run(["models", "install"])
    assert code == 0 and "nothing to install" in text
    code, text = run(["models", "install", "no-such-engine"])
    assert code == 2 and "whisper-small" in text


def test_what_this_kit_installed(kit_env: Path) -> None:
    code, text = run(["installed"])
    assert code == 0 and "Models" in text and "none yet" in text
    assert "starlette==" in text and "faster-whisper==" in text
    assert "Caddy" in text and "Tailscale" in text


def test_deleting_every_recording_asks_first(
    kit_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = KitConfig.from_env()
    vault = ClipVault(config.clips_dir, config.clip_key_file)
    clip = p.ClipIn(
        session_id="vs_000000000001",
        prompt_id="cmd_1",
        audio=p.encode_pcm(pcm()),
        kind=p.PromptKind.COMMAND,
    )
    vault.put(clip)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    assert run(["delete-recordings"]) == (1, "Nothing deleted.")
    monkeypatch.setattr("builtins.input", lambda prompt: "DELETE")
    code, text = run(["delete-recordings"])
    assert code == 0 and "Deleted 1 recordings" in text and vault.sessions() == []


def test_the_self_test_needs_the_key_in_its_window(kit_env: Path) -> None:
    code, text = run(["selftest"])
    assert code == 1 and "start-kit.ps1 -SelfTest" in text
