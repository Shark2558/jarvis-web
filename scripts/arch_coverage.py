# scripts/arch_coverage.py
"""R6.1 D6: the Architecture Guide covers the real system, and every card and row is complete.

    python scripts/arch_coverage.py [--repo DIR] [--guide FILE] [--scan DIR]

Coverage: the guide's "Component catalogue" (its `## ... Component catalogue` section) must name
  - every top-level package and module under `src/jarvis/` in a card's "Where in the code" field
  - every `src/jarvis/api/static/console*.js` module in a card's "Where in the code" field
  - every Cloud Scheduler job `deploy/*.sh` creates (`gcloud scheduler jobs create ...`)
  - every outside service: from the settings (`src/jarvis/config.py`, `service_fields`; a secret
    or URL setting with no known service fails) and from the API hosts in code (`api_hosts`;
    an unknown `api.*` or `*.googleapis.com` host fails), in a card's "Outside services" field
  - every Firestore collection the code names (`{prefix}name`, `_path("name"`,
    `*_COLLECTION = "name"`) as a code span in a card's "Data it keeps" field
Completeness: every card (a `####` heading in the catalogue) has the 11 `FIELDS`, none empty;
the technology table has exactly the 8 `TECH_COLUMNS` and every row 8 non-empty cells; the
version line and the change log are there; each of the 14 diagrams is linked with its caption.
Secret scan: the R6 build book scrubber (`jarvis.buildbook.gen.scrub`) finds no personal data or
secret-shaped string in any text file under `--scan` (default `docs/architecture/`); it reports
file, line and kind, never the text. Exit 0 = pass, 1 = problems (listed), 2 = no guide.
The tables (settings and hosts -> services, the diagram names) are in `arch_coverage.json`.
Standard library only, plus the scrubber from this checkout's `src/`.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
GUIDE = Path("docs/architecture/JARVIS-Architecture.md")
TABLES = json.loads((Path(__file__).with_suffix(".json")).read_text(encoding="utf-8"))
FIELDS = (
    "Name", "What it does", "Layer", "Skill", "Where in the code", "Depends on",
    "Data it keeps", "Outside services", "Cost (₹ a month)", "When it fails", "Since",
)  # fmt: skip
TECH_COLUMNS = (
    "Area", "Technology", "What it does (plain words)", "Why we chose it",
    "Alternatives we could use", "Why not those (today)", "Cost per month (₹)", "Since",
)  # fmt: skip
DIAGRAMS: tuple[str, ...] = tuple(TABLES["diagrams"])
# Settings -> outside services. A key ending in "_" is a prefix; any other key is a field name.
SERVICE_FIELDS = tuple((k, tuple(v)) for k, v in TABLES["service_fields"])
INTERNAL_SECRETS = frozenset(TABLES["internal_secrets"])
API_HOSTS: dict[str, str] = TABLES["api_hosts"]
NOT_SERVICES = frozenset(TABLES["not_services"])
_API_HOST = re.compile(r"^(?:api\.[a-z0-9.-]+|[a-z0-9-]+\.googleapis\.com|[a-z0-9.-]+\.internal)$")
_HOST_IN = re.compile(r"\bhttps?://([A-Za-z0-9.-]+)")
_COLLECTION = (
    re.compile(r"\{(?:self\.)?_?(?:prefix|p)\}([a-z][a-z0-9_]*)"),
    re.compile(r"_path\(\"([a-z][a-z0-9_]*)\""),
    re.compile(r"\b[A-Z_]*COLLECTION\s*=\s*\"([a-z][a-z0-9_]*)\""),
)
_JOB = re.compile(r"scheduler\s+jobs\s+create\s+\w+\s+(\"[^\"]+\"|\S+)")
_VERSION = re.compile(
    r"^Version v\d+\.\d+\.\d+ · \d{1,2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2} IST · Release R[\d.]+"
    r" · Status: (?:Draft|Current|Superseded) · Owner: \S.*$"
)
CHANGE_LOG_HEAD = "| Version | Date | Release | What changed | By |"
EMPTY = frozenset({"", "-", "—", "–", "tbd", "?", "n/a"})
SCAN_SUFFIXES = (".md", ".markdy", ".svg", ".txt", ".json")


@dataclass(frozen=True)
class Inventory:
    code: tuple[str, ...]
    console: tuple[str, ...]
    jobs: tuple[str, ...]
    services: tuple[str, ...]
    collections: tuple[str, ...]
    problems: tuple[str, ...]  # settings or hosts the tables above don't know


@dataclass(frozen=True)
class Card:
    name: str
    fields: dict[str, str]


def _code_items(repo: Path) -> tuple[str, ...]:
    root = repo / "src/jarvis"
    dirs = [f"src/jarvis/{p.name}" for p in root.iterdir() if (p / "__init__.py").is_file()]
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
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings"), None)
    if cls is None:
        return []
    return [
        (n.target.id, ast.unparse(n.annotation))
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    ]


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
        elif name not in INTERNAL_SECRETS and ("SecretStr" in annotation or name.endswith("_url")):
            problems.append(
                f"setting `{name}` names no known outside service: add it to SERVICE_FIELDS"
            )
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
    problems = [
        f"API host `{h}` in the code names no known service: add it to API_HOSTS"
        for h in sorted(unknown)
    ]
    return services, problems


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


def _section(text: str, title: str, level: str = "##") -> str:
    """The body of the first `level` heading whose title contains `title` (to the next heading
    of the same or a higher level)."""
    lines = text.splitlines()
    depth = len(level)
    for i, line in enumerate(lines):
        m = re.match(r"^(#+)\s+(.*)$", line)
        if m and len(m.group(1)) == depth and title.lower() in m.group(2).lower():
            body = []
            for nxt in lines[i + 1 :]:
                h = re.match(r"^(#+)\s", nxt)
                if h and len(h.group(1)) <= depth:
                    break
                body.append(nxt)
            return "\n".join(body)
    return ""


def _cells(line: str) -> list[str]:
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def _is_rule(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", line.strip()))


def cards(catalogue: str) -> list[Card]:
    found: list[Card] = []
    name, fields = "", dict[str, str]()
    for line in catalogue.splitlines():
        heading = re.match(r"^####\s+(.*)$", line)
        if heading:
            if name:
                found.append(Card(name, fields))
            name, fields = heading.group(1).strip(), {}
        elif name and line.strip().startswith("|") and not _is_rule(line):
            row = _cells(line)
            if len(row) >= 2 and row[0] != "Field":
                fields[row[0].strip("* ")] = " | ".join(row[1:])
    if name:
        found.append(Card(name, fields))
    return found


def _filled(value: str | None) -> bool:
    return value is not None and value.strip().strip("*_ ").lower() not in EMPTY


def check_cards(found: Sequence[Card]) -> list[str]:
    if not found:
        return ["catalogue: no component cards (#### headings) found"]
    out = []
    for c in found:
        missing = [f for f in FIELDS if not _filled(c.fields.get(f))]
        if missing:
            out.append(f"card `{c.name}`: missing or empty field(s): {', '.join(missing)}")
    return out


def check_tech(text: str) -> list[str]:
    rows = [
        ln for ln in _section(text, "Technology table", "###").splitlines() if ln.startswith("|")
    ]
    if not rows:
        return ["technology table: not found (a `### ... Technology table` section)"]
    head, body = _cells(rows[0]), [r for r in rows[1:] if not _is_rule(r)]
    out = []
    if tuple(head) != TECH_COLUMNS:
        out.append(f"technology table: columns must be exactly: {' | '.join(TECH_COLUMNS)}")
    for row in body:
        cells = _cells(row)
        label = cells[1] if len(cells) > 1 else row[:40]
        if len(cells) != len(TECH_COLUMNS) or not all(_filled(c) for c in cells):
            out.append(f"technology row `{label}`: needs 8 non-empty cells (has {len(cells)})")
    return out


def check_paperwork(text: str) -> list[str]:
    out = []
    first = text.splitlines()[0] if text.strip() else ""
    if not _VERSION.match(first):
        out.append(
            "version line: the first line must read `Version vX.Y.Z · 11 Nov 2026, 12:00 "
            "IST · Release R6.1 · Status: Current · Owner: ...`"
        )
    log = _section(text, "Change log")
    if CHANGE_LOG_HEAD not in log or not any(ln.startswith("| v") for ln in log.splitlines()):
        out.append(f"change log: a `## Change log` section with `{CHANGE_LOG_HEAD}` and a row")
    for name in DIAGRAMS:
        link = text.find(f"diagrams/{name}.svg")
        caption = f"*Figure {int(name[:2])}."
        if link < 0 or caption not in text[link : link + 600]:
            out.append(f"diagram `{name}`: link `diagrams/{name}.svg` and caption `{caption}`")
    return out


def _mentions(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(needle)}(?![\w-]|\.\w)", haystack) is not None


def _spans(text: str) -> set[str]:
    """Collection names in code spans: `{prefix}name/...`, `jarvis_name`, `name/{uid}`."""
    spans = re.findall(r"`([^`]+)`", text)
    return {re.sub(r"^(?:\{prefix\}|jarvis_)", "", s.strip()).split("/")[0] for s in spans}


def _missing(what: str, items: Iterable[str], present: Callable[[str], bool]) -> list[str]:
    return [f"{what} `{i}` is missing" for i in items if not present(i)]


def check_coverage(inv: Inventory, found: Sequence[Card], catalogue: str) -> list[str]:
    code = " ".join(c.fields.get("Where in the code", "") for c in found)
    services = " ".join(c.fields.get("Outside services", "") for c in found).lower()
    data = _spans(" ".join(c.fields.get("Data it keeps", "") for c in found))
    in_code = "from every card's Where in the code"
    return [
        *inv.problems,
        *_missing(f"package/module {in_code}:", inv.code, lambda p: _path_in(code, p)),
        *_missing(f"console module {in_code}:", inv.console, lambda m: _mentions(code, m)),
        *_missing("Scheduler job from the catalogue:", inv.jobs, lambda j: _mentions(catalogue, j)),
        *_missing("outside service from every card's Outside services:", inv.services,
                  lambda s: s.lower() in services),
        *_missing("Firestore collection from every card's Data it keeps (as a code span):",
                  inv.collections, lambda c: c in data),
    ]  # fmt: skip


def _path_in(code: str, path: str) -> bool:
    return re.search(rf"(?<![\w/]){re.escape(path)}(?![\w])", code) is not None


def scan(folder: Path) -> list[str]:
    if str(HERE / "src") not in sys.path:
        sys.path.insert(0, str(HERE / "src"))
    from jarvis.buildbook.gen.scrub import default_scrubber

    scrubber, out = default_scrubber(), []
    for path in sorted(p for p in folder.rglob("*") if p.suffix in SCAN_SUFFIXES and p.is_file()):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            kinds = scrubber.findings(line)
            if kinds:
                out.append(f"secret scan: {path.name}:{n} ({', '.join(kinds)})")
    return out


def check_all(repo: Path, guide: Path, scan_dir: Path) -> list[str]:
    text = guide.read_text(encoding="utf-8")
    catalogue = _section(text, "Component catalogue")
    found = cards(catalogue)
    return (
        check_coverage(inventory(repo), found, catalogue)
        + check_cards(found)
        + check_tech(text)
        + check_paperwork(text)
        + (scan(scan_dir) if scan_dir.is_dir() else [f"secret scan: {scan_dir} not found"])
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", type=Path, default=HERE)
    ap.add_argument("--guide", type=Path, default=None)
    ap.add_argument("--scan", type=Path, default=None)
    args = ap.parse_args(argv)
    guide = args.guide or args.repo / GUIDE
    if not guide.is_file():
        sys.stdout.write(f"arch coverage: FAILED - no guide at {guide}\n")
        return 2
    problems = check_all(args.repo, guide, args.scan or guide.parent)
    if problems:
        sys.stdout.write(f"arch coverage: FAILED - {len(problems)} problem(s):\n")
        sys.stdout.write("".join(f"  - {p}\n" for p in problems))
        return 1
    inv = inventory(args.repo)
    sys.stdout.write(
        f"arch coverage: OK - {len(inv.code)} packages/modules, {len(inv.console)} console "
        f"modules, {len(inv.jobs)} Scheduler jobs, {len(inv.services)} outside services, "
        f"{len(inv.collections)} Firestore collections\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
