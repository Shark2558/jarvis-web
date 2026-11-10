# src/jarvis/buildbook/gen/code.py
"""R6 D2: what the generator reads from the code, as text and ASTs (it imports nothing from the
app, so it documents exactly the checkout it is given — the real repo or the test fixture).

- AST look-ups: `module_path`, `tree`, `defines` (the flows' symbol check), `top_value` and
  `literal_args` (literal constants: prices, purposes, alert kinds).
- Architecture: `package_names` / `packages` — every `src/jarvis/*` package and top-level module,
  its tracked files, its lines of code and the first line of its docstring, in its layer.
- Integrations: `settings_fields` (class `Settings` in config.py: names and descriptions),
  `integrations` (services by setting prefix and probe, keyring purposes, alert kinds + levels).
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

from jarvis.buildbook import plain
from jarvis.buildbook.gen.layers import layer_for
from jarvis.buildbook.gen.repo import Repo
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
    text = repo.text(rel) if rel else None
    if text is None:
        return None
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


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


def settings_fields(repo: Repo) -> tuple[tuple[str, str], ...]:
    """(name, description) of every field of `class Settings` in config.py, in order."""
    module = tree(repo, module_path(repo, "config"))
    cls = _find(module.body, "Settings") if module else None
    if not isinstance(cls, ast.ClassDef):
        return ()
    return tuple(
        (n.target.id, _description(n.value))
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
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
    module = tree(repo, module_path(repo, "config"))
    cls = _find(module.body, "Settings") if module else None
    if not isinstance(cls, ast.ClassDef):
        return {}
    out: dict[str, Any] = {}
    for n in cls.body:
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            value = _default(n.value)
            if value is not None:
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
    ring = tree(repo, module_path(repo, "keyring"))
    purposes = (top_value(ring, "PURPOSES") if ring else None) or ()
    return Integrations(
        services=_services(repo, scrub),
        key_purposes=tuple(purposes),
        alert_kinds=_alerts(repo, scrub),
    )


__all__ = [
    "clip",
    "defines",
    "integrations",
    "literal_args",
    "module_path",
    "package_names",
    "packages",
    "probe_keys",
    "settings_defaults",
    "settings_fields",
    "top_expr",
    "top_value",
    "tree",
]
