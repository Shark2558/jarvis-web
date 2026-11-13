# src/jarvis/buildbook/gen/libs.py
"""R6 D2: the Libraries & licences and Stack sections.

Libraries: every pin in `requirements.lock` with its licence as `requirements.licences.json`
records it for that exact version (gen/licences.py; refreshed from the installed dist's metadata:
License-Expression -> License, when it is one short line -> the License classifiers -> "not
stated"), so the section never depends on what is installed where it is built; the vendored
three.js, onnxruntime-web and openWakeWord code, the wake-word models and the console fonts with
the licence their own licence file states. Copyleft (GPL / AGPL / LGPL, and file-level MPL / EPL /
EUPL / CDDL, with no permissive choice; SPDX AND binds tighter than OR) and non-commercial (the CC
BY-NC-SA wake model) licences are flagged, and `licence_limits` turns each flag into a Limitation.

Stack: Python and the build backend (pyproject.toml), the Dockerfile's base images, each direct
dependency at its locked version, the CI jobs, and the vendored releases named in api/console.py.
"""

from __future__ import annotations

import ast
import importlib.metadata as md
import re
import tomllib
from collections.abc import Callable, Sequence
from typing import Any, Literal

from jarvis.buildbook.gen.code import clip, tree
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.sections import Library, Limitation, Stack, StackItem

NOT_STATED = "not stated"
LOCK = "requirements.lock"
STATIC = "src/jarvis/api/static/"
CONSOLE = "src/jarvis/api/console.py"
LicenceLookup = Callable[[str], str]
Flag = Literal["copyleft", "non_commercial"]

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)")
_NC = re.compile(r"\bNC\b|NonCommercial|non-commercial", re.IGNORECASE)
# GPL / AGPL / LGPL, and file-level (weak) copyleft: MPL, EPL, EUPL, CDDL, flagged like LGPL
_COPYLEFT = re.compile(
    r"\b[AL]?GPL|General Public License|\bMPL\b|Mozilla Public License|\bEPL\b|"
    r"Eclipse Public License|\bEUPL\b|\bCDDL\b",
    re.IGNORECASE,
)
_TEXT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CC-BY-NC-SA-4.0", re.compile(r"NonCommercial-ShareAlike 4\.0|CC BY-NC-SA 4\.0")),
    ("CC-BY-NC", re.compile(r"NonCommercial|\bBY-NC\b")),
    ("AGPL-3.0", re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE", re.I)),
    ("LGPL", re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE", re.I)),
    ("GPL-3.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 3", re.I)),
    ("GPL-2.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 2", re.I)),
    ("GPL", re.compile(r"GNU GENERAL PUBLIC LICENSE", re.I)),
    ("OFL-1.1", re.compile(r"SIL Open Font License")),
    ("Apache-2.0", re.compile(r"Apache License[\s\S]{0,80}Version 2\.0", re.I)),
    ("MIT", re.compile(r"\bMIT License\b|Permission is hereby granted, free of charge")),
    ("BSD", re.compile(r"Redistribution and use in source and binary forms")),
)
# vendored licence files -> (library, its release constant in api/console.py, kind, role)
VENDORED: dict[str, tuple[str, str, str, str]] = {
    "vendor/LICENSE-three.txt": ("three.js", "THREE_RELEASE", "vendored", "3d"),
    "vendor/ort/LICENSE-onnxruntime.txt": ("onnxruntime-web", "ORT_RELEASE", "vendored", "voice"),
    "wakeword/LICENSE.txt": ("openWakeWord models", "WAKEWORD_RELEASE", "model", "voice"),
    "wakeword/LICENSE-openwakeword-code.txt": (
        "openWakeWord code (ported)",
        "",
        "vendored",
        "voice",
    ),
    # R7 D14, I0 seam 24: the vision files Part B vendors under vendor/vision/<release>/ (each
    # licence beside the release folders); a version comes from Part B's MANIFEST.json
    "vendor/vision/LICENSE-mediapipe-tasks-vision.txt": (
        "MediaPipe Tasks Vision",
        "",
        "vendored",
        "vision",
    ),
    "vendor/vision/LICENSE-mediapipe-models.txt": (
        "MediaPipe pose and object models",
        "",
        "model",
        "vision",
    ),
    "vendor/vision/LICENSE-tesseract.js.txt": ("tesseract.js", "", "vendored", "vision"),
    "vendor/vision/LICENSE-tesseract.js-core.txt": ("tesseract.js-core", "", "vendored", "vision"),
    "vendor/vision/LICENSE-tessdata-eng.txt": ("Tesseract English data", "", "model", "vision"),
    "vendor/vision/LICENSE-zxing-wasm.txt": ("zxing-wasm", "", "vendored", "vision"),
}
RELEASE_NAMES = {"three": "three.js", "ort": "onnxruntime-web", "oww": "openWakeWord models"}
ROLES: dict[str, tuple[str, ...]] = {
    "ai": ("anthropic", "jiter", "docstring-parser"),
    "web": ("fastapi", "starlette", "uvicorn", "httpx", "httpx2", "httpcore", "httpcore2", "h11",
            "anyio", "sniffio", "websockets", "httptools", "uvloop", "watchfiles", "idna",
            "certifi", "urllib3", "requests", "charset-normalizer", "truststore", "click"),
    "data": ("pydantic", "pydantic-core", "pydantic-settings", "annotated-types",
             "annotated-doc", "typing-extensions", "typing-inspection", "protobuf", "proto-plus",
             "cbor2", "pyyaml", "python-dotenv", "packaging", "tzdata"),
    "google": ("google-api-core", "google-auth", "google-cloud-core", "google-cloud-firestore",
               "googleapis-common-protos", "grpcio", "grpcio-status", "opentelemetry-api"),
    "security": ("cryptography", "cffi", "pycparser", "authlib", "joserfc", "itsdangerous",
                 "pyopenssl", "pyasn1", "pyasn1-modules", "webauthn"),
    "storage": ("redis",),
    "documents": ("pypdf", "python-docx", "lxml"),
    "build": ("pip", "setuptools", "wheel"),
}  # fmt: skip
_ROLE_OF = {name: role for role, names in ROLES.items() for name in names}
_KIND_ORDER = {"python": 0, "vendored": 1, "model": 2, "font": 3}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ---- licences --------------------------------------------------------------------------------
def licence_from_meta(expression: str | None, field: str | None, classifiers: Sequence[str]) -> str:
    if expression and expression.strip():
        return clip(expression.strip(), 80)
    one = (field or "").strip()
    if one and "\n" not in one and len(one) <= 80 and one.upper() != "UNKNOWN":
        return one
    named = [c.split("::")[-1].strip() for c in classifiers if c.startswith("License ::")]
    named = [n for n in named if n and n != "OSI Approved"]
    return clip(" OR ".join(named), 80) if named else NOT_STATED


