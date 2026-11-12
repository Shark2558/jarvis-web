# tests/test_r11_1_c_kit.py -- R11.1 O7: the home kit carries the laptop's face reader. The two
# new packages are hash-locked for the bridge image, the two model files are pinned (the kit lists
# name, size, hash, licence and source; the setup downloads and checks them, the bridge checks
# again), the bridge gets a read-only photo folder that is off until PHOTOS_DIR is set, and the
# kit can be UPDATED without losing this laptop's own settings.
from __future__ import annotations

import hashlib
import io
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml
from test_deploy_home import HOME, PUBLIC, _pins, make_stubs

from jarvis.home import kit
from jarvis.homebridge.face_engine import MODELS, RUNTIME_PACKAGES, ZOO_COMMIT

MODELS_DIR = HOME / "models"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((HOME / "docker-compose.yml").read_text())


# ---- the bridge image ---------------------------------------------------------------------------


def test_the_picture_libraries_are_hash_locked_for_the_bridge_image() -> None:
    """The engine loads them by name (`RUNTIME_PACKAGES`), so the import scan of
    tests/test_deploy_home.py cannot see them: they are pinned here, wheels for the bridge's
    Python 3.12 on Linux (x86-64 and ARM) only."""
    pins = _pins()
    assert set(RUNTIME_PACKAGES.values()) <= set(pins)
    assert pins["opencv-python-headless"][0] == "5.0.0.93" and pins["numpy"][0] == "2.5.4"
    assert pins["opencv-python-headless"][1] == {
        "ed709fdf9aa0bd1f2ed8549e71d19449b03a675bb581eb292285f6861953be37",
        "09a872a157c1376ab922a69bbf22f9a95bcc7b658a9d8b436a60212b02b2eeb4",
        "840bd717c21e5c11cadadc022a823315ea417f961213d06b4df010e019eb16f4",
        "10818d91510e05c04568ae12b5cd120779c70c01bf897b001a6221fe430df80f",
    }
    assert pins["numpy"][1] == {
        "fbde6962867ee75b48b0ee29b2b9372ec5d617799dbaf38e82dc0596f2f7738a",
        "fe4d21ab149f15e4e6043dfb0de87e6e5f34ac176cde83060e9802981fca2ac2",
    }
    text = (HOME / "bridge-requirements.txt").read_text()
    assert "Apache-2.0" in text and "BSD-3-Clause" in text and "LGPL" in text  # said, not hidden


def test_the_image_caps_the_decoder_and_has_the_two_mount_points() -> None:
    df = (HOME / "bridge.Dockerfile").read_text()
    assert "OPENCV_IO_MAX_IMAGE_PIXELS=50000000" in df  # review C-sec H2: the 50 MP own-file cap
    assert "mkdir /data /models /photos" in df and "USER 10001" in df
    assert "pip install --require-hashes --no-deps -r bridge-requirements.txt" in df


def test_the_bridge_gets_models_and_photos_read_only_and_more_memory(compose: dict) -> None:
    b = compose["services"]["bridge"]
    assert "./models:/models:ro" in b["volumes"]
    assert "${PHOTOS_DIR:-./photos-off}:/photos:ro" in b["volumes"]  # off: an empty folder
    assert b["mem_limit"] == "768m" and b["read_only"] is True and b["cap_drop"] == ["ALL"]
    assert not any(
        str(v).startswith("${PHOTOS_DIR") and not str(v).endswith(":ro") for v in b["volumes"]
    )
    example = (HOME / "bridge.env.example").read_text()
    assert re.search(r"^PHOTOS_DIR=$", example, re.M)  # off until the owner sets it
    assert re.search(r"^FACE_GROUPS_KEEP_DAYS=90$", example, re.M)


# ---- the two models -----------------------------------------------------------------------------


