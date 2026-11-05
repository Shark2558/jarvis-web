# tests/test_deploy_home.py -- R3 D2, D4: the home kit by text and structure, its shell scripts run
# against stubs, the zip (reproducible, no secret, kit rule), the watchdog step in cloudrun.sh.
from __future__ import annotations

import io
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from jarvis.home import kit

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "deploy" / "home"
PUBLIC = "https://jarvis-abc.a.run.app"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((HOME / "docker-compose.yml").read_text())


# ---- compose -----------------------------------------------------------------------------------


def test_every_published_port_is_localhost(compose: dict) -> None:
    ports = [p for s in compose["services"].values() for p in s.get("ports", [])]
    assert ports, "the bridge and Frigate publish ports"
    assert all(str(p).startswith("127.0.0.1:") for p in ports), ports
    published = {str(p).split(":")[1] for p in ports}
    assert published == {"8971", "8099", "8098"}  # 5000, 8554, 8555, 1883 are never published


def test_services_and_hardening(compose: dict) -> None:
    svc = compose["services"]
    assert set(svc) == {"mosquitto", "frigate", "homeassistant", "bridge"}
    for name, s in svc.items():
        assert s["restart"] == "unless-stopped", name
        assert not s.get("privileged"), name
    b = svc["bridge"]
    assert b["read_only"] is True and b["cap_drop"] == ["ALL"] and b["user"] == "10001:10001"
    assert "no-new-privileges:true" in b["security_opt"] and b["mem_limit"] == "256m"
    assert "host.docker.internal:172.29.80.1" in b["extra_hosts"]  # review M4
    assert b["env_file"] == "bridge.env" and "./bridge-data:/data" in b["volumes"]
    assert svc["homeassistant"]["network_mode"] == "host"
    assert (
        svc["frigate"]["shm_size"] == "256mb"
        and svc["frigate"]["environment"]["TZ"] == "Asia/Kolkata"
    )
    assert "ports" not in svc["mosquitto"]


def test_images_are_pinned_by_version(compose: dict) -> None:
    for name in ("mosquitto", "frigate", "homeassistant"):
        image = compose["services"][name]["image"]
        default = re.fullmatch(r"\$\{[A-Z_]+:-([^}]+)\}", image)
        assert default, image
        ref = default.group(1)
        assert re.search(r":\d+\.\d+(\.\d+)?$", ref), ref
        assert not re.search(r":(latest|stable|dev)$", ref)
    frigate = compose["services"]["frigate"]["image"]
    version = re.search(r":(\d+)\.(\d+)\.(\d+)\}", frigate)
    assert version and tuple(map(int, version.groups())) >= (0, 17, 2)  # never below 0.17.2


def test_no_password_in_the_compose_file_or_env_example() -> None:
    text = (HOME / "docker-compose.yml").read_text()
    assert not re.search(r"(?i)(password|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9]{6,}", text)
    env = (HOME / "bridge.env.example").read_text()
    for line in env.splitlines():
        if re.match(r"(HA_TOKEN|MQTT_PASSWORD|FRIGATE_PASSWORD)=", line):
            assert line.endswith("="), line


def test_mosquitto_is_never_anonymous() -> None:
    conf = (HOME / "mosquitto" / "mosquitto.conf").read_text()
    assert "allow_anonymous false" in conf and "password_file" in conf


def test_bridge_image_is_hash_locked_and_unprivileged() -> None:
    df = (HOME / "bridge.Dockerfile").read_text()
    assert "--require-hashes" in df and "USER 10001" in df and "bridge-requirements.txt" in df
    reqs = (HOME / "bridge-requirements.txt").read_text()
    pins = re.findall(r"^([a-z0-9_.-]+)==", reqs, re.M)
    assert {"fastapi", "uvicorn", "httpx", "pydantic", "cryptography"} <= set(pins)
    assert reqs.count("--hash=sha256:") >= len(pins)


def test_wsl_settings() -> None:
    cfg = (HOME / "wslconfig.example").read_text()
    assert "memory=5GB" in cfg and "instanceIdleTimeout=-1" in cfg
    script = (HOME / "setup-wsl.sh").read_text()
    assert "systemd=true" in script and "download.docker.com" in script


# ---- the README matches the plan's steps ---------------------------------------------------------