def _first(values: list[Any] | None) -> str | None:
    return str(values[0]) if values else None


def installed_licence(name: str) -> str:
    try:
        meta = md.metadata(name)
    except md.PackageNotFoundError:
        return NOT_STATED
    return licence_from_meta(
        _first(meta.get_all("License-Expression")),
        _first(meta.get_all("License")),
        meta.get_all("Classifier") or [],
    )


def licence_from_text(text: str) -> str:
    return next((spdx for spdx, rule in _TEXT_RULES if rule.search(text)), NOT_STATED)


def _split(expr: str, op: str) -> list[str]:
    """`expr` split on `op` (AND / OR, any case) outside brackets."""
    parts, depth, start = [], 0, 0
    for m in re.finditer(rf"[()]|\s+{op}\s+", expr, flags=re.IGNORECASE):
        if m.group(0) == "(":
            depth += 1
        elif m.group(0) == ")":
            depth = max(depth - 1, 0)
        elif depth == 0:
            parts.append(expr[start : m.start()])
            start = m.end()
    return [*parts, expr[start:]]


def _unavoidable(expr: str, term: re.Pattern[str]) -> bool:
    """Does every choice an SPDX expression offers include a licence matching `term`? (OR: each
    alternative must; AND binds tighter: any part will do; a bracketed group is read inside.)"""
    alternatives = _split(expr, "OR")
    if len(alternatives) > 1:
        return all(_unavoidable(a, term) for a in alternatives)
    parts = _split(expr, "AND")
    if len(parts) > 1:
        return any(_unavoidable(p, term) for p in parts)
    inner = expr.strip()
    if _wrapped(inner):
        return _unavoidable(inner[1:-1], term)
    return bool(term.search(inner))


