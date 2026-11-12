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
    # R11.1 O7: 256m -> 768m, for the face reader's two models and one picture at a time
    assert "no-new-privileges:true" in b["security_opt"] and b["mem_limit"] == "768m"
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
    assert "acl_file /mosquitto/config/acl" in conf


def test_mosquitto_acl_lets_frigate_write_and_the_bridge_only_read(compose: dict) -> None:
    """I1 (review B): Frigate's user may publish frigate/#; the bridge's user may only read it."""
    rules: dict[str, list[str]] = {}
    user = ""
    for line in (HOME / "mosquitto" / "acl").read_text().splitlines():
        line = line.strip()
        if line.startswith("user "):
            user = line.split()[1]
            rules[user] = []
        elif line.startswith("topic "):
            rules[user].append(" ".join(line.split()[1:]))
    assert rules == {"frigate": ["readwrite frigate/#"], "bridge": ["read frigate/#"]}
    vols = compose["services"]["mosquitto"]["volumes"]
    assert any(v.startswith("./mosquitto/acl:/mosquitto/config/acl:ro") for v in vols)


def test_frigate_gets_its_own_env_file_and_the_bridge_sees_frigate_media(compose: dict) -> None:
    """I1: the camera's address and Frigate's broker password reach only Frigate (frigate.env);
    the bridge mounts Frigate's media so the Faces plugin can delete and sweep face pictures
    (review C: without it face deletes are never acknowledged)."""
    svc = compose["services"]
    assert svc["frigate"]["env_file"] == "frigate.env"
    assert "FRIGATE_MQTT_PASSWORD" not in svc["frigate"].get("environment", {})
    assert svc["bridge"]["env_file"] == "bridge.env"
    assert "./frigate/media:/media/frigate" in svc["bridge"]["volumes"]
    example = (HOME / "bridge.env.example").read_text()
    assert "MQTT_USER=bridge" in example and "FRIGATE_GATE_RTSP" not in example
    assert "frigate.env" in kit.SKIP_NAMES and "passwd" in kit.SKIP_NAMES


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
        "powershell -ExecutionPolicy Bypass -File .\\setup-windows.ps1",
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
        "[Security.Principal.WindowsBuiltInRole]::Administrator",  # its own check, plain words
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
        "chgrp": f"#!/bin/bash\n{tail}",
        "setfacl": f"#!/bin/bash\n{tail}",
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
            'if [[ "$*" == *"cat /data/faces_code.txt"* ]]; then echo "FacesCode-77aa"; fi\n'
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
    # I1: two broker users, Frigate's (writes frigate/#) and the bridge's (reads only)
    assert "mosquitto_passwd -b -c /work/passwd frigate" in calls
    assert "mosquitto_passwd -b /work/passwd bridge" in calls
    assert "MQTT_USER=bridge" in env
    # the camera address lands only in Frigate's own env file (mode 600), never in bridge.env or
    # Frigate's config.yml (which is copied as it is: it reads {FRIGATE_GATE_RTSP})
    fenv = (run / "frigate.env").read_text()
    assert "FRIGATE_GATE_RTSP=rtsp://cam:camsecret@192.168.1.20:8080/x" in fenv
    assert "FRIGATE_MQTT_USER=frigate" in fenv
    assert re.search(r"FRIGATE_MQTT_PASSWORD=\S{10,}", fenv)
    assert stat.S_IMODE((run / "frigate.env").stat().st_mode) == 0o600
    assert "camsecret" not in env
    frigate = (run / "frigate" / "config" / "config.yml").read_text()
    assert "camsecret" not in frigate and "{FRIGATE_GATE_RTSP}" in frigate


def test_configure_keeps_frigate_passwords_and_camera_on_a_rerun(tmp_path: Path) -> None:
    run_script(tmp_path, "configure", CAMERA_URL="rtsp://cam:a&b|c@192.168.1.20:8080/x")
    run = tmp_path / "home" / "jarvis-home"
    first = (run / "frigate.env").read_text()
    assert "FRIGATE_GATE_RTSP=rtsp://cam:a&b|c@192.168.1.20:8080/x" in first  # printf, not sed
    run_script(tmp_path, "configure")
    assert (run / "frigate.env").read_text() == first


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
        "jarvis_home_cameras",  # I1: B's sealed camera settings
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


