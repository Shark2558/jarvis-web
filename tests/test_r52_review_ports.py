# tests/test_r52_review_ports.py -- R5.2 combined review (the Workshop's notes: the port clash).
# The home bridge (deploy/home/setup-windows.ps1) and the offline brain (deploy/local-brain/start-*)
# both took Tailscale Funnel's port 8443: on one laptop the brain's script replaced the bridge's
# door, and stopping the brain closed it. Each part now has its own Funnel port, as R3's plan D3
# and `jarvis.home.client` already said (the bridge 8443, the brain 443) and R5.2's kit 10000;
# every script refuses a port that already serves something else, before it starts anything.
from __future__ import annotations

import re
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.home.models import BRIDGE_PORT
from jarvis.localspeech import protocol as p
from jarvis.offline.config import ALLOWED_PORTS

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "deploy" / "local-brain"
BRIDGE_WIN = ROOT / "deploy" / "home" / "setup-windows.ps1"
KIT = ROOT / "deploy" / "local-speech"
BRAIN_PORT = 443  # R3 plan D3: "R1's local brain keeps 443"; jarvis.home.client refuses it
NAME = "my-laptop.tail1234.ts.net"


def _code(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _funnel_ports(text: str) -> set[int]:
    return {int(m) for m in re.findall(r"funnel --bg --https=(\d+)", _code(text))}


# ---- one door each ---------------------------------------------------------------------------
def test_each_laptop_part_has_its_own_funnel_port() -> None:
    bridge = _funnel_ports(BRIDGE_WIN.read_text())
    brain_unix = _funnel_ports((BRAIN / "start-unix.sh").read_text())
    brain_win = _funnel_ports((BRAIN / "start-windows.ps1").read_text())
    assert bridge == {BRIDGE_PORT} == {8443}
    assert brain_unix == brain_win == {BRAIN_PORT}
    assert p.FUNNEL_PORT == 10000
    assert len({BRIDGE_PORT, BRAIN_PORT, p.FUNNEL_PORT}) == 3
    assert {BRIDGE_PORT, BRAIN_PORT, p.FUNNEL_PORT} == set(ALLOWED_PORTS)


def test_the_brain_closes_only_its_own_port() -> None:
    for name in ("start-unix.sh", "start-windows.ps1"):
        code = _code((BRAIN / name).read_text())
        assert f"funnel --https={BRAIN_PORT} off" in code, name
        assert "--https=8443" not in code and "reset" not in code, name


@pytest.mark.parametrize(
    ("path", "mine", "before"),
    [
        (BRAIN / "start-windows.ps1", "http://127.0.0.1:11435", "Start-Process -FilePath 'caddy'"),
        (BRIDGE_WIN, "http://127.0.0.1:8099", "tailscale funnel --bg --https=8443"),
    ],
)
def test_the_windows_scripts_refuse_a_funnel_port_that_serves_something_else(
    path: Path, mine: str, before: str
) -> None:
    code = _code(path.read_text())
    assert "function Test-FunnelTaken" in code and "funnel status --json" in code
    assert f"'{mine}'" in code  # what counts as its own door (a re-run of itself)
    check = code.index("if (Test-FunnelTaken")
    refusal = code[check : code.index(before)]
    assert check < code.index(before) and ("exit 1" in refusal or "throw" in refusal)


# ---- start-unix.sh (the brain), run against stubs ----------------------------------------------
@pytest.fixture
def brain(tmp_path: Path) -> dict[str, Path]:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", 11435)) == 0:
            pytest.skip("port 11435 is in use on this machine")
    bin_dir, log = tmp_path / "bin", tmp_path / "log"
    bin_dir.mkdir()
    log.mkdir()

    def stub(name: str, body: str) -> None:
        path = bin_dir / name
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    stub("curl", "exit 0\n")
    stub("ollama", "exit 0\n")
    stub("caddy", f'echo started > "{log}/caddy"\nexit 0\n')
    stub(
        "tailscale",
        f'echo "$@" >> "{log}/tailscale"\n'
        'if [ "$1 $2" = "funnel status" ]; then cat "$(dirname "$0")/status" 2>/dev/null; fi\n'
        "exit 0\n",
    )
    return {"bin": bin_dir, "log": log, "home": tmp_path / "home"}


def _brain(stubs: dict[str, Path], status: str) -> subprocess.CompletedProcess[str]:
    (stubs["bin"] / "status").write_text(status)
    stubs["home"].mkdir(exist_ok=True)
    env = {
        "PATH": f"{stubs['bin']}:/usr/bin:/bin",
        "HOME": str(stubs["home"]),
        "JARVIS_LOCAL_BRAIN_DIR": str(stubs["home"] / ".lb"),
        "JARVIS_OLLAMA_WAIT_S": "1",
    }
    return subprocess.run(
        ["bash", str(BRAIN / "start-unix.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


BRIDGE_DOOR = f"https://{NAME}:8443 (Funnel on)\n|-- / proxy http://127.0.0.1:8099\n"
KIT_DOOR = f"https://{NAME}:10000 (Funnel on)\n|-- / proxy http://127.0.0.1:11436\n"


def test_the_brain_leaves_the_bridges_door_alone_and_prints_its_own_address(
    brain: dict[str, Path],
) -> None:
    mine = f"https://{NAME} (Funnel on)\n|-- / proxy http://127.0.0.1:11435\n"
    r = _brain(brain, BRIDGE_DOOR + KIT_DOOR + mine)
    assert r.returncode == 0, r.stderr
    ts = (brain["log"] / "tailscale").read_text()
    assert f"funnel --bg --https={BRAIN_PORT} 11435" in ts
    assert "8443" not in ts and "10000" not in ts  # never opened, never closed
    assert f"funnel --https={BRAIN_PORT} off" in ts
    assert f"Address: https://{NAME}\n" in r.stdout  # its own door, not the bridge's :8443


def test_the_brain_refuses_port_443_when_it_serves_something_else(brain: dict[str, Path]) -> None:
    other = f"https://{NAME} (Funnel on)\n|-- / proxy http://127.0.0.1:11436\n"
    r = _brain(brain, BRIDGE_DOOR + other)
    assert r.returncode != 0 and "already serves something else" in r.stderr
    assert not (brain["log"] / "caddy").exists()
    ts = (brain["log"] / "tailscale").read_text()
    assert "--bg" not in ts and " off" not in ts  # nothing opened, nothing of the other closed


# ---- start-kit.sh: port 443 has no ":443" in Funnel's status ------------------------------------
@pytest.fixture
def kit(tmp_path: Path) -> dict[str, Path]:
    for port in (p.GATE_PORT, p.SERVER_PORT):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                pytest.skip(f"port {port} is in use on this machine")
    bin_dir, log = tmp_path / "bin", tmp_path / "log"
    bin_dir.mkdir()
    log.mkdir()

    def stub(path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    listen = (
        "import socket, time; s = socket.socket(); "
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
        f"s.bind(('127.0.0.1', {p.SERVER_PORT})); s.listen(); time.sleep(20)"
    )
    stub(tmp_path / "kit" / "venv" / "bin" / "python", f'exec "{sys.executable}" -c "{listen}"\n')
    stub(bin_dir / "caddy", f'echo started > "{log}/caddy"\nexit 0\n')
    stub(
        bin_dir / "tailscale",
        f'echo "$@" >> "{log}/tailscale"\n'
        'if [ "$1 $2" = "funnel status" ]; then cat "$(dirname "$0")/status" 2>/dev/null; fi\n'
        "exit 0\n",
    )
    return {"bin": bin_dir, "log": log, "kit": tmp_path / "kit"}


def test_the_kit_refuses_port_443_while_the_brain_holds_it(kit: dict[str, Path]) -> None:
    brain_door = f"https://{NAME} (Funnel on)\n|-- / proxy http://127.0.0.1:11435\n"
    (kit["bin"] / "status").write_text(BRIDGE_DOOR + brain_door)
    env = {
        "PATH": f"{kit['bin']}:/usr/bin:/bin",
        "HOME": str(kit["kit"].parent),
        "JARVIS_SPEECH_KIT_DIR": str(kit["kit"]),
        "JARVIS_SPEECH_KIT_WAIT_S": "5",
        "JARVIS_SPEECH_KIT_HTTPS_PORT": "443",
    }
    r = subprocess.run(
        ["bash", str(KIT / "start-kit.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode != 0 and "already serves something else" in r.stderr
    assert not (kit["log"] / "caddy").exists()
    assert "--bg" not in (kit["log"] / "tailscale").read_text()


def test_the_kits_scripts_name_each_parts_port() -> None:
    for name in ("start-kit.ps1", "start-kit.sh", "README.md"):
        text = (KIT / name).read_text()
        assert "the offline brain keeps 8443" not in text, name
    readme = " ".join((KIT / "README.md").read_text().split())
    assert "home bridge" in readme and "8443" in readme and "443" in readme