def _wrapped(expr: str) -> bool:
    """ "(...)" with the first bracket closed by the last one."""
    if not (expr.startswith("(") and expr.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(expr):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0 and i < len(expr) - 1:
            return False
    return True


def flag_of(licence: str) -> Flag | None:
    if _unavoidable(licence, _NC):
        return "non_commercial"
    if _unavoidable(licence, _COPYLEFT):
        return "copyleft"
    return None


# ---- libraries -------------------------------------------------------------------------------
def locked(repo: Repo) -> tuple[tuple[str, str], ...]:
    pins = (_PIN.match(line) for line in (repo.text(LOCK) or "").splitlines())
    return tuple(sorted({(_norm(m.group(1)), m.group(2)) for m in pins if m}))


def _releases(repo: Repo) -> dict[str, str]:
    """`THREE_RELEASE = "three-0.187.0"` -> {"THREE_RELEASE": "0.187.0"} (api/console.py)."""
    module = tree(repo, CONSOLE)
    found: dict[str, str] = {}
    for node in module.body if module else []:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            value = node.value.value
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.endswith("_RELEASE") and isinstance(value, str):
                    found[t.id] = value.split("-", 1)[-1]
    return found


def _vendored(repo: Repo) -> list[Library]:
    releases, out = _releases(repo), []
    for rel in repo.under(STATIC):
        sub, name = rel[len(STATIC) :], rel.rsplit("/", 1)[-1]
        if sub in VENDORED:
            lib, const, kind, role = VENDORED[sub]
        elif sub.startswith("fonts/") and name.startswith(("OFL-", "LICENSE-")):
            stem = name.split("-", 1)[1].rsplit(".", 1)[0]
            lib, const, kind, role = stem.replace("-", " ").title(), "", "font", "console"
        else:
            continue
        licence = licence_from_text(repo.text(rel) or "")
        out.append(
            Library.model_validate(
                {
                    "name": lib,
                    "version": releases.get(const, ""),
                    "kind": kind,
                    "licence": licence,
                    "flag": flag_of(licence),
                    "role": role,
                }
            )
        )
    return out


def sort_key(lib: Library) -> tuple[int, str]:
    return (_KIND_ORDER[lib.kind], lib.name.lower())


def libraries(repo: Repo, licence: LicenceLookup) -> tuple[Library, ...]:
    python = []
    for name, version in locked(repo):
        lic = licence(name)
        python.append(
            Library(
                name=name,
                version=clip(version, 40),
                kind="python",
                licence=lic,
                flag=flag_of(lic),
                role=_ROLE_OF.get(name, "other"),
            )
        )
    return tuple(sorted([*python, *_vendored(repo)], key=sort_key))


def licence_limits(libs: Sequence[Library], label: str) -> tuple[Limitation, ...]:
    words = {
        "non_commercial": "personal, non-commercial use only.",
        "copyleft": "copyleft; its terms apply if JARVIS is ever shared.",
    }
    return tuple(
        Limitation.model_validate(
            {
                "text": clip(f"{lib.name} ({lib.licence}): {words[lib.flag]}", 200),
                "kind": "licence",
                "source": LOCK if lib.kind == "python" else STATIC.rstrip("/"),
                "release": label,
            }
        )
        for lib in libs
        if lib.flag
    )


# ---- stack -----------------------------------------------------------------------------------
def _pyproject(repo: Repo, pins: dict[str, str]) -> tuple[list[StackItem], list[StackItem]]:
    """(Python and the build backend, the direct dependencies by name)."""
    try:
        cfg = tomllib.loads(repo.text("pyproject.toml") or "")
    except tomllib.TOMLDecodeError:
        return [], []
    project, out = cfg.get("project", {}), []
    if project.get("requires-python"):
        out.append(
            StackItem(
                role="language",
                name="Python",
                version=project["requires-python"],
                source="pyproject.toml",
            )
        )
    backend = cfg.get("build-system", {}).get("build-backend")
    deps = []
    for spec in project.get("dependencies", []):
        m = re.match(r"\s*([A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*(.*)", spec)
        if m:
            name = _norm(m.group(1))
            deps.append(
                StackItem(
                    role="dependency",
                    name=name,
                    version=clip(pins.get(name) or m.group(2).strip(), 40),
                    source="pyproject.toml",
                )
            )
    if backend:
        out.append(StackItem(role="build backend", name=backend, source="pyproject.toml"))
    return out, sorted(deps, key=lambda i: i.name)


def _base_images(repo: Repo) -> list[StackItem]:
    out = []
    for line in (repo.text("Dockerfile") or "").splitlines():
        m = re.match(r"^\s*FROM\s+(?:--\S+\s+)*([^\s:@]+)(?::([^\s@]+))?", line, re.IGNORECASE)
        if m:
            out.append(
                StackItem(
                    role="base image",
                    name=clip(m.group(1), 80),
                    version=clip(m.group(2) or "", 40),
                    source="Dockerfile",
                )
            )
    return out


def _ci_jobs(repo: Repo) -> list[StackItem]:
    out = []
    for rel in repo.under(".github/workflows/"):
        in_jobs = False
        for line in (repo.text(rel) or "").splitlines():
            if re.match(r"^jobs:\s*(#.*)?$", line):
                in_jobs = True
            elif in_jobs and line and not line[0].isspace() and not line.startswith("#"):
                in_jobs = False
            elif in_jobs and (m := re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", line)):
                out.append(StackItem(role="ci job", name=m.group(1), source=rel))
    return out


def _vendored_releases(repo: Repo) -> list[StackItem]:
    out = []
    module = tree(repo, CONSOLE)
    for node in module.body if module else []:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)):
            continue
        value = node.value.value
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if isinstance(value, str) and any(n.endswith("_RELEASE") for n in names):
            head, _, version = value.partition("-")
            name = RELEASE_NAMES.get(head, head)
            out.append(StackItem(role="vendored", name=name, version=version, source=CONSOLE))
    return out


def stack(repo: Repo) -> Stack:
    head, deps = _pyproject(repo, dict(locked(repo)))
    items = [*head, *_base_images(repo), *deps, *_ci_jobs(repo), *_vendored_releases(repo)]
    return Stack(items=tuple(items))


__all__ = [
    "LOCK",
    "NOT_STATED",
    "LicenceLookup",
    "flag_of",
    "installed_licence",
    "libraries",
    "licence_from_meta",
    "licence_from_text",
    "licence_limits",
    "locked",
    "sort_key",
    "stack",
]