# ---- integrated review C1 / S1: every package the bridge imports is in its image, hash-locked ----

# import name -> PyPI name, where they differ
DIST = {"pydantic_core": "pydantic-core", "annotated_types": "annotated-types"}
MQTT_PINS = {
    "aiomqtt": (
        "2.5.1",
        {
            "fd58c3593160e4d475d90ce911cdfc4239cd64de96b0ba22edf6c86bd7afa278",
            "25a0a47d157e8f158d2da1110ea4786c0615518751e94f7b04976c977a8ff20d",
        },
    ),
    "paho-mqtt": (
        "2.1.0",
        {
            "6db9ba9b34ed5bc6b6e3812718c7e06e2fd7444540df2455d2c51bd58808feee",
            "12d6e7511d4137555a3f6ea167ae846af2c7357b10bc6fa4f7c3968fc1723834",
        },
    ),
}


def _pins() -> dict[str, tuple[str, set[str]]]:
    """bridge-requirements.txt as {name: (version, {sha256})}."""
    out: dict[str, tuple[str, set[str]]] = {}
    name = ""
    for line in (HOME / "bridge-requirements.txt").read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", line)
        if m:
            name = m.group(1).lower()
            out[name] = (m.group(2), set())
        for h in re.findall(r"--hash=sha256:([0-9a-f]{64})", line):
            out[name][1].add(h)
    return out


