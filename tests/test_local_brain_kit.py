# tests/test_local_brain_kit.py -- R1 C (D10): deploy/local-brain/ (Caddyfile, start-unix.sh,
# start-windows.ps1, README). The owner's one-time laptop step, built so it can't be done unsafely:
# the gate listens on loopback only, passes two requests with the right key, Ollama is never
# published, the key is made once, kept private and goes to Caddy through the environment only.
# start-unix.sh is RUN here against stub caddy / tailscale / ollama / curl programs.
from __future__ import annotations

import base64
import re
import stat
import subprocess
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "deploy" / "local-brain"
CADDY = (KIT / "Caddyfile").read_text()
UNIX = KIT / "start-unix.sh"
WIN = (KIT / "start-windows.ps1").read_text()
README = (KIT / "README.md").read_text()


def _code(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_the_kit_has_exactly_the_planned_files() -> None:
    assert sorted(p.name for p in KIT.iterdir()) == [
        "Caddyfile",
        "README.md",
        "start-unix.sh",
        "start-windows.ps1",
    ]


def test_the_gate_listens_on_loopback_only_and_is_closed_to_admin() -> None:
    code = _code(CADDY)
    assert "http://127.0.0.1:11435 {" in code and "bind 127.0.0.1" in code
    assert "admin off" in code and "auto_https off" in code
    assert "0.0.0.0" not in code and "[::]" not in code and ":11435 {" in code


def test_the_gate_passes_only_two_requests_and_only_with_the_key() -> None:
    code = _code(CADDY)
    assert code.count("reverse_proxy") == 2
    for needle in ("POST", "/v1/chat/completions", "GET", "/v1/models"):
        assert needle in code
    assert code.count('header Authorization "Bearer {env.JARVIS_LOCAL_KEY}"') == 2
    assert 'respond "Unauthorized" 401' in code and 'respond "Not found" 404' in code
    # the key is never in the file, and never forwarded to Ollama
    assert code.count("header_up -Authorization") == 2
    # nothing else of Ollama (pull, delete, tags, ...) is routed
    assert "/api" not in code and "reverse_proxy 127.0.0.1:11434" in code


def test_ollama_is_never_published() -> None:
    for text in (UNIX.read_text(), WIN):
        assert "funnel --bg --https=8443 11435" in text
        assert not re.search(r"funnel[^\n]*11434", _code(text))
        assert "serve --bg" not in text


def test_the_unix_script_is_valid_bash_and_strict() -> None:
    assert subprocess.run(["bash", "-n", str(UNIX)], check=False).returncode == 0
    text = UNIX.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text and "umask 077" in text and "chmod 600" in text
    assert "chmod 700" in text


def test_the_key_is_32_random_bytes_and_goes_to_caddy_through_the_environment() -> None:
    text = _code(UNIX.read_text())
    assert "head -c 32 /dev/urandom" in text
    assert re.search(r'JARVIS_LOCAL_KEY="\$KEY" caddy run', text)
    assert "--key" not in text and not re.search(
        r"caddy [^\n]*\$KEY", text.replace('JARVIS_LOCAL_KEY="$KEY" caddy', "")
    )
    win = _code(WIN)
    assert "GetBytes($bytes)" in win and "New-Object byte[] 32" in win
    assert "$env:JARVIS_LOCAL_KEY = $key" in win and "icacls" in win
    assert "-ArgumentList" in win and "$key" not in win.split("-ArgumentList")[1].split("\n")[0]


def test_the_windows_script_checks_what_it_needs_and_cleans_up() -> None:
    for token in (
        "Need 'caddy'",
        "Need 'tailscale'",
        "api/version",
        "funnel --bg --https=8443 11435",
        "finally",
    ):
        assert token in WIN
    assert "funnel --https=8443 off" in WIN


def test_the_readme_covers_the_setup_in_plain_words() -> None:
    for token in (
        "ollama pull qwen2.5:7b",
        "qwen2.5:3b",
        "Funnel",
        "start-unix.sh",
        "start-windows.ps1",
        "Integrations -> Offline mode",
        "Every change asks first",
        "awake",
    ):
        assert token in README
    assert "Claude can't be reached and your laptop didn't answer" in " ".join(README.split())


# ---- run start-unix.sh against stubs ----------------------------------------------------------


@pytest.fixture
def stubs(tmp_path: Path) -> dict[str, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    log.mkdir()

    def stub(name: str, body: str) -> None:
        p = bin_dir / name
        p.write_text("#!/usr/bin/env bash\n" + body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    stub("ollama", "exit 0\n")
    stub("curl", f'echo "$@" >> "{log}/curl"; exit 0\n')
    stub(
        "caddy",
        f'echo "key=$JARVIS_LOCAL_KEY" > "{log}/caddy_env"\n'
        f'echo "args=$*" > "{log}/caddy_args"\nexit 0\n',
    )
    stub(
        "tailscale",
        f'echo "$@" >> "{log}/tailscale"\n'
        'if [ "$1 $2" = "funnel status" ]; then\n'
        '  echo "https://my-laptop.tail1234.ts.net:8443 (Funnel on)"; echo "|-- / proxy http://127.0.0.1:11435"\n'
        "fi\nexit 0\n",
    )
    return {"bin": bin_dir, "log": log}


def _run(tmp_path: Path, stubs: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{stubs['bin']}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "JARVIS_LOCAL_BRAIN_DIR": str(tmp_path / "home" / ".lb"),
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", str(UNIX)], env=env, capture_output=True, text=True, timeout=30, check=False
    )


def test_first_run_makes_a_private_key_and_prints_address_and_key(
    tmp_path: Path, stubs: dict[str, Path]
) -> None:
    r = _run(tmp_path, stubs)
    assert r.returncode == 0, r.stderr
    key_file = tmp_path / "home" / ".lb" / "key"
    key = key_file.read_text()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", key)
    assert len(base64.urlsafe_b64decode(key + "=")) == 32
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700
    assert "Address: https://my-laptop.tail1234.ts.net:8443" in r.stdout
    assert f"Key: {key}" in r.stdout
    # Caddy got the key through its environment, never as an argument
    assert (stubs["log"] / "caddy_env").read_text().strip() == f"key={key}"
    args = (stubs["log"] / "caddy_args").read_text()
    assert "Caddyfile" in args and key not in args
    ts = (stubs["log"] / "tailscale").read_text()
    assert "funnel --bg --https=8443 11435" in ts and "11434" not in ts
    assert "funnel --https=8443 off" in ts  # only this port is closed again on exit
    assert "reset" not in ts  # never wipes the owner's other Funnel / Serve settings


def test_second_run_keeps_the_same_key(tmp_path: Path, stubs: dict[str, Path]) -> None:
    _run(tmp_path, stubs)
    first = (tmp_path / "home" / ".lb" / "key").read_text()
    r = _run(tmp_path, stubs)
    assert (tmp_path / "home" / ".lb" / "key").read_text() == first
    assert f"Key: {first}" in r.stdout


def test_two_fresh_installs_make_different_keys(tmp_path: Path, stubs: dict[str, Path]) -> None:
    _run(tmp_path, stubs)
    a = (tmp_path / "home" / ".lb" / "key").read_text()
    (tmp_path / "home" / ".lb" / "key").unlink()
    _run(tmp_path, stubs)
    assert (tmp_path / "home" / ".lb" / "key").read_text() != a


def test_a_missing_program_is_named_and_nothing_is_started(
    tmp_path: Path, stubs: dict[str, Path]
) -> None:
    (stubs["bin"] / "caddy").unlink()
    r = _run(tmp_path, stubs)
    assert r.returncode != 0 and "Missing: caddy" in r.stderr
    assert not (stubs["log"] / "tailscale").exists()


def test_ollama_not_answering_is_explained(tmp_path: Path, stubs: dict[str, Path]) -> None:
    (stubs["bin"] / "curl").write_text("#!/usr/bin/env bash\nexit 22\n")
    r = _run(tmp_path, stubs)
    assert r.returncode != 0 and "Ollama is not answering" in r.stderr
    assert not (stubs["log"] / "caddy_env").exists()


def test_funnel_failing_gives_a_hint_and_stops(tmp_path: Path, stubs: dict[str, Path]) -> None:
    (stubs["bin"] / "tailscale").write_text(
        f'#!/usr/bin/env bash\necho "$@" >> "{stubs["log"]}/tailscale"\n'
        '[ "$1" = "funnel" ] && [ "$2" = "--bg" ] && exit 1\nexit 0\n'
    )
    r = _run(tmp_path, stubs)
    assert r.returncode != 0 and "Funnel did not start" in r.stderr
    assert "Key:" not in r.stdout


# ---- security review fixes 5-7 ----------------------------------------------------------------


def test_the_caddyfile_fails_closed_when_the_key_is_missing_or_short() -> None:
    code = _code(CADDY)
    assert "@nokey" in code and "size({env.JARVIS_LOCAL_KEY}) < 16" in code
    # the guard is the first handle, so it wins over every other route
    assert code.index("handle @nokey") < code.index("handle @chat")
    assert 'respond "Offline gate has no key" 503' in code


def test_a_key_file_that_is_too_short_stops_the_script_before_caddy(
    tmp_path: Path, stubs: dict[str, Path]
) -> None:
    key_dir = tmp_path / "home" / ".lb"
    key_dir.mkdir(parents=True)
    (key_dir / "key").write_text("abc")
    r = _run(tmp_path, stubs)
    assert r.returncode != 0 and "key" in r.stderr.lower()
    assert not (stubs["log"] / "caddy_env").exists()
    assert not (stubs["log"] / "tailscale").exists()


def test_the_windows_script_refuses_a_short_key_and_never_resets_funnel() -> None:
    win = _code(WIN)
    assert "Length -lt 16" in win
    assert "funnel reset" not in win
    assert "funnel --https=8443 off" in win


def test_the_windows_folder_is_locked_down_before_the_key_is_written() -> None:
    win = _code(WIN)
    assert win.index("icacls") < win.index("WriteAllText")
    assert win.index("New-Item") < win.index("icacls")