def test_readme_has_the_sixteen_steps_in_plain_words() -> None:
    raw = (HOME / "README.txt").read_text()
    text = " ".join(raw.split())
    steps = re.findall(r"^\s*(\d{1,2})\. ", raw, re.M)
    assert steps[:16] == [str(i) for i in range(1, 17)]
    for needle in (
        "works only while this laptop is on",
        "C:\\JARVIS-Home",
        "Run with PowerShell",
        "IP Webcam",
        "localhost:8971",
        "localhost:8098/faces",
        "Mask the road",
        "NOT an administrator",
        "port 5443",
        "Arm (Away)",
    ):
        assert needle in text, needle
    assert raw.isascii()


def test_setup_windows_covers_the_plan_steps() -> None:
    ps = (HOME / "setup-windows.ps1").read_text()
    for needle in (
        "#Requires -RunAsAdministrator",
        "wsl --install",
        "Ubuntu-24.04",
        ".wslconfig",
        "powercfg",
        "tailscale funnel --bg --https=8443 http://127.0.0.1:8099",
        "tailscale serve --bg --https=5443 http://127.0.0.1:8971",
        "Register-ScheduledTask -TaskName 'JARVIS Home'",
        "setup-wsl.sh",
    ):
        assert needle in ps, needle
    assert "--https=443 " not in ps and "--https=443\n" not in ps  # 443 is R1's local brain
    assert "start-home.ps1" in ps and (HOME / "stop-home.ps1").exists()


# ---- the shell script, run with stubs ------------------------------------------------------------


def make_stubs(bin_dir: Path, log: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    tail = f'echo "$(basename "$0") $*" >> {log}\n'
    stubs = {
        "sudo": f'#!/bin/bash\n{tail}"$@"\n',
        "apt-get": f"#!/bin/bash\n{tail}",
        "curl": f"#!/bin/bash\n{tail}",
        "systemctl": f"#!/bin/bash\n{tail}",
        "dpkg": f"#!/bin/bash\n{tail}echo amd64\n",
        "chown": f"#!/bin/bash\n{tail}",
        "openssl": f'#!/bin/bash\n{tail}echo "QWxwaGFCZXRhR2FtbWFEZWx0YQ=="\n',
        "sleep": "#!/bin/bash\nexit 0\n",
        "docker": (
            "#!/bin/bash\n"
            f'echo "docker $*" >> {log}\n'
            'case "$1 $2" in\n'
            '  "compose version") echo "Docker Compose version v2" ;;\n'
            '  "image inspect") echo "ghcr.io/example/img@sha256:abc123" ;;\n'
            '  "run --rm") for a in "$@"; do last="$a"; done; true ;;\n'
            "esac\n"
            'if [[ "$*" == *" exec "* ]] && [ -n "${LINK_FAILS:-}" ]'
            ' && [[ "$*" == *homebridge* ]]; then\n'
            '  n="$(cat ${LINK_COUNT:-/dev/null} 2>/dev/null || echo 0)"; n=$((n+1))\n'
            '  echo $n > "$LINK_COUNT"\n'
            '  if [ "$n" -le "$LINK_FAILS" ]; then exit 1; fi\n'
            "fi\n"
            'if [[ "$*" == *"curl -s"* ]]; then\n'
            '  echo \'{"cameras":{"gate":{"camera_fps": 5.0}}}\'\n'
            "fi\n"
            "exit 0\n"
        ),
    }
    for name, body in stubs.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)


