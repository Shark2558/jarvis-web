# src/jarvis/calldesk/kit.py
"""The call desk's kit zip (R18 C; I0's `DeskKit` on `app.state.calls_desk_kit`). Cloud side only:
this file is never put in the kit.

`GET /v1/calls/desk/kit` (owner only) answers `CallDeskKit.build()`: `deploy/calldesk/` (the
installer, start/stop/restore scripts, the hash-pinned requirements, README.txt), a `desk.env`
holding only JARVIS's public address (not a secret), and the desk's source under `desk-src/`,
made from the repository at request time. Like the home kit (`jarvis.home.kit`):

- the source is found by reading the imports of `jarvis/calldesk/**/*.py`: each `jarvis.*` module
  they use is copied as it is in the repository (so `jarvis/calls/protocol.py`, `models.py` and
  `jarvis/home/signing.py` are always today's copies, never a hand-kept duplicate), and the build
  REFUSES (`KitError`) a `jarvis` module outside the kit set or a third-party import that
  `requirements-calldesk.txt` doesn't pin. Package `__init__` files are short stubs, so a cloud
  package's own `__init__` never ships;
- nothing secret ships: names like keys, tokens, state or a `.venv` are skipped;
- the zip is byte-for-byte reproducible (sorted names, fixed times), so the SHA-256 the console
  shows beside the button can be checked.
"""

from __future__ import annotations

import ast
import io
import os
import re
import sys
import zipfile
from pathlib import Path

from jarvis.calldesk import DESK_VERSION

ROOT_DIR = "JARVIS-CallDesk"
SRC_DIR = "desk-src"
REQUIREMENTS = "requirements-calldesk.txt"
KIT_ONLY = "jarvis.calldesk.kit"  # this file: cloud only
SAFE_JARVIS = frozenset(
    {
        "jarvis.calls.protocol",
        "jarvis.calls.models",
        "jarvis.home.signing",
        # R5.2 I1: the laptop speech kit's client for the desk (V2's `desk_speech`)
        "jarvis.localspeech.protocol",
        "jarvis.localspeech.client",
        "jarvis.localspeech.desk",
        "jarvis.offline.config",
    }
)
PACKAGES = frozenset(
    {
        "jarvis",
        "jarvis.calls",
        "jarvis.home",
        "jarvis.calldesk",
        "jarvis.localspeech",
        "jarvis.offline",
    }
)
IMPORT_TO_DIST = {"pydantic_core": "pydantic-core", "typing_extensions": "typing-extensions"}
SKIP_NAMES = frozenset(
    {"desk.env", "secret.json", "audio-state.json", ".env", "stop.request", "local-speech.key"}
)
SKIP_PARTS = frozenset({"__pycache__", ".git", ".venv", "desk-data"})
SKIP_SUFFIXES = (".pem", ".key", ".pyc", ".tmp", ".log")
_STAMP = (2026, 1, 1, 0, 0, 0)
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", re.MULTILINE)
_ROOT_INIT = '"""JARVIS call desk (the call desk kit)."""\n__version__ = "{v}"\n'
_PKG_INIT = '"""Part of the JARVIS call desk kit."""\n'


class KitError(RuntimeError):
    """The kit can't be built honestly (plain words, no secrets)."""


def repo_root() -> Path:
    """Where `deploy/calldesk` and `src` live: HOME_KIT_ROOT (the image sets /app, as for the home
    kit, because after `pip install .` this file is in site-packages), else the checkout."""
    configured = os.environ.get("HOME_KIT_ROOT", "").strip()
    return Path(configured) if configured else Path(__file__).resolve().parents[3]


def pinned(requirements: str) -> frozenset[str]:
    """Distribution names pinned with == in a requirements file (normalised)."""
    return frozenset(_norm(m.group(1)) for m in _PIN.finditer(requirements))


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


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


def _module_name(src: Path, path: Path) -> str:
    rel = path.relative_to(src).with_suffix("")
    parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts
    return ".".join(parts)


