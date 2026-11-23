# src/jarvis/buildbook/gen/facts_routes.py
"""R6.3 D2 (docs/plans/r6-3-book-content.md, plan review M9): every HTTP route the code declares,
read by AST, never by importing the app.

Every `APIRouter(...)` and `FastAPI(...)` bound to a name, at module level or inside a function
(`health/api.py` builds its router in one), with its `prefix=` resolved: a literal, a constant of
the module, one imported from another module, an f-string or a sum of those. On each of them,
whatever its name (`router`, `public`, `console`, `hook_router`, `app`, ...): every route
decorator (`.get`, `.post`, `.put`, `.patch`, `.delete`, `.head`, `.options`, `.api_route` with
its `methods=`, `.websocket`), every `.add_api_route` (GET unless `methods=` says) and
`.add_api_websocket_route`, the prefix joined to the path. A route added in a loop over
`writer/http.ROUTES` (I0's stub routers) reads that table: its rows under the router's prefix.
A path the scan can't read is a GenError (a route the book would otherwise quietly drop).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping

from jarvis.buildbook.facts_model import Route
from jarvis.buildbook.gen.facts_code import SRC
from jarvis.buildbook.gen.repo import GenError
from jarvis.buildbook.gen.scrub import Scrubber

ROUTER_TYPES = frozenset({"APIRouter", "FastAPI"})
VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
TABLE = ("jarvis.buildbook.writer.http", "ROUTES")  # the full book's routes table (I0, seam 6)
MAX_DEPTH = 12  # names resolved through other names
Env = Mapping[str, str]
_COMPOUND = ("body", "orelse", "finalbody", "handlers")


class Consts:
    """String constants of the parsed modules, followed through names and imports."""

    def __init__(self, trees: Mapping[str, ast.Module]) -> None:
        self.trees = trees
        self._bound: dict[str, dict[str, ast.expr]] = {}
        self._imports: dict[str, dict[str, tuple[str, str]]] = {}

    def text(
        self, rel: str, node: ast.expr | None, depth: int = 0, env: Env | None = None
    ) -> str | None:
        """The string `node` always is (`env`: a loop's names bound to strings), else None."""
        if node is None or depth > MAX_DEPTH:
            return None
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, str) else None
        if isinstance(node, ast.Name):
            if env and node.id in env:
                return env[node.id]
            return self.lookup(rel, node.id, depth + 1)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.text(rel, node.left, depth + 1, env)
            right = self.text(rel, node.right, depth + 1, env)
            return None if left is None or right is None else left + right
        if isinstance(node, ast.JoinedStr):
            parts = [self._part(rel, v, depth + 1, env) for v in node.values]
            return None if any(p is None for p in parts) else "".join(p or "" for p in parts)
        if isinstance(node, ast.Subscript):
            return self._item(rel, node, depth + 1, env)
        return None

    def _item(self, rel: str, node: ast.Subscript, depth: int, env: Env | None) -> str | None:
        """`TABLE[KEY]` of a constant dict (or `MappingProxyType({...})`) and a constant key."""
        found = self.expr_of(rel, node.value.id) if isinstance(node.value, ast.Name) else None
        key = self.text(rel, node.slice, depth, env)
        if found is None or key is None:
            return None
        where, value = found
        if isinstance(value, ast.Call) and value.args:
            value = value.args[0]
        if not isinstance(value, ast.Dict):
            return None
        for k, v in zip(value.keys, value.values, strict=True):
            if k is not None and self.text(where, k, depth) == key:
                return self.text(where, v, depth)
        return None

    def _part(self, rel: str, node: ast.expr, depth: int, env: Env | None) -> str | None:
        if isinstance(node, ast.FormattedValue):
            plain = node.conversion == -1 and node.format_spec is None
            return self.text(rel, node.value, depth, env) if plain else None
        return self.text(rel, node, depth, env)

    def lookup(self, rel: str, name: str, depth: int = 0) -> str | None:
        found = self.expr_of(rel, name, depth)
        return self.text(found[0], found[1], depth + 1) if found else None

    def expr_of(self, rel: str, name: str, depth: int = 0) -> tuple[str, ast.expr] | None:
        """(the module that binds `name`, the expression), following imports."""
        if depth > MAX_DEPTH:
            return None
        expr = self.bound(rel).get(name)
        if expr is not None:
            return rel, expr
        source = self._imported(rel).get(name)
        return self.expr_of(source[0], source[1], depth + 1) if source else None

    def bound(self, rel: str) -> dict[str, ast.expr]:
        if rel not in self._bound:
            found: dict[str, ast.expr] = {}
            for node in self.trees[rel].body if rel in self.trees else []:
                for name, expr in _names(node):
                    found[name] = expr
            self._bound[rel] = found
        return self._bound[rel]

    def _imported(self, rel: str) -> dict[str, tuple[str, str]]:
        if rel not in self._imports:
            found: dict[str, tuple[str, str]] = {}
            for node in self.trees[rel].body if rel in self.trees else []:
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    target = self.module_rel(node.module)
                    for a in node.names if target else []:
                        found[a.asname or a.name] = (target or "", a.name)
            self._imports[rel] = found
        return self._imports[rel]

    def module_rel(self, dotted: str) -> str | None:
        base = "src/" + dotted.replace(".", "/")
        return next((r for r in (f"{base}.py", f"{base}/__init__.py") if r in self.trees), None)


