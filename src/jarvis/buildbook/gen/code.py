# src/jarvis/buildbook/gen/code.py
"""R6 D2: what the generator reads from the code, as text and ASTs (it imports nothing from the
app, so it documents exactly the checkout it is given — the real repo or the test fixture).

- AST look-ups: `module_path`, `tree`, `defines` (the flows' symbol check), `top_value` and
  `literal_args` (literal constants: prices, purposes, alert kinds).
- Architecture: `package_names` / `packages` — every `src/jarvis/*` package and top-level module,
  its tracked files, its lines of code and the first line of its docstring, in its layer.
- Integrations: `settings_fields` (class `Settings` in config.py: names and descriptions),
  `integrations` (services by setting prefix and probe, keyring purposes, alert kinds + levels).
  R6.3 G3: after the rows in plain words, one row for each of the coverage checker's services
  (`gen/services.inventory`, 31 on R6.3) none of them stands for (`services_named`).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from jarvis.buildbook import plain
from jarvis.buildbook.gen import services as services_mod
from jarvis.buildbook.gen.layers import layer_for
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.sections import AlertRow, Integrations, Package, Service

SRC = "src/jarvis/"
CODE_SUFFIXES = (".py", ".js", ".mjs", ".css", ".html")
NOT_COUNTED = ("src/jarvis/api/static/vendor/",)  # vendored, minified: not our lines
SUMMARY_MAX = 200
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


# ---- AST look-ups ----------------------------------------------------------------------------
def module_path(repo: Repo, dotted: str) -> str | None:
    """`core.brain` -> `src/jarvis/core/brain.py` (or the package's `__init__.py`)."""
    base = SRC + dotted.replace(".", "/")
    for rel in (f"{base}.py", f"{base}/__init__.py"):
        if repo.has(rel):
            return rel
    return None


def tree(repo: Repo, rel: str | None) -> ast.Module | None:
    """The module's AST; None only when it isn't in the checkout. A tracked module that can't be
    read or parsed fails (the book would otherwise quietly drop what it says)."""
    if rel is None or not repo.has(rel):
        return None
    text = repo.text(rel)
    if text is None:
        raise GenError(f"{rel} can't be read as UTF-8 text")
    try:
        return ast.parse(text)
    except SyntaxError:
        raise GenError(f"{rel} isn't valid Python") from None


def _names(node: ast.stmt) -> tuple[str, ...]:
    if isinstance(node, _DEFS):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(t.id for t in node.targets if isinstance(t, ast.Name))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return (node.target.id,)
    return ()


def _find(body: list[ast.stmt], name: str) -> ast.stmt | None:
    return next((n for n in body if name in _names(n)), None)


def defines(module: ast.Module, name: str | None, attr: str | None) -> bool:
    """The module defines `name` (a def, class or assignment); `attr` inside that class."""
    if name is None:
        return attr is None
    node = _find(module.body, name)
    if node is None or attr is None:
        return node is not None
    return isinstance(node, ast.ClassDef) and _find(node.body, attr) is not None


def _value(node: ast.stmt | None) -> ast.expr | None:
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return node.value
    return None


def top_expr(module: ast.Module, name: str) -> ast.expr | None:
    """The expression a top-level `name = ...` (or `name: T = ...`) assigns."""
    return _value(_find(module.body, name))


def top_value(module: ast.Module, name: str) -> Any:
    """A top-level constant's literal value (None when absent or not a literal)."""
    value = _value(_find(module.body, name))
    if value is None:
        return None
    if isinstance(value, ast.Call) and value.args:  # MappingProxyType({...}) and the like
        value = value.args[0]
    try:
        return ast.literal_eval(value)
    except ValueError:
        return None


def literal_args(module: ast.Module, name: str) -> tuple[str, ...]:
    """`Name = Literal["a", "b"]` -> ("a", "b")."""
    value = _value(_find(module.body, name))
    if not isinstance(value, ast.Subscript):
        return ()
    items = value.slice.elts if isinstance(value.slice, ast.Tuple) else [value.slice]
    return tuple(i.value for i in items if isinstance(i, ast.Constant) and isinstance(i.value, str))


# ---- architecture ----------------------------------------------------------------------------
def package_names(repo: Repo) -> tuple[str, ...]:
    names = set()
    for rel in repo.under(SRC):
        parts = rel[len(SRC) :].split("/")
        if len(parts) == 2 and parts[1] == "__init__.py":
            names.add(parts[0])
        elif len(parts) == 1 and parts[0].endswith(".py") and parts[0] != "__init__.py":
            names.add(parts[0][:-3])
    return tuple(sorted(names))


def _lines(repo: Repo, rel: str) -> int:
    if not rel.endswith(CODE_SUFFIXES) or rel.startswith(NOT_COUNTED):
        return 0
    text = repo.text(rel) or ""
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _summary(repo: Repo, rel: str, name: str, scrub: Scrubber) -> str:
    module = tree(repo, rel)
    doc = ast.get_docstring(module) if module else None
    first = doc.strip().splitlines()[0].strip() if doc and doc.strip() else ""
    text = scrub.clean(first or plain.PACKAGE_WORDS.get(name, ""))
    return clip(text, SUMMARY_MAX)


def packages(repo: Repo, layer_of: Mapping[str, str], scrub: Scrubber) -> tuple[Package, ...]:
    out = []
    for name in package_names(repo):
        layer = layer_for(name, layer_of)
        init = f"{SRC}{name}/__init__.py"
        files = repo.under(f"{SRC}{name}/") if repo.has(init) else (f"{SRC}{name}.py",)
        head = init if repo.has(init) else files[0]
        out.append(
            Package.model_validate(
                {
                    "name": name,
                    "layer": layer,
                    "files": len(files),
                    "lines": sum(_lines(repo, f) for f in files),
                    "summary": _summary(repo, head, name, scrub),
                }
            )
        )
    return tuple(out)


def clip(text: str, limit: int) -> str:
    """`text` on one line, cut at a word boundary to at most `limit` characters ("…" marks it)."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


# ---- integrations ----------------------------------------------------------------------------
def _description(value: ast.expr | None) -> str:
    if not isinstance(value, ast.Call):
        return ""
    for kw in value.keywords:
        if kw.arg == "description" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return ""


def _fields(cls: ast.ClassDef) -> list[ast.AnnAssign]:
    return [n for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]


def _base_class(repo: Repo, module: ast.Module, name: str) -> ast.ClassDef | None:
    """A base class `config.py` imports from a `jarvis` module (R18: `config_calls.CallsConfig`)."""
    for node in module.body:
        if not (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("jarvis.")):
            continue
        if any(a.name == name and a.asname is None for a in node.names):
            other = tree(repo, module_path(repo, str(node.module).removeprefix("jarvis.")))
            cls = _find(other.body, name) if other else None
            return cls if isinstance(cls, ast.ClassDef) else None
    return None


def settings_nodes(repo: Repo) -> list[ast.AnnAssign]:
    """Every `Settings` field in Pydantic's order: its `jarvis` base classes' first (reversed
    MRO: the last base first), then its own."""
    module = tree(repo, module_path(repo, "config"))
    cls = _find(module.body, "Settings") if module else None
    if module is None or not isinstance(cls, ast.ClassDef):
        return []
    out: list[ast.AnnAssign] = []
    for base in reversed(cls.bases):
        found = _base_class(repo, module, base.id) if isinstance(base, ast.Name) else None
        out += _fields(found) if found is not None else []
    return out + _fields(cls)


def settings_fields(repo: Repo) -> tuple[tuple[str, str], ...]:
    """(name, description) of every field of `class Settings` in config.py, in order."""
    return tuple(
        (n.target.id, _description(n.value))
        for n in settings_nodes(repo)
        if isinstance(n.target, ast.Name)
    )


def _default(value: ast.expr | None) -> Any:
    if isinstance(value, ast.Call):  # Field(default, ...) or Field(default=...)
        found = value.args[0] if value.args else None
        found = next((k.value for k in value.keywords if k.arg == "default"), found)
        value = found
    if value is None:
        return None
    try:
        return ast.literal_eval(value)
    except ValueError:
        return None


def settings_defaults(repo: Repo) -> dict[str, Any]:
    """The literal default of every `Settings` field (a non-literal default is left out)."""
    out: dict[str, Any] = {}
    for n in settings_nodes(repo):
        value = _default(n.value)
        if value is not None and isinstance(n.target, ast.Name):
            out[n.target.id] = value
    return out


def probe_keys(repo: Repo) -> frozenset[str]:
    """The `key=` of every `Probe(...)` the health probes build."""
    module = tree(repo, module_path(repo, "health.probes"))
    if module is None:
        return frozenset()
    return frozenset(
        str(kw.value.value)
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Probe"
        for kw in node.keywords
        if kw.arg == "key" and isinstance(kw.value, ast.Constant)
    )


def _matches(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or (p.endswith("_") and name.startswith(p)) for p in prefixes)


def _services(repo: Repo, scrub: Scrubber) -> tuple[Service, ...]:
    fields, probes = settings_fields(repo), probe_keys(repo)
    out = []
    for words in plain.SERVICES:
        names = tuple(sorted(n for n, _ in fields if _matches(n, words.prefixes)))
        checked = bool(words.probe) and words.probe in probes
        if names or checked:
            what = scrub.clean(words.what)
            out.append(
                Service(id=words.id, label=words.label, what=what, settings=names, checked=checked)
            )
        # a service with neither a setting nor a probe is not in this checkout
    return tuple(out)


# ---- R6.3 G3: every service the coverage checker counts ---------------------------------------
OTHER_WHAT = "An outside service the code reaches, found from its settings or its API address."
SLUG_MAX = 40


def slug(name: str) -> str:
    """ "Google Cloud Speech-to-Text" -> "google_cloud_speech_to_text" (an id's tail)."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:SLUG_MAX] or "x"


def service_owners(setting: str, fields: Iterable[Sequence[object]]) -> tuple[str, ...]:
    """The services the checker's `service_fields` maps a setting to (a key ending in "_" is a
    prefix; the first key that matches wins, as the checker reads it)."""
    for key, owners in fields:
        if isinstance(key, str) and (
            setting == key or (key.endswith("_") and setting.startswith(key))
        ):
            return tuple(str(o) for o in owners) if isinstance(owners, (list, tuple)) else ()
    return ()


def _universe(table: Mapping[str, Any]) -> set[str]:
    owners = (o for _, named in table.get("service_fields", ()) for o in named)
    return {str(o) for o in owners} | {str(v) for v in dict(table.get("api_hosts", {})).values()}


def services_named(rows: Iterable[Service], table: Mapping[str, Any]) -> set[str]:
    """The checker's service names the book's rows stand for: what their settings map to, and
    every name a row's label spells or its id is."""
    fields, universe = tuple(table.get("service_fields", ())), _universe(table)
    found: set[str] = set()
    for row in rows:
        found.update(o for name in row.settings for o in service_owners(name, fields))
        found.update(n for n in universe if n.lower() in row.label.lower() or slug(n) == row.id)
    return found & universe


@lru_cache(maxsize=4)
def _inventory(root: Path, sha: str, dirty: bool, files: tuple[str, ...]) -> tuple[str, ...]:
    """The checker's services of one checkout state (it parses every module: `--check`'s
    second build, and the fact pack, reuse it)."""
    return services_mod.inventory(root).names


def inventory_names(repo: Repo) -> tuple[str, ...] | None:
    """The coverage checker's services (M7), or None for a checkout without its table."""
    if not (repo.has(services_mod.TABLE) and repo.has(f"{SRC}config.py")):
        return None
    return _inventory(repo.root, repo.sha, repo.dirty, repo.files)


def _others(repo: Repo, rows: Sequence[Service]) -> tuple[Service, ...]:
    names = inventory_names(repo)
    if not names:
        return ()
    table = services_mod.tables(repo.root)
    fields, covered = tuple(table.get("service_fields", ())), services_named(rows, table)
    settings = [n for n, _ in settings_fields(repo)]
    taken = {r.id for r in rows}
    out = []
    for name in sorted(set(names) - covered):
        sid = slug(name) if slug(name) not in taken else f"{slug(name)}_service"
        own = tuple(sorted(s for s in settings if name in service_owners(s, fields)))
        out.append(Service(id=sid, label=name, what=OTHER_WHAT, settings=own))
    return tuple(out)


def _alerts(repo: Repo, scrub: Scrubber) -> tuple[AlertRow, ...]:
    kinds_tree = tree(repo, module_path(repo, "alerts"))
    kinds = literal_args(kinds_tree, "AlertKind") if kinds_tree else ()
    ports = tree(repo, module_path(repo, "notify.ports"))
    levels = (top_value(ports, "DEFAULT_URGENCY") if ports else None) or {}
    return tuple(
        AlertRow.model_validate(
            {
                "kind": k,
                "level": levels.get(k, "important"),
                "what": scrub.clean(plain.alert_words(k)),
            }
        )
        for k in kinds
    )


def integrations(repo: Repo, scrub: Scrubber) -> Integrations:
    rel = module_path(repo, "keyring")
    ring = tree(repo, rel)
    purposes = top_value(ring, "PURPOSES") if ring else ()
    if not (isinstance(purposes, tuple) and all(isinstance(p, str) for p in purposes)):
        raise GenError(f"{rel}: PURPOSES isn't a literal tuple of names")
    services = _services(repo, scrub)
    return Integrations(
        services=(*services, *_others(repo, services)),
        key_purposes=tuple(purposes),
        alert_kinds=_alerts(repo, scrub),
    )


__all__ = [
    "OTHER_WHAT",
    "clip",
    "defines",
    "integrations",
    "inventory_names",
    "literal_args",
    "module_path",
    "package_names",
    "packages",
    "probe_keys",
    "service_owners",
    "services_named",
    "settings_defaults",
    "settings_nodes",
    "settings_fields",
    "slug",
    "top_expr",
    "top_value",
    "tree",
]
