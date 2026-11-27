# tests/test_r52_v1_import_guard.py -- R5.2 V1 (brief rule 5): the kit's model runtimes stay on the
# laptop. faster-whisper, Kokoro, Piper, onnxruntime, openWakeWord (and PyTorch, transformers,
# parler-tts, PyAV) are imported only inside the kit's runtime / wake-word modules, only inside
# functions; the cloud app never imports those modules (it reaches the kit over httpx through
# `protocol`, `client`, `memory`, `desk`); none of those packages is a dependency in pyproject.toml;
# and the kit's own modules import nothing from the cloud, only what its requirements pin.
from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
KIT = SRC / "jarvis" / "localspeech"
RUNTIME_PACKAGES = frozenset(
    {
        "faster_whisper",
        "ctranslate2",
        "kokoro",
        "kokoro_onnx",
        "piper",
        "onnxruntime",
        "openwakeword",
        "torch",
        "torchaudio",
        "transformers",
        "parler_tts",
        "av",
    }
)
RUNTIME_DISTS = frozenset(
    {
        "faster-whisper",
        "ctranslate2",
        "kokoro",
        "kokoro-onnx",
        "piper-tts",
        "onnxruntime",
        "onnxruntime-gpu",
        "openwakeword",
        "torch",
        "torchaudio",
        "transformers",
        "parler-tts",
        "av",
    }
)
CLOUD_MAY_IMPORT = frozenset({"protocol", "memory", "client", "desk"})  # I0's and V2's
RUNTIME_HOMES = ("jarvis/localspeech/runtimes/", "jarvis/localspeech/wakeword/")
KIT_SAFE_JARVIS = ("jarvis.localspeech", "jarvis.calls.models", "jarvis.calls.protocol")
KIT_THIRD_PARTY = {  # import name -> the distribution requirements-kit.txt pins
    "pydantic": "pydantic",
    "starlette": "starlette",
    "uvicorn": "uvicorn",
    "cryptography": "cryptography",
    "numpy": "numpy",
    "faster_whisper": "faster-whisper",
    "onnxruntime": "onnxruntime",
    "av": "av",
}
LEFT_OUT_RUNTIMES = frozenset({"kokoro_onnx", "piper", "torch", "transformers", "parler_tts"})
V1_FILES_NOT_MINE = frozenset({"__init__.py", "protocol.py", "memory.py", "client.py", "desk.py"})


def _module(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__")


def _imports(path: Path) -> list[tuple[str, bool]]:
    """Every absolute import in `path` as (module, at module level)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top: set[int] = set()
    for stmt in tree.body:
        top.add(id(stmt))
        if isinstance(stmt, ast.If):  # `if TYPE_CHECKING:` blocks count as top level
            top.update(id(n) for n in stmt.body)
    found: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, id(node) in top) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.module, id(node) in top))
            found += [(f"{node.module}.{a.name}", id(node) in top) for a in node.names]
    return found


def _type_checking_only(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.If) and getattr(node.test, "id", "") == "TYPE_CHECKING":
            for n in ast.walk(node):
                if isinstance(n, ast.Import):
                    names |= {a.name for a in n.names}
    return names


def test_runtime_packages_are_imported_only_lazily_in_the_kits_runtime_modules() -> None:
    offenders = []
    for path in sorted((SRC / "jarvis").rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        for name, at_top in _imports(path):
            if name.split(".")[0] not in RUNTIME_PACKAGES:
                continue
            if not rel.startswith(RUNTIME_HOMES) or at_top:
                offenders.append(f"{rel}: {name}{' (at import time)' if at_top else ''}")
    assert offenders == []


def test_the_cloud_never_imports_the_kits_own_modules() -> None:
    offenders = []
    for path in sorted((SRC / "jarvis").rglob("*.py")):
        if path.is_relative_to(KIT):
            continue
        for name, _ in _imports(path):
            parts = name.split(".")
            if parts[:2] == ["jarvis", "localspeech"] and len(parts) > 2:
                if parts[2] not in CLOUD_MAY_IMPORT and not parts[2][0].isupper():
                    offenders.append(f"{path.relative_to(SRC)}: {name}")
    assert offenders == []


def test_no_runtime_is_a_dependency_of_the_cloud_package() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        declared += extra
    names = {re.split(r"[\s<>=!~;\[]", d.strip(), maxsplit=1)[0].lower() for d in declared}
    assert names & RUNTIME_DISTS == set()


def test_the_kits_modules_import_nothing_from_the_cloud_and_only_pinned_packages() -> None:
    pins = set(
        re.findall(
            r"^([a-z0-9][a-z0-9._-]*)==",
            (ROOT / "deploy/local-speech/requirements-kit.txt").read_text(),
            re.M,
        )
    )
    stdlib = sys.stdlib_module_names
    offenders = []
    for path in sorted(KIT.rglob("*.py")):
        rel = path.relative_to(KIT).as_posix()
        if rel in V1_FILES_NOT_MINE or rel.startswith("wakeword/"):
            continue
        typing_only = _type_checking_only(path)
        for name, _ in _imports(path):
            root = name.split(".")[0]
            if root in stdlib or root == "__future__" or name in typing_only or root in typing_only:
                continue
            if root == "jarvis":
                if not name.startswith(KIT_SAFE_JARVIS) and name != "jarvis.localspeech":
                    offenders.append(f"{rel}: {name} (cloud code)")
                continue
            if root in LEFT_OUT_RUNTIMES and rel.startswith("runtimes/"):
                continue  # named in the README's "What this kit leaves out"
            if KIT_THIRD_PARTY.get(root) not in pins:
                offenders.append(f"{rel}: {name} (not pinned)")
    assert offenders == []


def test_importing_the_cloud_app_and_the_kit_loads_no_runtime() -> None:
    script = (
        "import sys\n"
        "import jarvis.api\n"
        "import jarvis.localspeech.server, jarvis.localspeech.service\n"
        "import jarvis.localspeech.selftest, jarvis.localspeech.manager\n"
        "import jarvis.localspeech.__main__, jarvis.localspeech.engines\n"
        f"runtimes = {sorted(RUNTIME_PACKAGES)!r}\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in runtimes\n"
        "             or m.startswith('jarvis.localspeech.runtimes.'))\n"
        "print(bad)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
    )
    assert done.stdout.strip() == "[]", done.stderr[-2000:]


def test_every_runtime_module_imports_cleanly_without_its_package() -> None:
    for path in sorted((KIT / "runtimes").glob("*.py")):
        module = _module(path)
        done = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
        )
        assert done.returncode == 0, (module, done.stderr[-500:])