def _names(node: ast.stmt) -> list[tuple[str, ast.expr]]:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
        return [(node.target.id, node.value)]
    if not isinstance(node, ast.Assign):
        return []
    out: list[tuple[str, ast.expr]] = []
    for t in node.targets:
        if isinstance(t, ast.Name):
            out.append((t.id, node.value))
        elif isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple):
            if len(t.elts) == len(node.value.elts):
                pairs = zip(t.elts, node.value.elts, strict=True)
                out.extend((n.id, v) for n, v in pairs if isinstance(n, ast.Name))
    return out


def _flat(body: list[ast.stmt], loop: ast.For | None) -> Iterator[tuple[ast.stmt, ast.For | None]]:
    """Each statement of a scope (into if / for / with / try, never into a def or class), with
    its nearest `for` loop."""
    for node in body:
        yield node, loop
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        inner = node if isinstance(node, ast.For) else loop
        for field in _COMPOUND:
            for child in getattr(node, field, None) or []:
                if isinstance(child, ast.ExceptHandler):
                    yield from _flat(child.body, inner)
                elif isinstance(child, ast.stmt):
                    yield from _flat([child], inner)


def _router_call(value: ast.expr | None) -> ast.Call | None:
    if not isinstance(value, ast.Call):
        return None
    f = value.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
    return value if name in ROUTER_TYPES else None


class _Scan:
    def __init__(self, rel: str, consts: Consts) -> None:
        self.rel, self.consts = rel, consts
        self.found: set[tuple[str, str]] = set()

    def fail(self, node: ast.AST, what: str) -> GenError:
        return GenError(f"{self.rel}:{getattr(node, 'lineno', 0)}: {what} the fact pack can't read")

    def scope(self, body: list[ast.stmt], outer: Mapping[str, str]) -> None:
        routers = dict(outer)
        for node, _ in _flat(body, None):
            for name, expr in _names(node):
                call = _router_call(expr)
                if call is not None:
                    routers[name] = self._prefix(call)
        for node, loop in _flat(body, None):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    self._decorated(dec, routers)
                self.scope(node.body, routers)
            elif isinstance(node, ast.ClassDef):
                self.scope(node.body, routers)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                self._added(node.value, routers, loop)

    def _prefix(self, call: ast.Call) -> str:
        expr = next((k.value for k in call.keywords if k.arg == "prefix"), None)
        if expr is None:
            return ""
        got = self.consts.text(self.rel, expr)
        if got is None:
            raise self.fail(call, "a router prefix")
        return got

    def _target(self, call: ast.Call, routers: Mapping[str, str]) -> tuple[str, str] | None:
        f = call.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in routers:
            return f.value.id, f.attr
        return None

    def _path(self, call: ast.Call, env: Env | None = None) -> str | None:
        expr = call.args[0] if call.args else None
        expr = next((k.value for k in call.keywords if k.arg == "path"), expr)
        return self.consts.text(self.rel, expr, env=env)

    def _methods(
        self, call: ast.Call, default: tuple[str, ...], env: Env | None = None
    ) -> tuple[str, ...]:
        expr = next((k.value for k in call.keywords if k.arg == "methods"), None)
        if expr is None:
            return default
        items = expr.elts if isinstance(expr, (ast.List, ast.Tuple, ast.Set)) else []
        got = tuple(self.consts.text(self.rel, i, env=env) for i in items)
        if not got or any(m is None for m in got):
            raise self.fail(call, "a route's methods")
        return tuple(str(m).upper() for m in got)

    def _decorated(self, dec: ast.expr, routers: Mapping[str, str]) -> None:
        hit = self._target(dec, routers) if isinstance(dec, ast.Call) else None
        if hit is None or not isinstance(dec, ast.Call):
            return
        name, attr = hit
        if attr in VERBS or attr in ("api_route", "websocket"):
            path = self._path(dec)
            if path is None:
                raise self.fail(dec, "a route path")
            verbs = {"api_route": self._methods(dec, ("GET",)), "websocket": ("WEBSOCKET",)}
            for method in verbs.get(attr, (attr.upper(),)):
                self.found.add((method, routers[name] + path))

    def _added(self, call: ast.Call, routers: Mapping[str, str], loop: ast.For | None) -> None:
        hit = self._target(call, routers)
        if hit is None or hit[1] not in ("add_api_route", "add_api_websocket_route"):
            return
        name, attr = hit
        if self._path(call) is None and loop is not None and isinstance(loop.iter, ast.Name):
            rows = table_rows(self.consts, self.rel, loop.iter.id)
            if rows is not None:
                self._from_table(call, routers[name], rows)
                return
        envs = loop_envs(self.consts, self.rel, loop) if self._path(call) is None else [{}]
        for env in envs or [{}]:
            path = self._path(call, env)
            if path is None:
                raise self.fail(call, "a route path")
            ws = attr == "add_api_websocket_route"
            for method in ("WEBSOCKET",) if ws else self._methods(call, ("GET",), env):
                self.found.add((method, routers[name] + path))

    def _from_table(self, call: ast.Call, prefix: str, rows: tuple[tuple[str, str], ...]) -> None:
        if not prefix:
            raise self.fail(call, "a route added in a loop")
        self.found.update((m, p) for m, p in rows if p == prefix or p.startswith(prefix + "/"))


