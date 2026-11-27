# src/jarvis/buildbook/gen/services.py
"""R6.3 seam 17 (docs/plans/r6-3-book-content.md D2, D10 G3, plan review M7): the ONE list of the
outside services JARVIS uses, moved here unchanged from `scripts/arch_inventory.py` so the guide's
coverage check and the build book's fact pack (`services.count`, the full book's service pages)
count the same 31.

Read from the code, never from the guide: `Settings` fields in `src/jarvis/config.py` (an AST)
mapped by the table's `service_fields` (a key ending in "_" is a prefix), and API hosts in the
code's string literals (not docstrings) mapped by `api_hosts`. An unknown secret, key, token or
URL setting, or an unknown `api.*`, `*.googleapis.com` or `*.internal` host, is a problem. The
tables are `scripts/arch_coverage.json` (`tables(repo)`), or the ones the caller passes. Standard
library only; the repository is a path.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TABLE = "scripts/arch_coverage.json"
_SECRET_NAME = ("_key", "_token", "_secret", "_url")
_API_HOST = re.compile(r"^(?:api\.[a-z0-9.-]+|[a-z0-9-]+\.googleapis\.com|[a-z0-9.-]+\.internal)$")
_HOST_IN = re.compile(r"\bhttps?://([A-Za-z0-9.-]+)")
_ADD_FIELD = "add it to arch_coverage.json service_fields"


@dataclass(frozen=True)
class Services:
    names: tuple[str, ...]  # sorted, unique
    problems: tuple[str, ...]  # settings first, then hosts


def tables(repo: Path) -> dict[str, Any]:
    """`scripts/arch_coverage.json` of the repository (ValueError when it isn't a table)."""
    try:
        raw = json.loads((repo / TABLE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"arch_coverage.json can't be read ({type(exc).__name__})") from None
    if not isinstance(raw, dict):
        raise ValueError("arch_coverage.json is not a table")
    return raw


def py_files(repo: Path) -> list[Path]:
    return sorted((repo / "src/jarvis").rglob("*.py"))


def _class_body(tree: ast.Module, name: str) -> list[ast.stmt] | None:
    found = next((c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == name), None)
    return None if found is None else found.body


def _base_body(repo: Path, tree: ast.Module, name: str) -> list[ast.stmt]:
    """The body of a base class config.py imports from a `jarvis` module (R18:
    `config_calls.CallsConfig`), as `gen/code.py`'s `settings_nodes` reads it; else nothing."""
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("jarvis."):
            continue
        if not any(a.name == name and a.asname is None for a in node.names):
            continue
        path = repo.joinpath("src", *str(node.module).split(".")).with_suffix(".py")
        if not path.is_file():
            return []
        return _class_body(ast.parse(path.read_text(encoding="utf-8")), name) or []
    return []


def settings_fields(repo: Path) -> list[tuple[str, str]]:
    """(field name, annotation) of `class Settings` in config.py, read as an AST: its `jarvis`
    base classes' fields first (the last base first, Pydantic's order), then its own."""
    tree = ast.parse((repo / "src/jarvis/config.py").read_text(encoding="utf-8"))
    cls = next((c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "Settings"), None)
    if cls is None:
        return []
    body = [
        n
        for base in reversed(cls.bases)
        if isinstance(base, ast.Name)
        for n in _base_body(repo, tree, base.id)
    ]
    out: list[tuple[str, str]] = []
    for n in [*body, *cls.body]:
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.append((n.target.id, ast.unparse(n.annotation)))
    return out


def _services_of(field: str, fields: Iterable[Any]) -> tuple[str, ...] | None:
    for key, services in fields:
        if field == key or (key.endswith("_") and field.startswith(key)):
            return tuple(services)
    return None


def _settings_services(repo: Path, t: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    services: set[str] = set()
    problems: list[str] = []
    fields, internal = tuple(t.get("service_fields", ())), frozenset(t.get("internal_secrets", ()))
    for name, annotation in settings_fields(repo):
        found = _services_of(name, fields)
        if found:
            services.update(found)
        elif name not in internal and ("SecretStr" in annotation or name.endswith(_SECRET_NAME)):
            problems.append(f"setting `{name}` names no known outside service: {_ADD_FIELD}")
    return services, problems


def literals(tree: ast.AST) -> Iterable[str]:
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


def _host_services(repo: Path, t: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    hosts: dict[str, str] = dict(t.get("api_hosts", {}))
    not_services = frozenset(t.get("not_services", ()))
    services: set[str] = set()
    unknown: set[str] = set()
    for path in py_files(repo):
        for text in literals(ast.parse(path.read_text(encoding="utf-8"))):
            for host in (h.lower() for h in _HOST_IN.findall(text)):
                if host in hosts:
                    services.add(hosts[host])
                elif host not in not_services and _API_HOST.match(host):
                    unknown.add(host)
    what = "in the code names no known service: add it to arch_coverage.json api_hosts"
    return services, [f"API host `{h}` {what}" for h in sorted(unknown)]


def inventory(repo: Path, table: Mapping[str, Any] | None = None) -> Services:
    """Every outside service the settings and the code's API hosts name, and the problems."""
    t = tables(repo) if table is None else table
    settings, p1 = _settings_services(repo, t)
    hosts, p2 = _host_services(repo, t)
    return Services(names=tuple(sorted(settings | hosts)), problems=tuple(p1 + p2))


__all__ = ["TABLE", "Services", "inventory", "literals", "py_files", "settings_fields", "tables"]
