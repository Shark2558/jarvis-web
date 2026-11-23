# scripts/arch_inventory.py
"""R6.1 D6, the code side of `arch_coverage.py`: what the repository has that the guide's
component catalogue must name. Read from the code, never from the guide:

- top-level packages (with or without `__init__.py`) and modules under `src/jarvis/`, and the
  console's `src/jarvis/api/static/console*.js` modules
- the Cloud Scheduler jobs `deploy/*.sh` creates (`$VAR` and `${VAR:-default}` resolved)
- outside services: `jarvis.buildbook.gen.services.inventory` (R6.3 seam 17; the build book's
  fact pack counts the same list): `Settings` fields in `config.py` (an AST) mapped by
  `service_fields`, and API hosts in the code's string literals mapped by `api_hosts`; an
  unknown secret, key, token or URL setting, or an unknown `api.*`, `*.googleapis.com` or
  `*.internal` host, is a problem
- Firestore collections, in every naming idiom the stores use
Tables: `arch_coverage.json`.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[1] / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jarvis.buildbook.gen import services  # noqa: E402


def _tables() -> tuple[dict[str, Any], str | None]:
    try:
        raw = json.loads(Path(__file__).with_name("arch_coverage.json").read_text(encoding="utf-8"))
        return (raw, None) if isinstance(raw, dict) else ({}, "arch_coverage.json is not a table")
    except (OSError, ValueError) as exc:
        return {}, f"arch_coverage.json can't be read ({type(exc).__name__})"


TABLES, TABLES_ERROR = _tables()


DIAGRAMS: tuple[str, ...] = tuple(TABLES.get("diagrams", ()))
_COLLECTION = (
    re.compile(r"\{(?:self\.)?_?(?:prefix|p)\}([a-z][a-z0-9_]*)"),
    re.compile(r"_path\(\"([a-z][a-z0-9_]*)\""),
    re.compile(r"\b[A-Z_]*COLLECTION\s*=\s*\"([a-z][a-z0-9_]*)\""),
    re.compile(r"\.collection\(\s*f?\"(?:\{[^}\"]*\})?([a-z][a-z0-9_]*)"),
)
_JOB = re.compile(r"scheduler\s+jobs\s+create\s+\w+\s+(\"[^\"]+\"|\S+)")


@dataclass(frozen=True)
class Inventory:
    code: tuple[str, ...]
    console: tuple[str, ...]
    jobs: tuple[str, ...]
    services: tuple[str, ...]
    collections: tuple[str, ...]
    problems: tuple[str, ...]  # settings or hosts the tables above don't know


def _code_items(repo: Path) -> tuple[str, ...]:
    """Top-level packages (with or without `__init__.py`) and modules under `src/jarvis/`."""
    root = repo / "src/jarvis"
    dirs = [
        f"src/jarvis/{p.name}"
        for p in root.iterdir()
        if p.is_dir() and p.name[0] not in "_." and any(p.rglob("*.py"))
    ]
    mods = [f"src/jarvis/{p.name}" for p in root.glob("*.py") if p.name != "__init__.py"]
    return tuple(sorted(dirs + mods))


def _jobs(repo: Path) -> tuple[str, ...]:
    jobs: set[str] = set()
    for sh in sorted((repo / "deploy").glob("*.sh")):
        text = sh.read_text(encoding="utf-8")
        for m in _JOB.finditer(text):
            jobs.add(_resolve(m.group(1).strip('"'), text))
    return tuple(sorted(jobs))


def _resolve(arg: str, text: str) -> str:
    default = re.fullmatch(r"\$\{\w+:-([^}]+)\}", arg)
    if default:
        return default.group(1)
    var = re.fullmatch(r"\$\{?(\w+)\}?", arg)
    if var:
        found = re.search(rf"^\s*{var.group(1)}=\"?([^\"\s]+)\"?", text, re.MULTILINE)
        return found.group(1) if found else f"<unresolved {arg}>"
    return arg


def _collections(repo: Path) -> tuple[str, ...]:
    names: set[str] = set()
    for path in services.py_files(repo):
        text = path.read_text(encoding="utf-8")
        for pattern in _COLLECTION:
            names.update(pattern.findall(text))
    return tuple(sorted(names))


def inventory(repo: Path) -> Inventory:
    static = repo / "src/jarvis/api/static"
    found = services.inventory(repo, TABLES)  # R6.3 seam 17: the one services list
    return Inventory(
        code=_code_items(repo),
        console=tuple(sorted(p.name for p in static.glob("console*.js"))),
        jobs=_jobs(repo),
        services=found.names,
        collections=_collections(repo),
        problems=found.problems,
    )
