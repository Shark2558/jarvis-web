# scripts/arch_inventory.py
"""R6.1 D6, the code side of `arch_coverage.py`: what the repository has that the guide's
component catalogue must name. Read from the code, never from the guide:

- top-level packages (with or without `__init__.py`) and modules under `src/jarvis/`, and the
  console's `src/jarvis/api/static/console*.js` modules
- the Cloud Scheduler jobs `deploy/*.sh` creates (`$VAR` and `${VAR:-default}` resolved)
- outside services: `Settings` fields in `config.py` (read as an AST) mapped by `service_fields`,
  and API hosts in the code's string literals (not docstrings) mapped by `api_hosts`; an unknown
  secret, key, token or URL setting, or an unknown `api.*`, `*.googleapis.com` or `*.internal`
  host, is a problem
- Firestore collections, in every naming idiom the stores use
Tables: `arch_coverage.json`.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _tables() -> tuple[dict[str, Any], str | None]:
    try:
        raw = json.loads(Path(__file__).with_name("arch_coverage.json").read_text(encoding="utf-8"))
        return (raw, None) if isinstance(raw, dict) else ({}, "arch_coverage.json is not a table")
    except (OSError, ValueError) as exc:
        return {}, f"arch_coverage.json can't be read ({type(exc).__name__})"


TABLES, TABLES_ERROR = _tables()


DIAGRAMS: tuple[str, ...] = tuple(TABLES.get("diagrams", ()))
# Settings -> outside services. A key ending in "_" is a prefix; any other key is a field name.
SERVICE_FIELDS = tuple((k, tuple(v)) for k, v in TABLES.get("service_fields", ()))
INTERNAL_SECRETS = frozenset(TABLES.get("internal_secrets", ()))
API_HOSTS: dict[str, str] = dict(TABLES.get("api_hosts", {}))
NOT_SERVICES = frozenset(TABLES.get("not_services", ()))
_SECRET_NAME = ("_key", "_token", "_secret", "_url")
_API_HOST = re.compile(r"^(?:api\.[a-z0-9.-]+|[a-z0-9-]+\.googleapis\.com|[a-z0-9.-]+\.internal)$")
_HOST_IN = re.compile(r"\bhttps?://([A-Za-z0-9.-]+)")
_COLLECTION = (
    re.compile(r"\{(?:self\.)?_?(?:prefix|p)\}([a-z][a-z0-9_]*)"),
    re.compile(r"_path\(\"([a-z][a-z0-9_]*)\""),
    re.compile(r"\b[A-Z_]*COLLECTION\s*=\s*\"([a-z][a-z0-9_]*)\""),
    re.compile(r"\.collection\(\s*f?\"(?:\{[^}\"]*\})?([a-z][a-z0-9_]*)"),
)
_JOB = re.compile(r"scheduler\s+jobs\s+create\s+\w+\s+(\"[^\"]+\"|\S+)")
_ADD_FIELD = "add it to arch_coverage.json service_fields"


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


def _py_files(repo: Path) -> list[Path]:
    return sorted((repo / "src/jarvis").rglob("*.py"))


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


def _settings_fields(repo: Path) -> list[tuple[str, str]]:
    """(field name, annotation) of `class Settings` in config.py, read as an AST."""
    tree = ast.parse((repo / "src/jarvis/config.py").read_text(encoding="utf-8"))
    body = [
        n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "Settings" for n in c.body
    ]
    out: list[tuple[str, str]] = []
    for n in body:
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.append((n.target.id, ast.unparse(n.annotation)))
    return out


def _services_of(field: str) -> tuple[str, ...] | None:
    for key, services in SERVICE_FIELDS:
        if field == key or (key.endswith("_") and field.startswith(key)):
            return services
    return None


def _settings_services(repo: Path) -> tuple[set[str], list[str]]:
    services: set[str] = set()
    problems: list[str] = []
    for name, annotation in _settings_fields(repo):
        found = _services_of(name)
        if found:
            services.update(found)
        elif name not in INTERNAL_SECRETS and (
            "SecretStr" in annotation or name.endswith(_SECRET_NAME)
        ):
            problems.append(f"setting `{name}` names no known outside service: {_ADD_FIELD}")
    return services, problems


def _literals(tree: ast.AST) -> Iterable[str]:
    """String constants that are not docstrings."""
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            yield n.value


def _host_services(repo: Path) -> tuple[set[str], list[str]]:
    services: set[str] = set()
    unknown: set[str] = set()
    for path in _py_files(repo):
        for text in _literals(ast.parse(path.read_text(encoding="utf-8"))):
            for host in (h.lower() for h in _HOST_IN.findall(text)):
                if host in API_HOSTS:
                    services.add(API_HOSTS[host])
                elif host not in NOT_SERVICES and _API_HOST.match(host):
                    unknown.add(host)
    what = "in the code names no known service: add it to arch_coverage.json api_hosts"
    return services, [f"API host `{h}` {what}" for h in sorted(unknown)]


def _collections(repo: Path) -> tuple[str, ...]:
    names: set[str] = set()
    for path in _py_files(repo):
        text = path.read_text(encoding="utf-8")
        for pattern in _COLLECTION:
            names.update(pattern.findall(text))
    return tuple(sorted(names))


def inventory(repo: Path) -> Inventory:
    static = repo / "src/jarvis/api/static"
    settings, p1 = _settings_services(repo)
    hosts, p2 = _host_services(repo)
    return Inventory(
        code=_code_items(repo),
        console=tuple(sorted(p.name for p in static.glob("console*.js"))),
        jobs=_jobs(repo),
        services=tuple(sorted(settings | hosts)),
        collections=_collections(repo),
        problems=tuple(p1 + p2),
    )
