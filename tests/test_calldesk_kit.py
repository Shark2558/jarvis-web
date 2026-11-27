"""R18 C: the call desk's kit zip and its installer scripts.

The kit is built from the repository at request time: protocol.py, models.py and signing.py go in
as they are in `src` (never a hand-kept copy), only modules of the kit set and pinned packages may
be imported, nothing secret ships, the bytes are reproducible, the shipped tree imports on its own,
and the owner-only route serves it with its SHA-256. The scripts keep the plan's promises: no
administrator, Python only with his Y, wheels only and hash-checked, one data folder.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from jarvis.api import calls_routes as cr
from jarvis.api.calldesk_kit import SLOT, desk_kit, install_calldesk_kit
from jarvis.calldesk import DESK_VERSION, config, kit
from jarvis.config import Settings

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "calldesk"
URL = "https://jarvis.example.run.app"
TOKEN = "t" * 32


def _zip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {i.filename: zf.read(i) for i in zf.infolist()}


@pytest.fixture(scope="module")
def built() -> bytes:
    return kit.build(URL, ROOT)


def test_the_kit_is_reproducible(built: bytes) -> None:
    assert kit.build(URL, ROOT) == built
    assert kit.CallDeskKit(URL, ROOT).build() == built
    assert kit.CallDeskKit(URL, ROOT).version == DESK_VERSION


def test_what_the_kit_holds(built: bytes) -> None:
    files = _zip(built)
    names = {n.split("/", 1)[1] for n in files}
    assert all(n.startswith(kit.ROOT_DIR + "/") for n in files)
    for need in (
        "install-calldesk.ps1",
        "start-calldesk.ps1",
        "stop-calldesk.ps1",
        "restore-microphone.ps1",
        "requirements-calldesk.txt",
        "README.txt",
        "desk.env",
        "desk-src/jarvis/__init__.py",
        "desk-src/jarvis/calldesk/__init__.py",
        "desk-src/jarvis/calldesk/__main__.py",
        "desk-src/jarvis/calldesk/session.py",
        "desk-src/jarvis/calldesk/wsconn.py",
        "desk-src/jarvis/calldesk/win/__init__.py",
        "desk-src/jarvis/calldesk/win/coreaudio.py",
        "desk-src/jarvis/calls/__init__.py",
        "desk-src/jarvis/calls/protocol.py",
        "desk-src/jarvis/calls/models.py",
        "desk-src/jarvis/home/__init__.py",
        "desk-src/jarvis/home/signing.py",
    ):
        assert need in names, need
    assert "desk-src/jarvis/calldesk/kit.py" not in names  # cloud only
    assert not any(
        n.endswith((".pyc", ".pem", ".key", ".log")) or "__pycache__" in n or "secret" in n
        for n in names
    )
    # nothing else of the cloud ships: only the shared modules outside the desk (R5.2 I1: + the
    # laptop speech kit's client, its protocol and the Tailscale address rule it reuses)
    outside = {n for n in names if n.startswith("desk-src/") and "/calldesk/" not in n}
    assert {n for n in outside if not n.endswith("__init__.py")} == {
        "desk-src/jarvis/calls/protocol.py",
        "desk-src/jarvis/calls/models.py",
        "desk-src/jarvis/home/signing.py",
        "desk-src/jarvis/localspeech/protocol.py",
        "desk-src/jarvis/localspeech/client.py",
        "desk-src/jarvis/localspeech/desk.py",
        "desk-src/jarvis/offline/config.py",
    }


def test_shared_modules_are_todays_copies_and_cloud_inits_never_ship(built: bytes) -> None:
    files = {n.split("/", 1)[1]: d for n, d in _zip(built).items()}
    for rel in ("jarvis/calls/protocol.py", "jarvis/calls/models.py", "jarvis/home/signing.py"):
        assert files[f"desk-src/{rel}"] == (ROOT / "src" / rel).read_bytes(), rel
    for rel in ("calldesk/session.py", "calldesk/vad.py", "calldesk/__init__.py"):
        assert files[f"desk-src/jarvis/{rel}"] == (ROOT / "src" / "jarvis" / rel).read_bytes()
    assert files["desk-src/jarvis/calls/__init__.py"] == kit._PKG_INIT.encode()
    assert files["desk-src/jarvis/home/__init__.py"] == kit._PKG_INIT.encode()
    assert DESK_VERSION.encode() in files["desk-src/jarvis/__init__.py"]


def test_desk_env_holds_only_the_address(built: bytes) -> None:
    env = {n.split("/", 1)[1]: d for n, d in _zip(built).items()}["desk.env"].decode()
    assert f"JARVIS_URL={URL}\n" in env
    values = [line for line in env.splitlines() if line and not line.startswith("#")]
    assert values == [f"JARVIS_URL={URL}"]


def test_the_shipped_tree_imports_on_its_own(built: bytes, tmp_path: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(built)) as zf:
        zf.extractall(tmp_path)
    src = tmp_path / kit.ROOT_DIR / "desk-src"
    probe = (
        "import jarvis, jarvis.calldesk.__main__ as m, jarvis.calldesk.app, "
        "jarvis.calldesk.wsconn, jarvis.calls.protocol as p; "
        f"assert jarvis.__file__.startswith({str(src)!r}), jarvis.__file__; "
        "assert p.FRAME_BYTES == 640; print('ok')"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=src, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-2000:]
    cfg = config.load(tmp_path / kit.ROOT_DIR, {"LOCALAPPDATA": str(tmp_path / "local")})
    assert cfg.jarvis_url == URL  # the shipped desk.env is what the desk reads


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(DEPLOY, root / "deploy" / "calldesk")
    shutil.copytree(
        ROOT / "src" / "jarvis" / "calldesk",
        root / "src" / "jarvis" / "calldesk",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for rel in ("calls/protocol.py", "calls/models.py", "home/signing.py", "calls/store.py"):
        (root / "src" / "jarvis" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "src" / "jarvis" / rel, root / "src" / "jarvis" / rel)
    return root


def test_a_cloud_import_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "src/jarvis/calldesk/extra.py").write_text("from jarvis.calls import store\n")
    with pytest.raises(kit.KitError, match="not part of the call desk kit"):
        kit.build(URL, root)


def test_an_unpinned_package_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "src/jarvis/calldesk/extra.py").write_text("def f() -> None:\n    import requests\n")
    with pytest.raises(kit.KitError, match="doesn't install"):
        kit.build(URL, root)


def test_no_address_or_no_kit_files_is_refused(tmp_path: Path) -> None:
    with pytest.raises(kit.KitError, match="public address"):
        kit.build("http://jarvis.example", ROOT)
    with pytest.raises(kit.KitError, match="not in this build"):
        kit.build(URL, tmp_path)


def test_secrets_left_in_the_folder_never_ship(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    for name in ("secret.json", "desk.env", "x.key"):
        (root / "deploy/calldesk" / name).write_text("SECRET")
    (root / "deploy/calldesk/.venv").mkdir()
    (root / "deploy/calldesk/.venv/pyvenv.cfg").write_text("SECRET")
    files = _zip(kit.build(URL, root))
    assert not any(b"SECRET" in d for d in files.values())


# ---- the pins ----------------------------------------------------------------------------------


def _requirements() -> str:
    return (DEPLOY / "requirements-calldesk.txt").read_text(encoding="utf-8")


def test_every_pin_is_hash_locked_and_the_set_is_the_closure() -> None:
    text = _requirements()
    blocks = re.split(r"\n(?=[A-Za-z])", text.split("\n", 1)[1])
    pins = {}
    for block in blocks:
        m = re.match(r"([A-Za-z0-9._-]+)==(\S+)", block)
        if m:
            hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", block)
            assert hashes, m.group(1)
            pins[kit._norm(m.group(1))] = m.group(2)
    assert set(pins) == {
        "soundcard",
        "numpy",
        "cffi",
        "pycparser",
        "comtypes",
        "websockets",
        "cryptography",
        "pydantic",
        "pydantic-core",
        "annotated-types",
        "typing-extensions",
        "typing-inspection",
        # R5.2 I1: httpx and what it needs, for the laptop speech kit's client
        "httpx",
        "httpcore",
        "h11",
        "anyio",
        "idna",
        "certifi",
    }
    assert kit.pinned(text) == frozenset(pins)
    assert pins["soundcard"] == "0.4.6"  # the version S0 tests on the laptop


# ---- the scripts -------------------------------------------------------------------------------


def _ps(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def test_the_installer_keeps_its_promises() -> None:
    ps = _ps("install-calldesk.ps1")
    assert "--require-hashes --only-binary=:all:" in ps
    assert "IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)" in ps
    winget = ps.index("winget install")
    assert ps.rfind("Yes 'Install it now?'", 0, winget) != -1  # only after his Y
    assert "--scope user" in ps and "Python.Python.3.12" in ps
    assert "jarvis.calldesk link" in ps and "jarvis.calldesk check" in ps
    assert "jarvis-calldesk.pth" in ps and "desk-src" in ps
    assert "kit-folder.txt" in ps  # what start-home.ps1 reads


def test_every_script_uses_the_desks_data_folder() -> None:
    want = config.default_data_dir({"LOCALAPPDATA": "X"}).relative_to("X")
    folder = "\\".join(want.parts)  # JARVIS\CallDesk
    for name in ("install-calldesk.ps1", "start-calldesk.ps1", "stop-calldesk.ps1"):
        assert f"'{folder}'" in _ps(name), name
    home = (ROOT / "deploy/home/start-home.ps1").read_text(encoding="utf-8")
    assert f"{folder}\\kit-folder.txt" in home and "start-calldesk.ps1" in home


def test_start_and_stop_scripts() -> None:
    start = _ps("start-calldesk.ps1")
    assert "'-I', '-m', 'jarvis.calldesk', 'supervise'" in start and "pythonw.exe" in start
    assert "stop.request" in start and "-WindowStyle Hidden" in start
    stop = _ps("stop-calldesk.ps1")
    cfg = config.DeskConfig(URL, Path("d"), Path("k"))
    assert cfg.stop_request.name in stop and "jarvis.calldesk restore" in stop
    assert "jarvis.calldesk supervise" in stop and "jarvis.calldesk run" in stop
    assert "jarvis.calldesk restore" in _ps("restore-microphone.ps1")


def test_readme_is_numbered_plain_steps() -> None:
    readme = _ps("README.txt")
    steps = re.findall(r"^ {1,2}(\d+)\. ", readme, re.MULTILINE)
    assert steps == [str(i) for i in range(1, len(steps) + 1)] and len(steps) >= 6
    assert "install-calldesk.ps1" in readme and "NOT as administrator" in readme


def test_review_readme_names_the_console_s_own_menu_path() -> None:
    # R18 review: the desk's section is Calls -> Settings -> "Call desk on your laptop" (there is no
    # "Calls -> Call desk"), with "Link the call desk" and the review's Unlink there
    readme = " ".join(_ps("README.txt").split())
    assert "Calls -> Call desk" not in readme
    assert 'Calls -> Settings -> "Call desk on your laptop" -> "Link the call desk"' in readme
    assert 'Calls -> Settings -> "Call desk on your laptop" -> Unlink' in readme


# ---- the route -------------------------------------------------------------------------------


def _app(settings: Settings, url: str | None) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings.model_copy(
        update={"env": "prod", "api_token": SecretStr(TOKEN), "public_base_url": url}
    )
    cr.install_calls_routes(app)
    install_calldesk_kit(app, ROOT)
    return app


def test_no_https_address_no_kit(settings: Settings) -> None:
    assert desk_kit(settings.model_copy(update={"public_base_url": None})) is None
    assert getattr(_app(settings, "http://x").state, SLOT, None) is None


def test_the_owner_downloads_the_kit_with_its_hash(settings: Settings, built: bytes) -> None:
    auth = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(_app(settings, URL)) as c:
        got = c.get("/v1/calls/desk/kit", headers=auth)
        info = c.get("/v1/calls/desk/kit/info", headers=auth).json()
        anon = c.get("/v1/calls/desk/kit")
    assert got.status_code == 200 and got.content == built
    assert got.headers["x-kit-sha256"] == hashlib.sha256(built).hexdigest()
    assert got.headers["cache-control"] == "no-store"
    assert "JARVIS-Call-desk-kit.zip" in got.headers["content-disposition"]
    assert info == {
        "sha256": hashlib.sha256(built).hexdigest(),
        "size": len(built),
        "version": "18.1.0",  # R5.2 I1: the desk gained the laptop speech kit
    }
    assert anon.status_code == 401
