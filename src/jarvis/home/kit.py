# src/jarvis/home/kit.py
"""The home kit zip (R3 D4). Cloud only.

`GET /v1/home/kit` returns `build(...)`: `deploy/home/` (compose file, scripts, README) plus the
bridge source under `bridge-src/` and a `bridge.env` that holds only JARVIS's public address (not a
secret). The zip is byte-for-byte reproducible (sorted names, fixed times) so its SHA-256, shown
beside the button, can be checked.

The bridge source is found by reading the imports of `jarvis/homebridge/*.py`: every `jarvis.*`
module they use is copied too, and the build REFUSES (`KitError`) if one is outside the kit set
(`jarvis.home.{ports,signing,classes}`, `jarvis.faces.ports`, `jarvis.homebridge.*`) or if a file
imports a package the bridge image doesn't install. That is the "kit rule" as code. Nothing secret
is ever in the kit: files named like keys, tokens or data volumes are skipped, and the env file has
blank passwords for the setup script to fill at home.
"""

from __future__ import annotations

import ast
import hashlib
import io
import sys
import zipfile
from pathlib import Path

from jarvis.homebridge.config import BRIDGE_VERSION

KIT_VERSION = BRIDGE_VERSION
ROOT_DIR = "JARVIS-Home"
SAFE_THIRD_PARTY = frozenset(
    {
        "pydantic",
        "pydantic_core",
        "cryptography",
        "fastapi",
        "starlette",
        "uvicorn",
        "httpx",
        "aiomqtt",
        "annotated_types",
    }
)
SAFE_JARVIS = (
    "jarvis.home.ports",
    "jarvis.home.signing",
    "jarvis.home.classes",
    "jarvis.faces.ports",
)
SKIP_NAMES = frozenset({"bridge.env", "secret.json", ".env", "state.json"})
SKIP_PARTS = frozenset({"bridge-data", "__pycache__", ".git", "mosquitto-data"})
SKIP_SUFFIXES = (".pem", ".key", ".pyc", ".tmp", ".log")
_STAMP = (2026, 1, 1, 0, 0, 0)
_PKG_INIT = '"""JARVIS home bridge package (home kit)."""\n__version__ = "{v}"\n'
_SUBPKG_INIT = '"""Part of the JARVIS home kit."""\n'


class KitError(RuntimeError):
    """The kit can't be built honestly (plain words in the message, no secrets)."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _skip(path: Path, base: Path) -> bool:
    rel = path.relative_to(base)
    return (
        any(p in SKIP_PARTS for p in rel.parts)
        or path.name in SKIP_NAMES
        or path.name.endswith(SKIP_SUFFIXES)
    )


def _is_safe_jarvis(name: str) -> bool:
    return (
        name.startswith("jarvis.homebridge")
        or name in SAFE_JARVIS
        or name
        in (
            "jarvis",
            "jarvis.home",
            "jarvis.faces",
        )
    )


def _imports(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _module_file(src: Path, name: str) -> Path | None:
    rel = Path(*name.split("."))
    for cand in (src / rel.with_suffix(".py"), src / rel / "__init__.py"):
        if cand.is_file():
            return cand
    return None


def bridge_sources(src: Path) -> dict[str, bytes]:
    """{path inside bridge-src: bytes} for the bridge and everything it imports from jarvis."""
    files: dict[str, bytes] = {}
    todo = sorted((src / "jarvis" / "homebridge").rglob("*"))
    seen: set[Path] = set()
    while todo:
        path = todo.pop()
        if not path.is_file() or path in seen or "__pycache__" in path.parts:
            continue
        seen.add(path)
        rel = path.relative_to(src).as_posix()
        data = path.read_bytes()
        files[rel] = data
        if path.suffix != ".py":
            continue
        for name in _imports(data.decode("utf-8")):
            top = name.split(".")[0]
            if top == "jarvis":
                found = _module_file(src, name)
                if found is None:
                    continue  # `from jarvis.home.ports import X`: the X part isn't a module
                if not _is_safe_jarvis(name):
                    raise KitError(f"{rel} imports {name}, which is not part of the home kit")
                todo.append(found)
            elif top not in SAFE_THIRD_PARTY and top not in sys.stdlib_module_names:
                raise KitError(f"{rel} imports {top}, which the bridge image doesn't install")
    for pkg in {Path(f).parent for f in files if f.endswith(".py")}:  # every package has an init
        init = (pkg / "__init__.py").as_posix()
        if init not in files:
            files[init] = _SUBPKG_INIT.encode()
    files["jarvis/__init__.py"] = _PKG_INIT.format(v=KIT_VERSION).encode()
    return files


def env_file(public_url: str) -> bytes:
    """`bridge.env`: JARVIS's public address (not a secret); the passwords stay blank for the
    setup script to fill at home."""
    lines = [
        "# Filled in by the setup script on your laptop. Keep this file private.",
        f"JARVIS_URL={public_url.rstrip('/')}",
        "HA_URL=http://host.docker.internal:8123",
        "HA_TOKEN=",
        "MQTT_PASSWORD=",
        "FRIGATE_PASSWORD=",
        "",
    ]
    return "\n".join(lines).encode()


def kit_files(root: Path, public_url: str) -> dict[str, bytes]:
    home = root / "deploy" / "home"
    if not home.is_dir():
        raise KitError("the home kit files are not in this build")
    files: dict[str, bytes] = {}
    for path in sorted(home.rglob("*")):
        if path.is_file() and not _skip(path, home):
            files[path.relative_to(home).as_posix()] = path.read_bytes()
    files["bridge.env"] = env_file(public_url)
    for rel, data in bridge_sources(root / "src").items():
        files[f"bridge-src/{rel}"] = data
    return files


def build(public_url: str, root: Path | None = None) -> bytes:
    """The kit zip. Reproducible: the same tree and address give the same bytes."""
    if not public_url.startswith("https://"):
        raise KitError("JARVIS's public address isn't set, so the kit can't be made")
    files = kit_files(root or repo_root(), public_url)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"{ROOT_DIR}/{name}", date_time=_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if name.endswith(".sh") else 0o644
            info.external_attr = mode << 16
            zf.writestr(info, files[name])
    return buf.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def outdated(bridge_version: str | None) -> bool:
    """True when the bridge reports an older version than this kit."""

    def parts(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    try:
        return bridge_version is not None and parts(bridge_version) < parts(KIT_VERSION)
    except ValueError:
        return False


__all__ = ["KIT_VERSION", "KitError", "build", "bridge_sources", "kit_files", "outdated", "sha256"]
