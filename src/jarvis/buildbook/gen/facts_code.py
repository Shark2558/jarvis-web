# src/jarvis/buildbook/gen/facts_code.py
"""R6.3 D2 (docs/plans/r6-3-book-content.md, plan review H5): what the fact pack reads from the
code as ASTs and text, standard library only (it imports nothing from the app):

- `parse_src(repo)`: every tracked `src/jarvis/**/*.py`, parsed once ({path: Module}, sorted)
- `constants(trees, scrub)`: every top-level UPPER_CASE name bound to a literal number, or to
  arithmetic or a unary minus on literals (`WINDOW_S = 15 * 60`, `OFFSET = -2`, `A, B = 2, 5`),
  as `<scrubbed path>:<NAME>` -> its value (a bool, a string, a call or a name inside a def is
  not one; neither is a division by zero or a power over `MAX_POWER`)
- `symbols(trees, scrub)`: every top-level function and class as `<scrubbed path>:<name>`
- `settings(repo, scrub)`: every `Settings` field of config.py with its literal default (a
  scalar; strings scrubbed) and its `ge` / `le` bounds
- `collections(repo)`: the Firestore collections the code names, in every idiom the stores use
  (the coverage checker's patterns, `scripts/arch_inventory.py`)
"""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable, Mapping
from typing import Any

from jarvis.buildbook.facts_model import FactValue, Setting
from jarvis.buildbook.gen.code import clip, settings_nodes, tree
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import Scrubber

SRC = "src/jarvis/"
UPPER = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
MAX_POWER = 64  # a larger exponent is not a constant a page quotes
KIND_MAX = 80
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
# the coverage checker's collection idioms (scripts/arch_inventory.py `_COLLECTION`)
COLLECTION = (
    re.compile(r"\{(?:self\.)?_?(?:prefix|p)\}([a-z][a-z0-9_]*)"),
    re.compile(r"_path\(\"([a-z][a-z0-9_]*)\""),
    re.compile(r"\b[A-Z_]*COLLECTION\s*=\s*\"([a-z][a-z0-9_]*)\""),
    re.compile(r"\.collection\(\s*f?\"(?:\{[^}\"]*\})?([a-z][a-z0-9_]*)"),
)
Number = int | float


def parse_src(repo: Repo) -> dict[str, ast.Module]:
    """Every tracked Python module under src/jarvis/ (a GenError if one can't be parsed)."""
    out: dict[str, ast.Module] = {}
    for rel in repo.under(SRC):
        if rel.endswith(".py"):
            module = tree(repo, rel)
            if module is not None:
                out[rel] = module
    return out


def number(node: ast.expr | None) -> Number | None:
    """The value of a literal number, or of arithmetic / a unary sign on them; else None."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value if _finite(value) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = number(node.operand)
        return None if inner is None else (-inner if isinstance(node.op, ast.USub) else inner)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = number(node.left), number(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POWER:
            return None
        try:
            value = _BINARY[type(node.op)](left, right)
        except (ArithmeticError, ValueError):
            return None
        return value if isinstance(value, (int, float)) and _finite(value) else None
    return None


def _finite(value: Number) -> bool:
    return not isinstance(value, float) or math.isfinite(value)


def _bound(node: ast.stmt) -> list[tuple[str, ast.expr | None]]:
    """(name, the expression bound to it) of one top-level statement."""
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [(node.target.id, node.value)]
    if not isinstance(node, ast.Assign):
        return []
    out: list[tuple[str, ast.expr | None]] = []
    for target in node.targets:
        if isinstance(target, ast.Name):
            out.append((target.id, node.value))
        elif isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
            if len(target.elts) == len(node.value.elts):
                pairs = zip(target.elts, node.value.elts, strict=True)
                out.extend((t.id, v) for t, v in pairs if isinstance(t, ast.Name))
    return out


def constants(trees: Mapping[str, ast.Module], scrub: Scrubber) -> dict[str, FactValue]:
    out: dict[str, FactValue] = {}
    for rel in sorted(trees):
        path = scrub.clean(rel)
        for node in trees[rel].body:
            for name, expr in _bound(node):
                value = number(expr) if UPPER.match(name) else None
                if value is not None:
                    key = f"{path}:{name}"
                    out[key] = FactValue(value=value, source=key)
    return out


def symbols(trees: Mapping[str, ast.Module], scrub: Scrubber) -> tuple[str, ...]:
    found = {
        f"{scrub.clean(rel)}:{node.name}"
        for rel, module in trees.items()
        for node in module.body
        if isinstance(node, _DEFS)
    }
    return tuple(sorted(found))


def _call_default(value: ast.Call) -> ast.expr | None:
    found = value.args[0] if value.args else None
    return next((k.value for k in value.keywords if k.arg == "default"), found)


def _scalar(node: ast.expr | None, scrub: Scrubber) -> str | int | float | bool | None:
    if not isinstance(node, (ast.Constant, ast.UnaryOp, ast.BinOp)):
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bool)):
        return scrub.clean(node.value) if isinstance(node.value, str) else node.value
    return number(node)


def _setting(node: ast.AnnAssign, name: str, scrub: Scrubber) -> Setting:
    value = node.value
    bounds: dict[str, Number | None] = {"ge": None, "le": None}
    if isinstance(value, ast.Call):
        for kw in value.keywords:
            if kw.arg in bounds:
                bounds[kw.arg] = number(kw.value)
        value = _call_default(value)
    return Setting.model_validate(
        {
            "name": name,
            "kind": clip(ast.unparse(node.annotation), KIND_MAX),
            "default": _scalar(value, scrub),
            **bounds,
        }
    )


def settings(repo: Repo, scrub: Scrubber) -> tuple[Setting, ...]:
    """Every `Settings` field, its `jarvis` base classes' too (R18: `config_calls.CallsConfig`)."""
    found = {
        n.target.id: _setting(n, n.target.id, scrub)
        for n in settings_nodes(repo)
        if isinstance(n.target, ast.Name)
    }
    return tuple(found[k] for k in sorted(found))


def collections(repo: Repo) -> tuple[str, ...]:
    names: set[str] = set()
    for rel in repo.under(SRC):
        if rel.endswith(".py"):
            text = repo.text(rel) or ""
            for pattern in COLLECTION:
                names.update(pattern.findall(text))
    return tuple(sorted(names))


__all__ = [
    "COLLECTION",
    "MAX_POWER",
    "collections",
    "constants",
    "number",
    "parse_src",
    "settings",
    "symbols",
]
