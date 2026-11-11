# scripts/arch_coverage.py
"""R6.1 D6: the Architecture Guide covers the real system, and every card and row is complete.

    python scripts/arch_coverage.py [--repo DIR] [--guide FILE] [--scan DIR]

Coverage: the guide's `## ... Component catalogue` must name, INSIDE its cards' fields,
  - "Where in the code": every top-level package (the package itself, not a file in it) and
    module under `src/jarvis/`, every `src/jarvis/api/static/console*.js` module and every
    Cloud Scheduler job `deploy/*.sh` creates
  - "Outside services", as one item of the field's list: every service the settings
    (`config.py`, `service_fields`; an unknown secret, key, token or URL setting fails) and the
    code's API hosts (`api_hosts`; an unknown `api.*`, `*.googleapis.com` or `*.internal` host
    fails) name
  - "Data it keeps", as code spans: every Firestore collection the code names
The code side is read by `arch_inventory.py`. Reverse (`arch_files.py`): every path a card
cites and every diagram file the guide links exist.
Completeness: every `####` card has the 11 `FIELDS` filled; the technology table has the 8
`TECH_COLUMNS` and 8 filled cells a row; the version line, the change log and the 14 diagram
links with captions are there. Secret scan: the R6 build book scrubber finds nothing under
`--scan` (default `docs/architecture/`; file, line and kind only, never the text).
Exit 0 = pass, 1 = problems (listed), 2 = no guide, or a file that can't be read or parsed.
Tables: `arch_coverage.json`.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arch_files import NO_DIAGRAMS, check_cited, check_diagram_files, scan  # noqa: E402
from arch_inventory import DIAGRAMS, TABLES_ERROR, Inventory, inventory  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
GUIDE = Path("docs/architecture/JARVIS-Architecture.md")
FIELDS = (
    "Name", "What it does", "Layer", "Skill", "Where in the code", "Depends on",
    "Data it keeps", "Outside services", "Cost (₹ a month)", "When it fails", "Since",
)  # fmt: skip
TECH_COLUMNS = (
    "Area", "Technology", "What it does (plain words)", "Why we chose it",
    "Alternatives we could use", "Why not those (today)", "Cost per month (₹)", "Since",
)  # fmt: skip
_VERSION = re.compile(
    r"^Version v\d+\.\d+\.\d+ · \d{1,2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2} IST · Release R[\d.]+"
    r" · Status: (?:Draft|Current|Superseded) · Owner: \S.*$"
)
CHANGE_LOG_HEAD = "| Version | Date | Release | What changed | By |"
EMPTY = frozenset({"", "-", "—", "–", "tbd", "tbc", "todo", "?", "n/a", "...", "…"})
NONE_OK = frozenset({"Depends on", "Data it keeps", "Outside services"})  # "None" is an answer


@dataclass(frozen=True)
class Card:
    name: str
    fields: dict[str, str]


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


def _filled(value: str | None, field: str = "") -> bool:
    if value is None:
        return False
    v = value.strip().strip("*_ ").lower()
    return v not in EMPTY and (v != "none" or field in NONE_OK)


def check_cards(found: Sequence[Card]) -> list[str]:
    if not found:
        return ["catalogue: no component cards (#### headings) found"]
    out = []
    for c in found:
        missing = [f for f in FIELDS if not _filled(c.fields.get(f), f)]
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


def service_names(field: str) -> set[str]:
    """The items of an "Outside services" field, lower-cased: split at top-level `,`, `;`,
    " and " and " or ", each item's name up to its first bracket ("Anthropic (fast tier)")."""
    items, depth, cur = [], 0, ""
    for ch in field.replace(" and ", ",").replace(" or ", ","):
        depth += (ch == "(") - (ch == ")")
        if ch in ",;" and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    heads = (re.sub(r"^(?:and|or)\s+", "", i.split("(")[0].strip(" `*")) for i in items)
    return {h.lower() for h in heads if h}


def _mentions(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(needle)}(?![\w-]|\.\w)", haystack) is not None


def _spans(text: str) -> set[str]:
    """Collection names in code spans: `{prefix}name/...`, `jarvis_name`, `name/{uid}`."""
    spans = re.findall(r"`([^`]+)`", text)
    return {re.sub(r"^(?:\{prefix\}|jarvis_)", "", s.strip()).split("/")[0] for s in spans}


def _missing(what: str, items: Iterable[str], present: Callable[[str], bool]) -> list[str]:
    return [f"{what} `{i}` is missing" for i in items if not present(i)]


def check_coverage(inv: Inventory, found: Sequence[Card]) -> list[str]:
    code = " ".join(c.fields.get("Where in the code", "") for c in found)
    services = set().union(*(service_names(c.fields.get("Outside services", "")) for c in found))
    data = _spans(" ".join(c.fields.get("Data it keeps", "") for c in found))
    in_code = "from every card's Where in the code"
    return [
        *inv.problems,
        *_missing(f"package/module {in_code}:", inv.code, lambda p: _path_in(code, p)),
        *_missing(f"console module {in_code}:", inv.console, lambda m: _mentions(code, m)),
        *_missing(f"Scheduler job {in_code}:", inv.jobs, lambda j: _mentions(code, j)),
        *_missing("outside service from every card's Outside services (one item of its list):",
                  inv.services, lambda s: s.lower() in services),
        *_missing("Firestore collection from every card's Data it keeps (as a code span):",
                  inv.collections, lambda c: c in data),
    ]  # fmt: skip


def _path_in(code: str, path: str) -> bool:
    """The package or module itself (`src/jarvis/x` or `src/jarvis/x/`), never a file in it."""
    return re.search(rf"(?<![\w/]){re.escape(path)}/?(?![\w/-]|\.\w)", code) is not None


def check_all(repo: Path, guide: Path, scan_dir: Path) -> list[str]:
    text = guide.read_text(encoding="utf-8")
    catalogue = _section(text, "Component catalogue")
    found = cards(catalogue)
    return (
        check_coverage(inventory(repo), found)
        + check_cited(repo, ((c.name, c.fields) for c in found))
        + check_diagram_files(text, guide.parent / "diagrams", DIAGRAMS)
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
    try:
        if TABLES_ERROR:
            raise ValueError(TABLES_ERROR)
        problems = check_all(args.repo, guide, args.scan or guide.parent)
        inv = inventory(args.repo)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as exc:
        sys.stdout.write(f"arch coverage: ERROR - {type(exc).__name__}: {exc}\n")
        return 2
    if problems:
        sys.stdout.write(f"arch coverage: FAILED - {len(problems)} problem(s):\n")
        sys.stdout.write("".join(f"  - {p}\n" for p in problems))
        return 1
    sys.stdout.write(
        f"arch coverage: OK - {len(inv.code)} packages/modules, {len(inv.console)} console "
        f"modules, {len(inv.jobs)} Scheduler jobs, {len(inv.services)} outside services, "
        f"{len(inv.collections)} Firestore collections\n"
    )
    return 0


__all__ = [
    "DIAGRAMS", "GUIDE", "NO_DIAGRAMS", "Card", "Inventory", "cards", "check_all", "inventory",
    "main", "service_names",
]  # fmt: skip

if __name__ == "__main__":
    sys.exit(main())
