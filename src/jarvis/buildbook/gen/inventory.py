# src/jarvis/buildbook/gen/inventory.py
"""R6 D2's Stack section and R6.3 D2b and G5 (docs/plans/r6-3-book-content.md): the technology
inventory, read from the checkout's own files, standard library only, deterministic.

- `stack(repo)`: R6's rows as before (Python and the build backend from pyproject.toml, the
  Dockerfile's base images, each direct dependency at its locked version, the CI jobs, the
  vendored releases named in api/console.py), then the inventory's rows (moved here from
  `gen/libs.py`, which keeps the Libraries & licences section and re-exports `stack`).
- `items(repo)`: what the cloud image's lock doesn't show (D2b): Android's libraries and build
  plugins (`android/gradle/libs.versions.toml`), the home kit's images
  (`deploy/home/docker-compose.yml`; JARVIS's own bridge image is not a row), the bridge's pins
  that the cloud lock doesn't hold (`deploy/home/bridge-requirements.txt`), and the dev tools (the
  `dev` extra of pyproject.toml, `tools/markdy/package-lock.json`'s direct packages). Each with
  one SPDX spelling of its licence where the file states one ("not stated" otherwise: nothing is
  typed here), and its use (`USE`): run-time, or build and maintenance.
- `spdx(licence)`: one spelling a licence ("Apache 2.0" -> "Apache-2.0", "MIT License" -> "MIT",
  "3-Clause BSD License" -> "BSD-3-Clause"; "BSD License" -> "BSD", the clause count unstated);
  each term of an OR / AND expression; an unknown spelling stays as given.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from dataclasses import dataclass
from typing import Any, Literal

from jarvis.buildbook.gen.code import clip, tree
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.sections import Stack, StackItem

NOT_STATED = "not stated"
LOCK = "requirements.lock"
CONSOLE = "src/jarvis/api/console.py"
ANDROID = "android/gradle/libs.versions.toml"
COMPOSE = "deploy/home/docker-compose.yml"
BRIDGE = "deploy/home/bridge-requirements.txt"
PYPROJECT = "pyproject.toml"
MARKDY = "tools/markdy/package-lock.json"
OWN_IMAGE = "jarvis-"  # the home kit's own bridge image, built on the laptop: not a library
RELEASE_NAMES = {"three": "three.js", "ort": "onnxruntime-web", "oww": "openWakeWord models"}
Use = Literal["run-time", "build and maintenance"]
RUN: Use = "run-time"
BUILD: Use = "build and maintenance"
# every Stack role and inventory group, and what it is used for (D2b's split)
USE: dict[str, Use] = {
    "language": RUN,
    "build backend": BUILD,
    "base image": RUN,
    "dependency": RUN,
    "ci job": BUILD,
    "vendored": RUN,
    "android library": RUN,
    "android build": BUILD,
    "home kit image": RUN,
    "home bridge": RUN,
    "dev tool": BUILD,
}
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)")
_SPEC = re.compile(r"\s*([A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*(.*)")
_IMAGE = re.compile(r"^\s*image:\s*(?:\$\{[A-Z0-9_]+:-)?([^\s}]+)\}?\s*(?:#.*)?$")
_ALL = re.compile(r"^#.*?\ball ([A-Za-z][\w.+-]*(?: \d[\d.]*)?)", re.MULTILINE)
_OP = re.compile(r"(\s+(?:OR|AND)\s+)")
_TERM = r"[A-Za-z0-9][A-Za-z0-9.+-]*"
_EXPRESSION = re.compile(rf"^{_TERM}(?:\s+(?:OR|AND|WITH)\s+{_TERM})*$")  # SPDX, no prose
_SPDX_RULES = (
    (r"apache(?: software)?(?: license)?,? (?:version )?2(?:\.0)?", "Apache-2.0"),
    (r"(?:the )?mit(?: license)?", "MIT"),
    (r"(?:3-clause bsd|bsd 3-clause|new bsd)(?: license)?", "BSD-3-Clause"),
    (r"(?:2-clause bsd|bsd 2-clause|simplified bsd)(?: license)?", "BSD-2-Clause"),
    (r"bsd(?: license)?", "BSD"),  # the clause count not stated
    (r"(?:psf|python software foundation)(?: license)?", "PSF-2.0"),
)
_SPDX = tuple((re.compile(rf"^{rule}$", re.IGNORECASE), name) for rule, name in _SPDX_RULES)


@dataclass(frozen=True)
class Item:
    group: str  # a key of USE
    name: str
    version: str
    licence: str  # one SPDX spelling, or "not stated"
    use: Use
    source: str  # the file it was read from


def spdx(licence: str) -> str:
    parts = _OP.split(licence.strip())
    out = [p if _OP.fullmatch(p) else _one(p) for p in parts]
    return "".join(out) if licence.strip() else licence


def _one(term: str) -> str:
    return next((name for rule, name in _SPDX if rule.match(term.strip())), term.strip())


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked(repo: Repo) -> tuple[tuple[str, str], ...]:
    pins = (_PIN.match(line) for line in (repo.text(LOCK) or "").splitlines())
    return tuple(sorted({(norm(m.group(1)), m.group(2)) for m in pins if m}))


def _item(group: str, name: str, version: str, licence: str, source: str) -> Item:
    return Item(group, clip(name, 80), clip(version, 40), spdx(licence), USE[group], source)


# ---- D2b: what the cloud image's lock doesn't show -------------------------------------------
def _android(repo: Repo) -> list[Item]:
    text = repo.text(ANDROID)
    try:
        cfg: dict[str, Any] = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError:
        return []
    stated = _ALL.search(text or "")
    licence = stated.group(1).rstrip(".") if stated else NOT_STATED  # "all Apache-2.0" (Part E)
    out = []
    for group, table, key, said in (
        ("android library", "libraries", "module", licence),
        ("android build", "plugins", "id", NOT_STATED),
    ):
        for row in cfg.get(table, {}).values():
            if isinstance(row, dict) and row.get(key):
                version = _android_version(row.get("version"), cfg.get("versions", {}))
                out.append(_item(group, str(row[key]), version, said, ANDROID))
    return sorted(out, key=lambda i: (i.group != "android library", i.name))


def _android_version(ref: object, versions: dict[str, Any]) -> str:
    """`version = "1.1.0"` or `version.ref = "agp"` (a name in `[versions]`)."""
    if isinstance(ref, dict):
        ref = versions.get(str(ref.get("ref", "")))
    return str(ref or "")


def _images(repo: Repo) -> list[Item]:
    out = []
    for line in (repo.text(COMPOSE) or "").splitlines():
        m = _IMAGE.match(line)
        ref = m.group(1) if m else ""
        name, _, tag = ref.rpartition(":") if ":" in ref.rsplit("/", 1)[-1] else (ref, "", "")
        short = name.rsplit("/", 1)[-1]
        if short and not short.startswith(OWN_IMAGE):
            out.append(_item("home kit image", short, tag, NOT_STATED, COMPOSE))
    return sorted(out, key=lambda i: i.name)


def _bridge(repo: Repo) -> list[Item]:
    text = repo.text(BRIDGE) or ""
    cloud = {n for n, _ in locked(repo)}
    notes = " ".join(ln.lstrip("# ") for ln in text.splitlines() if ln.startswith("#"))
    out = []
    for m in (_PIN.match(line) for line in text.splitlines()):
        if m and norm(m.group(1)) not in cloud:
            name, version = norm(m.group(1)), m.group(2)
            said = re.search(rf"{re.escape(name)} {re.escape(version)} \(([^)]+)\)", notes)
            note = said.group(1).strip() if said else ""  # the file's own note, when SPDX
            licence = note if _EXPRESSION.match(note) else NOT_STATED
            out.append(_item("home bridge", name, version, licence, BRIDGE))
    return sorted(out, key=lambda i: i.name)


def _dev(repo: Repo) -> list[Item]:
    try:
        cfg = tomllib.loads(repo.text(PYPROJECT) or "")
    except tomllib.TOMLDecodeError:
        cfg = {}
    specs = cfg.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    found = [m for m in (_SPEC.match(s) for s in specs if isinstance(s, str)) if m]
    out = [
        _item("dev tool", norm(m.group(1)), m.group(2).strip(), NOT_STATED, PYPROJECT)
        for m in found
    ]
    return out + _npm(repo)


def _npm(repo: Repo) -> list[Item]:
    try:
        packages = json.loads(repo.text(MARKDY) or "{}").get("packages", {})
    except (ValueError, AttributeError):
        return []
    root = packages.get("", {}) if isinstance(packages, dict) else {}
    direct = sorted({**root.get("dependencies", {}), **root.get("devDependencies", {})})
    out = []
    for name in direct:
        pkg = packages.get(f"node_modules/{name}", {})
        licence = pkg.get("license") if isinstance(pkg.get("license"), str) else NOT_STATED
        out.append(_item("dev tool", name, str(pkg.get("version", "")), licence, MARKDY))
    return out


def items(repo: Repo) -> tuple[Item, ...]:
    """The inventory's rows in a fixed order: Android, the home kit, the bridge, the dev tools."""
    return (*_android(repo), *_images(repo), *_bridge(repo), *_dev(repo))