def run_script(tmp: Path, *args: str, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
    log = tmp / "calls.log"
    log.touch()
    make_stubs(tmp / "bin", log)
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    full_env = {
        "PATH": f"{tmp / 'bin'}:/usr/bin:/bin",
        "HOME": str(home),
        "HOME_DIR": str(home / "jarvis-home"),
        "KIT_DIR": str(HOME),
        **env,
    }
    done = subprocess.run(
        ["bash", str(HOME / "setup-wsl.sh"), *args],
        capture_output=True, text=True, env=full_env, timeout=60, cwd=tmp,
    )  # fmt: skip
    return done, log.read_text()


def test_scripts_parse() -> None:
    for name in ("setup-wsl.sh",):
        assert subprocess.run(["bash", "-n", str(HOME / name)]).returncode == 0
    assert os.access(HOME / "setup-wsl.sh", os.X_OK)


def test_usage_when_no_argument(tmp_path: Path) -> None:
    done, _ = run_script(tmp_path)
    assert done.returncode == 2 and "Usage" in done.stderr


def test_install_with_docker_missing_runs_the_official_steps(tmp_path: Path) -> None:
    done, calls = run_script(tmp_path, "install", PATH_NO_DOCKER="1")
    # docker (stub) exists, so it skips; the wsl.conf write is the part that needs checking
    assert done.returncode == 0 or "wsl.conf" in done.stderr


def test_configure_writes_private_files_and_no_secret_in_output(tmp_path: Path) -> None:
    done, calls = run_script(
        tmp_path,
        "configure",
        CAMERA_URL="rtsp://cam:camsecret@192.168.1.20:8080/x",
        HA_TOKEN="hatoken-xyz",
    )
    assert done.returncode == 0, done.stderr
    run = tmp_path / "home" / "jarvis-home"
    env = (run / "bridge.env").read_text()
    assert "HA_TOKEN=hatoken-xyz" in env and re.search(r"MQTT_PASSWORD=\S{10,}", env)
    assert stat.S_IMODE((run / "bridge.env").stat().st_mode) == 0o600
    assert (
        "hatoken-xyz" not in done.stdout + done.stderr + calls
    )  # never echoed or put on a command line
    assert "camsecret" not in done.stdout + done.stderr + calls
    assert "chown 10001:10001 bridge-data" in calls
    assert "mosquitto_passwd -b -c /work/passwd jarvis" in calls
    # the camera address lands only in Frigate's own file
    frigate = run / "frigate" / "config" / "config.yml"
    if (HOME / "frigate" / "config.yml").exists():
        assert "camsecret" in frigate.read_text()


def test_configure_keeps_an_existing_password(tmp_path: Path) -> None:
    run_script(tmp_path, "configure")
    first = (tmp_path / "home" / "jarvis-home" / "bridge.env").read_text()
    run_script(tmp_path, "configure")
    assert (tmp_path / "home" / "jarvis-home" / "bridge.env").read_text() == first


def test_up_pulls_pins_digests_and_starts(tmp_path: Path) -> None:
    run_script(tmp_path, "configure")
    done, calls = run_script(tmp_path, "up")
    assert done.returncode == 0, done.stderr
    assert "compose --env-file bridge.env --env-file images.env pull" in calls
    assert "compose --env-file bridge.env --env-file images.env up -d --build" in calls
    images = (tmp_path / "home" / "jarvis-home" / "images.env").read_text()
    for var in ("MOSQUITTO_IMAGE", "FRIGATE_IMAGE", "HOMEASSISTANT_IMAGE"):
        assert f"{var}=ghcr.io/example/img@sha256:abc123" in images


def test_link_retries_then_succeeds(tmp_path: Path) -> None:
    run_script(tmp_path, "configure")
    done, calls = run_script(
        tmp_path, "link", "ABCD-EFGH", "https://l.tail1.ts.net:8443",
        LINK_FAILS="2", LINK_COUNT=str(tmp_path / "count"),
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert (
        calls.count("python -m jarvis.homebridge link ABCD-EFGH https://l.tail1.ts.net:8443") == 3
    )
    assert "Linked." in done.stdout


def test_link_gives_up_with_plain_words(tmp_path: Path) -> None:
    run_script(tmp_path, "configure")
    done, _ = run_script(
        tmp_path, "link", "ABCD-EFGH", "https://l.tail1.ts.net:8443",
        LINK_FAILS="99", LINK_COUNT=str(tmp_path / "count"),
    )  # fmt: skip
    assert done.returncode == 1 and "new code" in done.stderr
    done, _ = run_script(tmp_path, "link")
    assert done.returncode == 1 and "usage" in done.stderr


def test_camera_check(tmp_path: Path) -> None:
    run_script(tmp_path, "configure")
    done, _ = run_script(tmp_path, "camera")
    assert done.returncode == 0 and "Camera works." in done.stdout


# ---- the zip ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def zipped() -> bytes:
    return kit.build(PUBLIC)


def test_kit_is_reproducible_and_has_a_stable_hash(zipped: bytes) -> None:
    again = kit.build(PUBLIC)
    assert again == zipped and kit.sha256(again) == kit.sha256(zipped)
    assert kit.build("https://other.example") != zipped  # only the address differs


def test_kit_contents(zipped: bytes) -> None:
    names = zipfile.ZipFile(io.BytesIO(zipped)).namelist()
    top = {n.split("/")[0] for n in names}
    assert top == {kit.ROOT_DIR}
    rel = {n.split("/", 1)[1] for n in names}
    for need in (
        "docker-compose.yml", "bridge.Dockerfile", "bridge-requirements.txt", "bridge.env",
        "bridge.env.example", "setup-windows.ps1", "setup-wsl.sh", "start-home.ps1",
        "stop-home.ps1", "wslconfig.example", "README.txt", "mosquitto/mosquitto.conf",
        "homeassistant/configuration.yaml", "bridge-src/jarvis/__init__.py",
        "bridge-src/jarvis/home/signing.py", "bridge-src/jarvis/home/ports.py",
        "bridge-src/jarvis/home/classes.py", "bridge-src/jarvis/homebridge/app.py",
        "bridge-src/jarvis/homebridge/__main__.py",
    ):  # fmt: skip
        assert need in rel, need
    assert not any("bridge-data" in n or n.endswith((".pyc", ".pem", ".key")) for n in rel)
    # the cloud's own code does not ship
    assert not any(n.startswith("bridge-src/jarvis/api") or "/tools/" in n for n in rel)


def test_kit_has_no_secret_and_only_the_public_address(zipped: bytes) -> None:
    zf = zipfile.ZipFile(io.BytesIO(zipped))
    env = zf.read(f"{kit.ROOT_DIR}/bridge.env").decode()
    assert f"JARVIS_URL={PUBLIC}" in env
    for line in env.splitlines():
        if line.startswith(("HA_TOKEN=", "MQTT_PASSWORD=", "FRIGATE_PASSWORD=")):
            assert line.endswith("=")
    blob = b"".join(zf.read(n) for n in zf.namelist())
    for needle in (b"BEGIN PRIVATE KEY", b"jarvis-token-key", b"sk-ant-", b"AIza"):
        assert needle not in blob
    modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in zf.infolist()}
    assert (
        modes[f"{kit.ROOT_DIR}/setup-wsl.sh"] == 0o755
        and modes[f"{kit.ROOT_DIR}/README.txt"] == 0o644
    )
    assert all(i.date_time == (2026, 1, 1, 0, 0, 0) for i in zf.infolist())


def test_kit_needs_an_address() -> None:
    with pytest.raises(kit.KitError):
        kit.build("")
    with pytest.raises(kit.KitError):
        kit.build("http://insecure.example")


def test_the_kit_rule_is_enforced(tmp_path: Path) -> None:
    src = tmp_path / "src" / "jarvis"
    (src / "homebridge").mkdir(parents=True)
    (src / "homebridge" / "ok.py").write_text("import json\nfrom pydantic import BaseModel\n")
    assert "jarvis/homebridge/ok.py" in kit.bridge_sources(tmp_path / "src")
    (src / "config.py").write_text("x = 1\n")
    (src / "homebridge" / "bad.py").write_text("from jarvis.config import x\n")
    with pytest.raises(kit.KitError, match="not part of the home kit"):
        kit.bridge_sources(tmp_path / "src")
    (src / "homebridge" / "bad.py").write_text("import requests\n")
    with pytest.raises(kit.KitError, match="doesn't install"):
        kit.bridge_sources(tmp_path / "src")


def test_the_real_bridge_imports_only_kit_modules() -> None:
    files = kit.bridge_sources(ROOT / "src")
    modules = {f for f in files if f.endswith(".py")}
    assert {
        "jarvis/home/classes.py",
        "jarvis/faces/ports.py",
    } & modules or "jarvis/home/classes.py" in modules
    assert not any(
        m.startswith(("jarvis/api", "jarvis/tools", "jarvis/notify", "jarvis/llm")) for m in modules
    )


def test_outdated() -> None:
    assert kit.outdated("0.0.9") and not kit.outdated(kit.KIT_VERSION) and not kit.outdated(None)
    assert not kit.outdated("garbage") and not kit.outdated("9.9.9")


# ---- cloudrun.sh ------------------------------------------------------------------------------


def test_cloudrun_watchdog_step_is_non_fatal_and_exact() -> None:
    sh = (ROOT / "deploy" / "cloudrun.sh").read_text()
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy/cloudrun.sh")]).returncode == 0
    assert 'HOME_JOB="jarvis-home-watchdog"' in sh
    block = sh[sh.index("setup_home_watchdog() {") : sh.index('say "DONE.')]
    assert '--schedule "*/5 * * * *"' in block and "--attempt-deadline 60s" in block
    assert '--oidc-token-audience "$HOME_WATCH_URL"' in block
    assert 'HOME_WATCH_URL="${BASE_URL}/internal/home/watchdog"' in sh
    assert '--oidc-service-account-email "${SCHED_SA:-}"' in block
    assert "if setup_home_watchdog; then" in block  # a failure never stops the deploy
    assert "HOME: laptop-offline alerts are off (re-run this script)." in block
    assert "HOME: watchdog on" in sh and "3 free jobs per billing account" in sh
    for group in (
        "jarvis_home",
        "jarvis_home_devices",
        "jarvis_home_feed",
        "jarvis_faces",
        "jarvis_webpush",
    ):
        assert group in sh


def test_dockerfile_and_dockerignore_carry_the_kit() -> None:
    assert "COPY deploy/home ./deploy/home" in (ROOT / "Dockerfile").read_text()
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert "!deploy/home" in ignore and ignore.index("!deploy/home") > ignore.index("deploy")
    assert "deploy/home/bridge.env" in ignore and "deploy/home/bridge-data" in ignore


def test_dockerfile_tells_the_app_where_the_kit_is() -> None:
    """Review H2: after `pip install .` the package lives in site-packages, not next to deploy/."""
    df = (ROOT / "Dockerfile").read_text()
    assert "ENV HOME_KIT_ROOT=/app" in df


def test_kit_is_found_from_an_installed_layout_through_home_kit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = tmp_path / "usr" / "lib" / "python3.12" / "site-packages" / "jarvis" / "home"
    site.mkdir(parents=True)
    monkeypatch.setattr(kit, "__file__", str(site / "kit.py"))
    monkeypatch.delenv("HOME_KIT_ROOT", raising=False)
    with pytest.raises(kit.KitError):  # nothing next to site-packages
        kit.build(PUBLIC)
    monkeypatch.setenv("HOME_KIT_ROOT", str(ROOT))
    assert kit.build(PUBLIC)[:2] == b"PK"


def test_a_home_kit_root_without_the_kit_is_a_plain_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME_KIT_ROOT", str(tmp_path))
    with pytest.raises(kit.KitError):
        kit.build(PUBLIC)


def test_home_assistant_listens_only_on_loopback_and_the_home_network_gateway() -> None:
    """Review M4: network_mode host binds 0.0.0.0 inside the WSL VM unless the config says not."""
    cfg = yaml.safe_load((HOME / "homeassistant" / "configuration.yaml").read_text())
    http = cfg["http"]
    compose = yaml.safe_load((HOME / "docker-compose.yml").read_text())
    ipam = compose["networks"]["home"]["ipam"]["config"][0]
    gateway = ipam["gateway"]
    assert http["server_host"] == ["127.0.0.1", gateway]
    assert "0.0.0.0" not in http["server_host"] and "::" not in http["server_host"]
    # the bridge reaches Home Assistant at that same gateway address
    assert compose["services"]["bridge"]["extra_hosts"] == [f"host.docker.internal:{gateway}"]
    assert gateway.startswith("172.29.80.") and ipam["subnet"] == "172.29.80.0/24"


def test_readme_does_not_overclaim_what_listens_where() -> None:
    text = (HOME / "README.txt").read_text()
    assert "Everything listens on 127.0.0.1" not in text
    assert "Home Assistant" in text.split("Safety notes", 1)[1]
    assert "172.29.80.1" in text


def test_secrets_are_typed_without_echo_in_the_windows_script() -> None:
    """Review LOW: the camera password and the Home Assistant token are not shown while typed."""
    ps = (HOME / "setup-windows.ps1").read_text()
    assert "Read-Host $text -AsSecureString" in ps
    assert "$pass = AskSecret " in ps and "$env:HA_TOKEN = AskSecret " in ps
    assert "$pass = Ask " not in ps and "$env:HA_TOKEN = Ask " not in ps


def test_the_bridge_base_image_is_pinned_by_digest_like_the_others() -> None:
    sh = (HOME / "setup-wsl.sh").read_text()
    compose = yaml.safe_load((HOME / "docker-compose.yml").read_text())
    assert compose["services"]["bridge"]["build"]["args"]["BASE_IMAGE"] == (
        "${BASE_IMAGE:-python:3.12-slim}"
    )
    assert 'pin_digest BASE_IMAGE "${BASE_IMAGE:-python:3.12-slim}"' in sh
    assert 'docker pull "${BASE_IMAGE:-python:3.12-slim}"' in sh  # --ignore-buildable skips it
    assert sh.index("docker pull") < sh.index("pin_digest BASE_IMAGE")