def _manifest() -> list[list[str]]:
    rows = []
    for line in (MODELS_DIR / "MODELS.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            rows.append(line.split())
    return rows


def test_the_kit_lists_each_model_as_the_bridge_pins_it() -> None:
    rows = {r[3]: r for r in _manifest()}
    assert set(rows) == {m.name for m in MODELS}
    for m in MODELS:
        sha, size, licence, name, url = rows[m.name]
        assert (sha, int(size), licence, name, url) == (
            m.sha256,
            m.size,
            m.licence,
            m.name,
            m.source,
        )
        assert ZOO_COMMIT in url and url.startswith("https://media.githubusercontent.com/")


def test_the_models_licences_ship_with_the_kit_and_no_model_file_is_in_the_repository() -> None:
    mit = (MODELS_DIR / "LICENSE-yunet-MIT.txt").read_bytes()
    apache = (MODELS_DIR / "LICENSE-sface-Apache-2.0.txt").read_bytes()
    assert hashlib.sha256(mit).hexdigest() == (
        "c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958"
    )
    assert hashlib.sha256(apache).hexdigest() == (
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
    )
    assert b"MIT License" in mit and b"Shiqi Yu" in mit and b"Apache License" in apache
    assert not list(MODELS_DIR.glob("*.onnx"))  # downloaded on the laptop, never committed
    assert "*.onnx" in (MODELS_DIR / ".gitignore").read_text()
    names = zipfile.ZipFile(io.BytesIO(kit.build(PUBLIC))).namelist()
    for need in ("models/MODELS.txt", "models/LICENSE-yunet-MIT.txt"):
        assert f"{kit.ROOT_DIR}/{need}" in names
    assert not any(n.endswith(".onnx") for n in names)


# ---- the setup script, run with stubs -----------------------------------------------------------

GOOD = b"model-bytes-for-the-test"


def run(tmp: Path, *args: str, kit_dir: Path = HOME, curl: bytes | None = GOOD, **env: str):
    log = tmp / "calls.log"
    log.touch()
    make_stubs(tmp / "bin", log)
    body = '#!/bin/bash\necho "curl $*" >> ' + str(log) + "\n"
    if curl is None:
        body += "exit 22\n"
    else:
        (tmp / "payload").write_bytes(curl)
        body += (
            'out=""; while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; fi; shift; done\n'
        )
        body += f'[ -n "$out" ] && cp {tmp / "payload"} "$out"\nexit 0\n'
    (tmp / "bin" / "curl").write_text(body)
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    full = {
        "PATH": f"{tmp / 'bin'}:/usr/bin:/bin",
        "HOME": str(home),
        "HOME_DIR": str(home / "jarvis-home"),
        "KIT_DIR": str(kit_dir),
        **env,
    }
    done = subprocess.run(
        ["bash", str(HOME / "setup-wsl.sh"), *args],
        capture_output=True, text=True, env=full, timeout=60, cwd=tmp,
    )  # fmt: skip
    return done, log.read_text()


def manifest(tmp: Path, content: bytes = GOOD) -> str:
    path = tmp / "MODELS.txt"
    sha = hashlib.sha256(content).hexdigest()
    path.write_text(
        "# test manifest\n"
        f"{sha}  {len(content)}  MIT  one.onnx  https://media.githubusercontent.com/media/x/one.onnx\n"
    )
    return str(path)


def test_models_are_downloaded_checked_and_kept(tmp_path: Path) -> None:
    run(tmp_path, "configure")
    done, calls = run(tmp_path, "models", MODELS_FILE=manifest(tmp_path))
    assert done.returncode == 0, done.stderr
    model = tmp_path / "home" / "jarvis-home" / "models" / "one.onnx"
    assert model.read_bytes() == GOOD
    assert "https://media.githubusercontent.com/media/x/one.onnx" in calls
    assert "ready" in done.stdout.lower()
    done, calls_again = run(tmp_path, "models", MODELS_FILE=manifest(tmp_path))
    assert done.returncode == 0 and calls_again.count("curl ") == calls.count("curl ")  # kept


def test_a_download_that_is_not_the_pinned_file_is_thrown_away(tmp_path: Path) -> None:
    run(tmp_path, "configure")
    done, _ = run(tmp_path, "models", curl=b"something else", MODELS_FILE=manifest(tmp_path))
    assert done.returncode == 1
    models = tmp_path / "home" / "jarvis-home" / "models"
    assert not (models / "one.onnx").exists() and not list(models.glob("*.part"))
    assert "not the reviewed file" in done.stderr
    done, _ = run(tmp_path, "models", curl=None, MODELS_FILE=manifest(tmp_path))
    assert done.returncode == 1 and "internet" in done.stderr


def test_up_goes_on_without_the_models_and_says_what_waits(tmp_path: Path) -> None:
    run(tmp_path, "configure")
    done, calls = run(tmp_path, "up", curl=None, MODELS_FILE=manifest(tmp_path))
    assert done.returncode == 0, done.stderr
    assert "up -d --build" in calls and "setup-wsl.sh models" in done.stdout


def fake_kit(tmp: Path) -> Path:
    """A kit as the download gives it: the repository's files plus its own blank bridge.env."""
    out = tmp / "kit"
    zipfile.ZipFile(io.BytesIO(kit.build(PUBLIC))).extractall(tmp / "unzipped")
    (tmp / "unzipped" / kit.ROOT_DIR).rename(out)
    return out


def test_an_update_keeps_this_laptops_own_settings_and_rebuilds_only_the_bridge(
    tmp_path: Path,
) -> None:
    source = fake_kit(tmp_path)
    assert "HA_TOKEN=\n" in (source / "bridge.env").read_text()  # the kit's own copy is blank
    done, _ = run(tmp_path, "configure", kit_dir=source, HA_TOKEN="hatoken-kept-42")
    assert done.returncode == 0, done.stderr
    live = tmp_path / "home" / "jarvis-home"
    with (live / "bridge.env").open("a") as fh:
        fh.write("PHOTOS_DIR=/mnt/c/Users/someone/Pictures/JARVIS\n")
    before = (live / "bridge.env").read_text()
    frigate = (live / "frigate.env").read_text()
    (source / "README.txt").write_text("a newer kit\n")
    done, calls = run(tmp_path, "update", kit_dir=source, MODELS_FILE=manifest(tmp_path))
    assert done.returncode == 0, done.stderr
    assert (live / "bridge.env").read_text() == before  # the token, password and folder stay
    assert (live / "frigate.env").read_text() == frigate
    assert stat.S_IMODE((live / "bridge.env").stat().st_mode) == 0o600
    assert (live / "README.txt").read_text() == "a newer kit\n"
    assert (live / "models" / "one.onnx").exists() and (live / "photos-off").is_dir()
    assert "up -d --build bridge" in calls and "hatoken-kept-42" not in done.stdout + calls
    assert "Updated" in done.stdout and "localhost:8098/faces" in done.stdout


def test_setting_up_again_from_a_fresh_download_no_longer_wipes_the_settings(
    tmp_path: Path,
) -> None:
    source = fake_kit(tmp_path)
    run(tmp_path, "configure", kit_dir=source, HA_TOKEN="hatoken-kept-42")
    live = tmp_path / "home" / "jarvis-home"
    before = (live / "bridge.env").read_text()
    assert "HA_TOKEN=hatoken-kept-42" in before and f"JARVIS_URL={PUBLIC}" in before
    done, _ = run(tmp_path, "configure", kit_dir=source)
    assert done.returncode == 0, done.stderr
    assert (live / "bridge.env").read_text() == before


def test_the_photo_folder_is_set_checked_and_switched_off(tmp_path: Path) -> None:
    run(tmp_path, "configure")
    live = tmp_path / "home" / "jarvis-home"
    photos = tmp_path / "My Pictures"
    photos.mkdir()
    done, calls = run(tmp_path, "photos-dir", str(photos))
    assert done.returncode == 0, done.stderr
    assert f"PHOTOS_DIR={photos}\n" in (live / "bridge.env").read_text()
    assert "up -d --force-recreate bridge" in calls and "read-only" in done.stdout
    done, _ = run(tmp_path, "photos-dir", str(tmp_path / "missing"))
    assert done.returncode == 1 and "no such folder" in done.stderr
    assert f"PHOTOS_DIR={photos}\n" in (live / "bridge.env").read_text()  # unchanged
    for bad in ("relative/path", "/"):
        done, _ = run(tmp_path, "photos-dir", bad)
        assert done.returncode == 1, bad
    done, calls = run(tmp_path, "photos-dir", "off")
    assert done.returncode == 0 and "PHOTOS_DIR=\n" in (live / "bridge.env").read_text()
    assert "off" in done.stdout.lower()
    done, _ = run(tmp_path, "photos-dir")
    assert done.returncode == 1 and "usage" in done.stderr.lower()


def test_the_script_parses_and_passes_shellcheck() -> None:
    import shutil
    import sys

    assert subprocess.run(["bash", "-n", str(HOME / "setup-wsl.sh")]).returncode == 0
    found = shutil.which("shellcheck") or str(Path(sys.executable).with_name("shellcheck"))
    if not Path(found).exists():
        pytest.skip("shellcheck not installed")
    subprocess.run([found, "-S", "warning", str(HOME / "setup-wsl.sh")], check=True)


# ---- the Windows half and the README (by text: no PowerShell here) ------------------------------


def test_the_windows_script_has_update_and_photo_folder_runs_before_the_first_run_steps() -> None:
    ps = (HOME / "setup-windows.ps1").read_text()
    assert re.search(
        r"param\(\s*\[switch\]\$HaToken,\s*\[switch\]\$Update,\s*\[string\]\$PhotosDir", ps
    )
    first_run = ps.index("# 1. Windows")
    update, photos = ps.index("if ($Update) {"), ps.index("if ($PhotosDir) {")
    assert update < first_run and photos < first_run
    assert 'setup-wsl.sh" update' in ps[update:first_run] and "exit 0" in ps[update:first_run]
    block = ps[photos:first_run]
    assert "setup-wsl.sh photos-dir" in block and "WslPath $PhotosDir" in block
    assert "Test-Path -LiteralPath $PhotosDir -PathType Container" in block and "exit 0" in block
    assert "-PhotosDir off" in ps and "setup-windows.ps1 -Update" in ps
    assert ps.isascii()


def test_the_readme_says_what_the_laptop_now_does_with_photos() -> None:
    raw = (HOME / "README.txt").read_text()
    text = " ".join(raw.split())
    assert raw.isascii() and "not built yet" not in text and "Kit to-do" not in text
    for needle in (
        "setup-windows.ps1 -Update",
        "setup-windows.ps1 -PhotosDir",
        "-PhotosDir off",
        "read-only",
        "FACE_GROUPS_KEEP_DAYS",
        "90 days",
        "never leave this laptop",
        "localhost:8098/faces",
        "JPEG",
    ):
        assert needle in text, needle


# ---- review C-sec L1, L2, L3 and C-code L1, L2: the scripts' small holes -------------------------


def test_a_whole_disk_a_system_folder_or_the_kit_itself_is_refused(tmp_path: Path) -> None:
    run(tmp_path, "configure")
    live = tmp_path / "home" / "jarvis-home"
    before = (live / "bridge.env").read_text()
    for bad in ("//", "/", "///", "/etc", "/usr/share", "/proc/1", str(tmp_path / "home")):
        done, calls = run(tmp_path, "photos-dir", bad)
        assert done.returncode == 1, (bad, done.stdout)
        assert "force-recreate" not in calls, bad
    inside = live / "photos-off"
    inside.mkdir(exist_ok=True)
    done, _ = run(tmp_path, "photos-dir", str(inside))
    assert done.returncode == 1 and "home kit" in done.stderr
    assert (live / "bridge.env").read_text() == before  # nothing was written
    # "//" was the reviewer's way past the old check: it resolves to the whole disk
    photos = tmp_path / "Pics"
    photos.mkdir()
    done, _ = run(tmp_path, "photos-dir", str(photos) + "//")
    assert done.returncode == 0 and f"PHOTOS_DIR={photos}\n" in (live / "bridge.env").read_text()


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("/mnt/c", False),
        ("/mnt/c/Windows", False),
        ("/mnt/c/Windows/System32", False),
        ("/mnt/c/Users", False),
        ("/mnt/c/Users/someone", False),  # a whole profile
        ("/mnt/c/Program Files", False),
        ("/mnt/c/ProgramData/x", False),
        ("/home/someone", False),
        ("/mnt/wsl/x", False),
        ("/mnt/c/Users/someone/Pictures/JARVIS", True),
        ("/mnt/d/Photos", True),
        ("/home/someone/photos", True),
    ],
)
def test_the_folder_rule_by_path(path: str, ok: bool) -> None:
    script = (HOME / "setup-wsl.sh").read_text()
    start = script.index("photos_dir_ok() {")
    body = script[start : script.index("\n}\n", start) + 3]
    done = subprocess.run(
        ["bash", "-c", body + '\nphotos_dir_ok "$1"', "x", path],
        env={"HOME_DIR": "/home/someone/jarvis-home", "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=10,
    )  # fmt: skip
    assert (done.returncode == 0) is ok, (path, done.stderr)


def test_models_are_fetched_over_https_only_and_size_capped() -> None:
    script = (HOME / "setup-wsl.sh").read_text()
    fetch = script[script.index("fetch_model() {") : script.index("step_models() {")]
    for flag in ("--proto '=https'", "--proto-redir '=https'", "--tlsv1.2", "--max-filesize"):
        assert flag in fetch, flag


def test_a_kit_without_its_model_list_only_warns_and_goes_on(tmp_path: Path) -> None:
    run(tmp_path, "configure")
    done, calls = run(tmp_path, "up", MODELS_FILE=str(tmp_path / "no-such-list.txt"))
    assert done.returncode == 0, done.stderr
    assert "up -d --build" in calls and "model files is missing" in done.stderr


def test_the_windows_script_restores_wslenv_and_refuses_a_quote_in_the_kit_folder() -> None:
    ps = (HOME / "setup-windows.ps1").read_text()
    update = ps[ps.index("\nif ($Update) {") : ps.index("\nif ($PhotosDir) {")]
    assert "KIT_DIR='$kitInWsl'" not in update  # no path inside a shell string any more
    assert '$kitInWsl.Contains("\'")' in update and "$env:WSLENV = $savedWslEnv" in update
    photos = ps[ps.index("\nif ($PhotosDir) {") :]
    assert "$savedWslEnv = $env:WSLENV" in photos and "$env:WSLENV = $savedWslEnv" in photos