# ---- R6's Stack (moved from gen/libs.py unchanged), then the inventory -------------------------
def _pyproject(repo: Repo, pins: dict[str, str]) -> tuple[list[StackItem], list[StackItem]]:
    """(Python and the build backend, the direct dependencies by name)."""
    try:
        cfg = tomllib.loads(repo.text(PYPROJECT) or "")
    except tomllib.TOMLDecodeError:
        return [], []
    project, out = cfg.get("project", {}), []
    if project.get("requires-python"):
        out.append(
            StackItem(
                role="language", name="Python", version=project["requires-python"], source=PYPROJECT
            )
        )
    backend = cfg.get("build-system", {}).get("build-backend")
    deps = []
    for spec in project.get("dependencies", []):
        m = _SPEC.match(spec)
        if m:
            name = norm(m.group(1))
            version = clip(pins.get(name) or m.group(2).strip(), 40)
            deps.append(StackItem(role="dependency", name=name, version=version, source=PYPROJECT))
    if backend:
        out.append(StackItem(role="build backend", name=backend, source=PYPROJECT))
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
    r6 = [*head, *_base_images(repo), *deps, *_ci_jobs(repo), *_vendored_releases(repo)]
    rows = [
        StackItem(role=i.group, name=i.name, version=i.version, source=i.source)
        for i in items(repo)
    ]
    return Stack(items=(*r6, *rows))


__all__ = [
    "CONSOLE",
    "LOCK",
    "NOT_STATED",
    "USE",
    "Item",
    "items",
    "locked",
    "norm",
    "spdx",
    "stack",
]