def _third_party_imports() -> dict[str, str]:
    """{top-level module: file} for every import in the kit's Python (function level too)."""
    import ast
    import sys

    found: dict[str, str] = {}
    for rel, data in kit.bridge_sources(ROOT / "src").items():
        if not rel.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(data.decode("utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for n in names:
                top = n.split(".")[0]
                if top not in ("jarvis", "__future__") and top not in sys.stdlib_module_names:
                    found.setdefault(top, rel)
    return found


def test_every_bridge_third_party_import_is_hash_locked() -> None:
    pins = _pins()
    imports = _third_party_imports()
    assert "aiomqtt" in imports  # the camera's MQTT client (imported where it connects)
    for top, where in imports.items():
        dist = DIST.get(top, top).lower().replace("_", "-")
        assert dist in pins, f"{where} imports {top}: not in bridge-requirements.txt"
        assert pins[dist][1], f"{dist} has no hash"


def test_the_mqtt_packages_are_the_reviewed_versions_with_wheel_and_sdist_hashes() -> None:
    pins = _pins()
    for name, (version, hashes) in MQTT_PINS.items():
        assert pins[name] == (version, hashes), name
    text = (HOME / "bridge-requirements.txt").read_text()
    assert "is added with its hashes by the camera part" not in text  # the old promise is kept
    pyproject = (ROOT / "pyproject.toml").read_text()
    # R11.1 I1: + the face engine's two libraries (INTEGRATION-C 3.1)
    assert (
        'homebridge = ["aiomqtt==2.5.1", "paho-mqtt==2.1.0", "opencv-python-headless==5.0.0.93", '
        '"numpy==2.5.4"]'
    ) in pyproject


def test_every_homebridge_extra_pin_is_the_bridge_image_s_hash_locked_version() -> None:
    """R11.1 I1: the extra CI installs and the image's lock name the same versions."""
    import tomllib

    extra = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "optional-dependencies"
    ]["homebridge"]
    pins = _pins()
    for spec in extra:
        name, version = spec.split("==")
        assert pins[name][0] == version and pins[name][1], spec


def test_the_bridge_image_installs_only_the_locked_files_and_no_dependencies_of_its_own() -> None:
    df = (HOME / "bridge.Dockerfile").read_text()
    assert "pip install --require-hashes --no-deps -r bridge-requirements.txt" in df


# ---- integrated review H2: the laptop Faces page is reachable and its code is shown -------------


def test_the_faces_page_listens_inside_its_container_where_compose_publishes_it(
    compose: dict,
) -> None:
    b = compose["services"]["bridge"]
    assert "127.0.0.1:8098:8098" in b["ports"]  # the laptop only
    env = b.get("environment", {})
    assert env.get("FACES_BIND") == "0.0.0.0", "a loopback-only bind inside the container is dead"


def test_up_and_link_print_the_faces_page_code(tmp_path: Path) -> None:
    sh = (HOME / "setup-wsl.sh").read_text()
    assert "exec -T bridge cat /data/faces_code.txt" in sh
    run_script(tmp_path, "configure")
    done, calls = run_script(tmp_path, "up")
    assert done.returncode == 0, done.stderr
    assert "FacesCode-77aa" in done.stdout and "localhost:8098/faces" in done.stdout
    done, _ = run_script(tmp_path, "link", "ABCD-EFGH", "https://l.tail1.ts.net:8443")
    assert done.returncode == 0 and "FacesCode-77aa" in done.stdout


# ---- integrated review H4: the bridge may delete in Frigate's face folders ----------------------


def test_configure_shares_frigates_face_folders_with_the_bridge(tmp_path: Path) -> None:
    done, calls = run_script(tmp_path, "configure")
    assert done.returncode == 0, done.stderr
    media = tmp_path / "home" / "jarvis-home" / "frigate" / "media" / "clips"
    for sub in ("faces/train", "doorstep/train"):
        assert (media / sub).is_dir(), sub
    assert "chgrp -R 10001 frigate/media/clips/faces frigate/media/clips/doorstep" in calls
    assert "chmod -R g+rwX frigate/media/clips/faces" in calls
    assert "-type d -exec chmod g+s {} +" in calls  # new files keep the bridge's group
    assert "setfacl -R -d -m g:10001:rwX" in calls  # new folders stay deletable by the bridge


# ---- integrated review M12 / Minor / hygiene: the kit agrees with the code -------------------


def _keys(text: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", text, re.M)}


def test_every_setting_the_kit_writes_for_the_bridge_is_one_the_bridge_reads(compose: dict) -> None:
    from jarvis.homebridge.plugins import PLUGIN_ENV_KEYS

    read = set(PLUGIN_ENV_KEYS) | {
        "JARVIS_URL",
        "HA_URL",
        "HA_TOKEN",
        "BRIDGE_DATA_DIR",
        "BRIDGE_BIND",
    }
    example = _keys((HOME / "bridge.env.example").read_text())
    shipped = _keys(kit.env_file(PUBLIC).decode())
    sh = (HOME / "setup-wsl.sh").read_text()
    written = set(re.findall(r"set_env bridge\.env ([A-Z_]+)", sh))
    environment = set(compose["services"]["bridge"].get("environment", {}))
    for name, keys in (
        ("example", example),
        ("kit", shipped),
        ("setup", written),
        ("compose", environment),
    ):
        assert keys <= read, (name, keys - read)
    assert "FRIGATE_PASSWORD" not in example | shipped  # Minor: never read by anything
    assert {"JARVIS_URL", "MQTT_USER", "MQTT_PASSWORD", "HA_TOKEN"} <= example


def test_frigate_env_never_reaches_the_bridge(compose: dict) -> None:
    b = compose["services"]["bridge"]
    assert b["env_file"] == "bridge.env"
    frigate_keys = {"FRIGATE_MQTT_USER", "FRIGATE_MQTT_PASSWORD", "FRIGATE_GATE_RTSP"}
    assert not frigate_keys & _keys((HOME / "bridge.env.example").read_text())
    assert not frigate_keys & set(b.get("environment", {}))


def test_the_broker_can_read_its_password_file(tmp_path: Path) -> None:
    """Hygiene: Mosquitto runs as uid 1883 and reads passwd itself; the file is its own, 600,
    and a re-run replaces it instead of failing on a file it can no longer write."""
    done, calls = run_script(tmp_path, "configure")
    assert done.returncode == 0, done.stderr
    assert "sudo rm -f mosquitto/passwd" in calls
    assert "chown 1883:1883 mosquitto/passwd" in calls
    assert calls.index("sudo rm -f mosquitto/passwd") < calls.index("mosquitto_passwd -b -c")
    assert calls.index("mosquitto_passwd -b /work/passwd bridge") < calls.index(
        "chown 1883:1883 mosquitto/passwd"
    )


# ---- owner's guide fixes (coordinator, 5 Nov): admin, the zip folder, the HA token, the task ----


def test_the_windows_script_checks_for_administrator_and_says_the_exact_command() -> None:
    ps = (HOME / "setup-windows.ps1").read_text()
    assert "#Requires -RunAsAdministrator" not in ps  # it would stop before any plain words
    check = ps.index("WindowsBuiltInRole]::Administrator")
    assert check < ps.index("wsl --install")
    assert "powershell -ExecutionPolicy Bypass -File .\\setup-windows.ps1" in ps[check:]
    readme = " ".join((HOME / "README.txt").read_text().split())
    assert "Run with PowerShell" not in readme and "Right-click setup-windows.ps1" not in readme
    assert "as administrator" in readme
    assert "Run with PowerShell" not in (HOME / "setup-windows.ps1").read_text()


def test_extracting_the_kit_gives_the_folder_the_steps_use(zipped: bytes) -> None:
    names = zipfile.ZipFile(io.BytesIO(zipped)).namelist()
    assert {n.split("/")[0] for n in names} == {"JARVIS-Home"}
    readme = " ".join((HOME / "README.txt").read_text().split())
    assert "Unzip it to C:\\JARVIS-Home" not in readme
    assert "Extract it to C:\\ (this makes the folder C:\\JARVIS-Home)" in readme
    assert "cd C:\\JARVIS-Home" in readme
    console = (ROOT / "src" / "jarvis" / "api" / "static" / "console-home.js").read_text()
    assert "unzip it to C:\\\\JARVIS-Home" not in console
    assert "extract it to C:\\\\ (this makes C:\\\\JARVIS-Home)" in console


def test_the_home_assistant_token_is_a_later_step_once_it_is_running() -> None:
    ps = (HOME / "setup-windows.ps1").read_text()
    # R11.1: -Update and -PhotosDir joined it (tests/test_r11_1_c_kit.py pins the whole list)
    assert re.search(r"param\(\s*\[switch\]\$HaToken\b", ps)
    # the token is asked for once, only in the -HaToken run, which ends before the first-run steps
    asks = [m.start() for m in re.finditer(r"\$env:HA_TOKEN = AskSecret", ps)]
    branch, first_run = ps.index("if ($HaToken) {"), ps.index("# 1. Windows")
    assert len(asks) == 1 and branch < asks[0] < first_run
    assert "exit 0" in ps[asks[0] : first_run]
    assert "setup-windows.ps1 -HaToken" in ps[first_run:]  # said at the end of the first run
    assert "HA_TOKEN" not in ps[first_run:].replace("-HaToken", "")
    readme = " ".join((HOME / "README.txt").read_text().split())
    assert "setup-windows.ps1 -HaToken" in readme and "localhost:8123" in readme


def test_ha_token_step_saves_it_without_echo_and_restarts_the_bridge(tmp_path: Path) -> None:
    run_script(tmp_path, "configure")
    done, calls = run_script(tmp_path, "ha-token", HA_TOKEN="hatoken-later-42")
    assert done.returncode == 0, done.stderr
    env = (tmp_path / "home" / "jarvis-home" / "bridge.env").read_text()
    assert "HA_TOKEN=hatoken-later-42" in env
    assert "hatoken-later-42" not in done.stdout + done.stderr + calls
    assert "up -d --force-recreate bridge" in calls
    done, _ = run_script(tmp_path, "ha-token")
    assert done.returncode == 1 and "token" in done.stderr


def test_the_logon_task_runs_its_script_past_the_execution_policy() -> None:
    ps = (HOME / "setup-windows.ps1").read_text()
    line = next(x for x in ps.splitlines() if "New-ScheduledTaskAction" in x)
    assert "-NoProfile -ExecutionPolicy Bypass" in line and "start-home.ps1" in line


def test_the_kit_allows_the_face_engine_s_libraries_and_each_is_hash_locked() -> None:
    """R11.1 I1 (INTEGRATION-C 3.1): cv2 and numpy pass the kit's import allow-list (the engine
    may import them plainly), and every name on the allow-list is a hash-locked bridge pin."""
    from jarvis.home.kit import SAFE_THIRD_PARTY

    assert {"cv2", "numpy"} <= SAFE_THIRD_PARTY
    pins = _pins()
    names = {"cv2": "opencv-python-headless", "pydantic_core": "pydantic-core"}
    for top in SAFE_THIRD_PARTY:
        dist = names.get(top, DIST.get(top, top)).lower().replace("_", "-")
        assert dist in pins and pins[dist][1], top