_SPREAD = {"items": 2, "keys": 0, "values": 1}


def loop_envs(consts: Consts, rel: str, loop: ast.For | None) -> list[dict[str, str]]:
    """Each iteration's names bound to strings, for a loop over a constant tuple, list or dict
    (`for k in D`, `for k, v in D.items()`, `.keys()`, `.values()`); [] for any other loop."""
    if loop is None:
        return []
    it, spread = loop.iter, 0
    if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and not it.args:
        spread, it = _SPREAD.get(it.func.attr, -1), it.func.value
    found = consts.expr_of(rel, it.id) if isinstance(it, ast.Name) and spread >= 0 else None
    if found is None:
        return []
    where, value = found
    if isinstance(value, ast.Dict):
        pairs = [(k, v) for k, v in zip(value.keys, value.values, strict=True) if k is not None]
        items: list[ast.expr] = [
            ast.Tuple(elts=[k, v]) if spread == 2 else (v if spread == 1 else k) for k, v in pairs
        ]
    elif isinstance(value, (ast.Tuple, ast.List, ast.Set)) and spread == 0:
        items = list(value.elts)
    else:
        return []
    return [_bind(consts, where, loop.target, item) for item in items]


def _bind(consts: Consts, rel: str, target: ast.expr, item: ast.expr) -> dict[str, str]:
    if isinstance(target, ast.Name):
        got = consts.text(rel, item)
        return {target.id: got} if got is not None else {}
    if isinstance(target, ast.Tuple) and isinstance(item, ast.Tuple):
        out: dict[str, str] = {}
        for t, v in zip(target.elts, item.elts, strict=False):
            out.update(_bind(consts, rel, t, v))
        return out
    return {}


def table_rows(consts: Consts, rel: str, name: str) -> tuple[tuple[str, str], ...] | None:
    """(method, path) of each row of the writer's routes table, when `name` in `rel` is it."""
    module, table = TABLE
    source = consts.module_rel(module)
    imported = consts._imported(rel).get(name)  # noqa: SLF001 - this module's own helper
    if source is None or (imported != (source, table) and not (rel == source and name == table)):
        return None
    value = consts.bound(source).get(table)
    rows: list[tuple[str, str]] = []
    for row in value.elts if isinstance(value, ast.Tuple) else []:
        cells = row.elts[:2] if isinstance(row, ast.Tuple) else []
        got = [consts.text(source, c) for c in cells]
        if len(got) != 2 or None in got:
            return None
        rows.append((str(got[0]), str(got[1])))
    return tuple(rows)


def routes(trees: Mapping[str, ast.Module], scrub: Scrubber) -> tuple[Route, ...]:
    consts = Consts(trees)
    found: set[tuple[str, str, str]] = set()
    for rel in sorted(trees):
        if not rel.startswith(SRC):
            continue
        scan = _Scan(rel, consts)
        scan.scope(trees[rel].body, {})
        module = scrub.clean(rel)
        found.update((path, method, module) for method, path in scan.found)
    return tuple(Route(method=m, path=p, module=mod) for p, m, mod in sorted(found))


__all__ = ["ROUTER_TYPES", "TABLE", "VERBS", "Consts", "routes", "table_rows"]