def _desk_files(src: Path) -> list[Path]:
    desk = src / "jarvis" / "calldesk"
    return sorted(
        p
        for p in desk.rglob("*.py")
        if "__pycache__" not in p.parts and _module_name(src, p) != KIT_ONLY
    )


def desk_sources(src: Path, allowed_dists: frozenset[str]) -> dict[str, bytes]:
    """{path under desk-src: bytes} for the desk and every jarvis module it imports."""
    files: dict[str, bytes] = {}
    todo = _desk_files(src)
    seen: set[Path] = set()
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        rel = path.relative_to(src).as_posix()
        data = path.read_bytes()
        if path.name != "__init__.py" or rel.startswith("jarvis/calldesk/"):
            files[rel] = data
        for name in sorted(_imports(data.decode("utf-8"))):
            todo.extend(_follow(src, rel, name, allowed_dists))
    for pkg in {Path(f).parent for f in files}:  # every package has an init
        for parent in (pkg, *pkg.parents):
            init = (parent / "__init__.py").as_posix()
            if parent.as_posix() not in (".", "") and init not in files:
                files[init] = _PKG_INIT.encode()
    files["jarvis/__init__.py"] = _ROOT_INIT.format(v=DESK_VERSION).encode()
    return files


def _follow(src: Path, rel: str, name: str, allowed_dists: frozenset[str]) -> list[Path]:
    top = name.split(".")[0]
    if top != "jarvis":
        dist = _norm(IMPORT_TO_DIST.get(top, top))
        if top not in sys.stdlib_module_names and dist not in allowed_dists:
            raise KitError(f"{rel} imports {top}, which the call desk kit doesn't install")
        return []
    if name in PACKAGES:
        return []  # a package: its stub init is made below
    found = _module_file(src, name)
    if found is None:
        return []  # `from jarvis.calls.protocol import X`: X isn't a module
    if not (name.startswith("jarvis.calldesk.") or name in SAFE_JARVIS):
        raise KitError(f"{rel} imports {name}, which is not part of the call desk kit")
    return [found]


def _skip(path: Path, base: Path) -> bool:
    rel = path.relative_to(base)
    return (
        any(p in SKIP_PARTS for p in rel.parts)
        or path.name in SKIP_NAMES
        or path.name.endswith(SKIP_SUFFIXES)
    )


def env_file(public_url: str) -> bytes:
    lines = [
        "# The call desk's only setting: JARVIS's public address (not a secret).",
        f"JARVIS_URL={public_url.rstrip('/')}",
        "",
    ]
    return "\n".join(lines).encode()


def kit_files(root: Path, public_url: str) -> dict[str, bytes]:
    deploy = root / "deploy" / "calldesk"
    if not (deploy / REQUIREMENTS).is_file():
        raise KitError("the call desk kit files are not in this build")
    files: dict[str, bytes] = {}
    for path in sorted(deploy.rglob("*")):
        if path.is_file() and not _skip(path, deploy):
            files[path.relative_to(deploy).as_posix()] = path.read_bytes()
    allowed = pinned(files[REQUIREMENTS].decode("utf-8"))
    for rel, data in desk_sources(root / "src", allowed).items():
        files[f"{SRC_DIR}/{rel}"] = data
    files["desk.env"] = env_file(public_url)
    return files


def build(public_url: str, root: Path | None = None) -> bytes:
    if not public_url.startswith("https://"):
        raise KitError("JARVIS's public address isn't set, so the kit can't be made")
    files = kit_files(root or repo_root(), public_url)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"{ROOT_DIR}/{name}", date_time=_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[name])
    return buf.getvalue()


class CallDeskKit:
    """`app.state.calls_desk_kit` (I0's `DeskKit`): the zip for this JARVIS's public address."""

    def __init__(self, public_url: str, root: Path | None = None) -> None:
        self._url = public_url
        self._root = root

    @property
    def version(self) -> str:
        return DESK_VERSION

    def build(self) -> bytes:
        return build(self._url, self._root)


__all__ = [
    "DESK_VERSION",
    "CallDeskKit",
    "KitError",
    "build",
    "desk_sources",
    "kit_files",
    "pinned",
]
