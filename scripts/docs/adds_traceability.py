#!/usr/bin/env python3
# scripts/docs/adds_traceability.py
"""The Architecture Design Document's traceability matrix.

It writes docs/architecture/design/10-traceability.md:

    python scripts/docs/adds_traceability.py WORKBOOK.xlsx [--repo DIR] [--out FILE]
        [--version-line LINE] [--workbook-name NAME]

Reads the requirements workbook's "Requirements" sheet (columns found by their header names:
"Serial No.", "Module", "Feature", "Status", "Release") and writes one Markdown row per
requirement: serial, a short feature title, its layer and skill (from the module, through
`MODULES` below), its release and status, and, for a Done row, where its code is.

Where the code is, never guessed: for a Done row the code files of its module's packages are
searched for the row's own words — a use-case id such as INV-01 or HF-02 when the title has one,
otherwise two distinctive words of the title in the same file (one, when the title has only one);
the file with most of them wins, a word in its path counting extra. A hit names that file (a lead
to start reading, not a proof); no hit says "location not confirmed". Rows not Done say "—".

Only the title (cut to 80 characters) leaves the workbook: never its remarks, which can hold
personal details. Re-run at every release (workshop rules 3.8). Exit 0 written, 2 bad input.
Needs openpyxl (the dev environment has it).
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

LAYERS: Mapping[str, str] = {
    "L1": "L1 Interaction",
    "L2": "L2 Input & perception",
    "L3": "L3 Context & orchestration",
    "L4": "L4 Reasoning",
    "L5": "L5 Skills",
    "L6": "L6 Integration & tools",
    "L7": "L7 Data",
    "L8": "L8 Output",
    "X": "Cross-cutting",
}

SKILLS: Mapping[str, str] = {
    "task": "Task & Productivity",
    "research": "Research & Intel",
    "code": "Code & DevOps",
    "decision": "Decision Support",
    "communication": "Communication",
    "finance": "Finance & Analytics",
    "learning": "Learning",
    "creative": "Creative",
    "security": "Security Advisor",
    "automation": "Automation Engine",
    "health": "Health & Wellbeing",
    "-": "—",
}


@dataclass(frozen=True)
class Home:
    """Where a workbook module lives in the architecture."""

    layer: str
    skill: str
    paths: tuple[str, ...]  # repository paths (packages, modules or folders) holding its code


_W = ("src/jarvis/wardrobe",)
_V = ("src/jarvis/vision", "src/jarvis/camera")

# Workbook module -> layer, skill, code. A module not listed here maps to "—" (and the chapter
# lists it under "Modules with no architectural home"), so a new module shows up at once.
MODULES: Mapping[str, Home] = {
    "Platform": Home("L4", "-", ("src/jarvis/llm", "src/jarvis/core", "src/jarvis/api")),
    "Brain": Home("L4", "-", ("src/jarvis/llm", "src/jarvis/core")),
    "Voice": Home("L2", "communication", ("src/jarvis/voice", "src/jarvis/api/static")),
    "Task & Productivity": Home(
        "L5",
        "task",
        ("src/jarvis/tools", "src/jarvis/helpers", "src/jarvis/series", "src/jarvis/groceries",
         "src/jarvis/packages", "src/jarvis/family", "src/jarvis/undo", "src/jarvis/telegram"),
    ),
    "Calendar": Home("L5", "task", ("src/jarvis/tools",)),
    "Communication": Home(
        "L5",
        "communication",
        ("src/jarvis/tools", "src/jarvis/telegram", "src/jarvis/whatsapp", "src/jarvis/notify",
         "src/jarvis/webpush"),
    ),
    "Research & Intel": Home(
        "L5",
        "research",
        ("src/jarvis/tools", "src/jarvis/kb", "src/jarvis/people", "src/jarvis/picture",
         "src/jarvis/places", "src/jarvis/drive", "src/jarvis/documents"),
    ),
    "People research": Home("L5", "research", ("src/jarvis/people",)),
    "Picture research": Home("L5", "research", ("src/jarvis/picture",)),
    "Documents": Home("L2", "research", ("src/jarvis/documents", "src/jarvis/api")),
    "Creative": Home("L5", "creative", ("src/jarvis/media", "src/jarvis/tools")),
    "Finance & Analytics": Home("L5", "finance", ("src/jarvis/billing", "src/jarvis/quota")),
    "Bills": Home("L5", "finance", ("src/jarvis/helpers",)),
    "Costs": Home("X", "finance", ("src/jarvis/billing", "src/jarvis/llm")),
    "Memory & profile": Home("L3", "research", ("src/jarvis/memory", "src/jarvis/recall")),
    "Mobile & wearables": Home(
        "L1", "-", ("src/jarvis/mobile", "src/jarvis/phone", "src/jarvis/watch", "android")
    ),
    "Phone camera": Home("L2", "-", ("src/jarvis/camera", "src/jarvis/vision", "android")),
    "Console": Home("L1", "-", ("src/jarvis/web", "src/jarvis/api/static")),
    "Code & DevOps": Home(
        "X", "code", ("src/jarvis/hardening", "src/jarvis/backup", "deploy", ".github")
    ),
    "Safety & permissions": Home(
        "X", "security", ("src/jarvis/tools", "src/jarvis/permissions", "src/jarvis/privacy")
    ),
    "Security Advisor": Home(
        "L5", "security", ("src/jarvis/tools", "src/jarvis/privacy", "src/jarvis/hardening")
    ),
    "Security & privacy": Home("X", "security", ("src/jarvis/llm", "deploy")),
    "Safety": Home("X", "security", ("evals",)),
    "Quality": Home("X", "code", ("tests", "scripts")),
    "Decision Support": Home("L5", "decision", ()),
    "Automation Engine": Home(
        "L5", "automation", ("src/jarvis/ticks.py", "src/jarvis/series", "src/jarvis/helpers")
    ),
    "Helpers": Home("L5", "automation", ("src/jarvis/helpers",)),
    "Brief": Home("L8", "automation", ("src/jarvis/brief", "src/jarvis/helpers")),
    "Learning": Home("L5", "learning", ()),
    "Vitals": Home("X", "code", ("src/jarvis/vitals", "src/jarvis/quota")),
    "Systems check": Home("X", "code", ("src/jarvis/vitals", "src/jarvis/selfwatch")),
    "Self-health": Home("X", "code", ("src/jarvis/selfwatch", "src/jarvis/vitals")),
    "Connectors": Home("L6", "code", ("src/jarvis/integrations",)),
    "Photos": Home("L6", "research", ("src/jarvis/photos", "src/jarvis/contacts")),
    "Faces": Home(
        "L2", "security", ("src/jarvis/faces", "src/jarvis/facegroups", "src/jarvis/homebridge")
    ),
    "No-AI mode": Home("L3", "-", ("src/jarvis/understand", "src/jarvis/offline")),
    "Home": Home("L6", "security", ("src/jarvis/home", "src/jarvis/homebridge")),
    "Build book": Home("X", "code", ("src/jarvis/buildbook",)),
    "Architecture guide": Home("X", "code", ("docs/architecture", "scripts", ".claude")),
    "Versioning": Home("X", "code", ("src/jarvis/about.py", "scripts", ".github")),
    "Vision engine": Home("L2", "health", _V),
    "Vision & fitness": Home("L5", "health", _V),
    "Fitness coach": Home("L5", "health", _V),
    "Activity": Home("L5", "health", _V),
    "Activity (AI)": Home("L5", "automation", ()),
    "Privacy": Home("X", "security", ("src/jarvis/privacy", "src/jarvis/camera")),
    "Cameras": Home("L6", "security", ("src/jarvis/homebridge", "src/jarvis/camera")),
    "Kitchen": Home("L5", "health", ("src/jarvis/helpers", "src/jarvis/groceries")),
    "Kitchen & nutrition": Home("L5", "health", _V),
    "Care & health assist": Home("L5", "health", ("src/jarvis/health", "src/jarvis/vision")),
    "Kitchen / wardrobe (AI)": Home("L5", "creative", ()),
    "Wardrobe": Home("L5", "task", _W),
    "Laundry": Home("L5", "task", _W),
    "Outfits": Home("L5", "task", _W),
    "Try-on": Home("L5", "task", _W),
    "Wardrobe controls": Home("L5", "task", _W),
    "Wardrobe extras": Home("L5", "task", _W),
    "Laundry calls": Home("L5", "communication", ()),
    "Social (paid)": Home("L6", "research", ()),
    "Maps": Home("L6", "research", ("src/jarvis/tools",)),
    "Gesture control": Home("L2", "-", ()),
    "Not in any release": Home("X", "-", ()),
}

CODE_SUFFIXES = (".py", ".js", ".kt", ".ps1", ".sh", ".yml", ".yaml")  # code, not docs
CASE_ID = re.compile(r"\b([A-Z]{2,4}-\d{2,3})\b")
# A Kotlin package path names the repository owner's account; the matrix shows only "…".
JVM_PACKAGE = re.compile(r"/(kotlin|java)/io/github/[^/]+/")
WORD = re.compile(r"[a-z][a-z'-]{4,}")
STOP = frozenset(
    "about after again along always another before being between could every first follow "
    "from have their there these thing things those through under until where which while "
    "would your yours jarvis using should other since each into onto when with without "
    "what that this them they then than more most only also does done make makes made "
    "phone laptop camera based check checks people person place places".split()
)
NOT_CONFIRMED = "location not confirmed"
STATUSES = ("Done", "Next up", "Pending", "Declined")
TITLE_MAX = 80


@dataclass(frozen=True)
class Requirement:
    serial: int
    module: str
    feature: str
    status: str
    release: str


@dataclass(frozen=True)
class Row:
    req: Requirement
    layer: str
    skill: str
    code: str


class WorkbookError(Exception):
    """The workbook can't be read as the requirements workbook."""


def read_workbook(path: Path) -> list[Requirement]:
    """Every numbered row of the "Requirements" sheet, in serial order."""
    try:
        import openpyxl  # noqa: PLC0415 - optional at import time so --help works without it
    except ImportError as exc:  # pragma: no cover - the dev environment has it
        raise WorkbookError("openpyxl is not installed") from exc
    try:
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise WorkbookError(f"can't open {path.name}: {exc}") from exc
    if "Requirements" not in book.sheetnames:
        raise WorkbookError("no 'Requirements' sheet")
    sheet = book["Requirements"]
    rows = sheet.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows, ())]
    want = {"Serial No.", "Module", "Feature", "Status", "Release"}
    missing = want - set(header)
    if missing:
        raise WorkbookError(f"missing columns: {', '.join(sorted(missing))}")
    col = {name: header.index(name) for name in want}
    out: list[Requirement] = []
    for values in rows:
        serial = values[col["Serial No."]] if len(values) > col["Serial No."] else None
        if isinstance(serial, str) and serial.strip().isdigit():
            serial = int(serial.strip())
        if not isinstance(serial, int) or isinstance(serial, bool):
            continue
        out.append(
            Requirement(
                serial=serial,
                module=_text(values[col["Module"]]),
                feature=_text(values[col["Feature"]]),
                status=_text(values[col["Status"]]),
                release=_text(values[col["Release"]]) or "—",
            )
        )
    book.close()
    return sorted(out, key=lambda r: r.serial)


def _text(value: object) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def short_title(feature: str) -> str:
    """The title cut at a word boundary, with no Markdown table breakers."""
    title = feature.replace("|", "/").replace("\n", " ").strip()
    if len(title) <= TITLE_MAX:
        return title
    cut = title[: TITLE_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "…"


def distinctive_words(feature: str) -> list[str]:
    """The title's distinctive words, longest first (ties in title order)."""
    seen: dict[str, int] = {}
    for i, word in enumerate(WORD.findall(feature.lower())):
        word = word.strip("'-")
        if len(word) >= 5 and word not in STOP and word not in seen:
            seen[word] = i
    return sorted(seen, key=lambda w: (-len(w), seen[w]))


class CodeIndex:
    """The lower-cased text of the files under each repository path, read once."""

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self._cache: dict[str, list[tuple[str, str]]] = {}

    def exists(self, rel: str) -> bool:
        return (self._repo / rel).exists()

    def files(self, rel: str) -> list[tuple[str, str]]:
        if rel not in self._cache:
            self._cache[rel] = list(self._read(rel))
        return self._cache[rel]

    def _read(self, rel: str) -> Iterable[tuple[str, str]]:
        root = self._repo / rel
        paths = [root] if root.is_file() else sorted(root.rglob("*")) if root.is_dir() else []
        for path in paths:
            if not path.is_file() or path.suffix not in CODE_SUFFIXES:
                continue
            if "__pycache__" in path.parts or "node_modules" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            yield path.relative_to(self._repo).as_posix(), text


def locate(req: Requirement, home: Home, index: CodeIndex) -> str:
    """Where a Done row's code is, from its own words; NOT_CONFIRMED when nothing matches."""
    paths = [p for p in home.paths if index.exists(p)]
    if not paths:
        return NOT_CONFIRMED
    ids = [m.lower() for m in CASE_ID.findall(req.feature)]
    words = distinctive_words(req.feature)
    need = 1 if len(words) < 2 else 2
    for rel in paths:
        for name, text in index.files(rel):
            if ids and all(i in text for i in ids):
                return _shown(name)
    if ids:
        return NOT_CONFIRMED
    best, best_score = "", 0
    for rel in paths:
        for name, text in index.files(rel):
            hits = sum(1 for w in words[:6] if w in text)
            score = hits + sum(2 for w in words[:6] if w[:5] in name.lower())  # name match
            if hits >= need and score > best_score:  # most of the row's words; ties: first
                best, best_score = name, score
    return _shown(best) if best else NOT_CONFIRMED


def _shown(path: str) -> str:
    """A located file as the matrix shows it (JVM package folders folded)."""
    folded = JVM_PACKAGE.sub(r"/\1/…/", path)
    return f"`{folded}`"


def build_rows(reqs: Sequence[Requirement], index: CodeIndex) -> list[Row]:
    rows: list[Row] = []
    for req in reqs:
        home = MODULES.get(req.module)
        if home is None:
            rows.append(Row(req, "—", "—", NOT_CONFIRMED if req.status == "Done" else "—"))
            continue
        code = locate(req, home, index) if req.status == "Done" else "—"
        rows.append(Row(req, LAYERS[home.layer], SKILLS[home.skill], code))
    return rows


def render(rows: Sequence[Row], version_line: str, workbook_name: str) -> str:
    status = Counter(r.req.status for r in rows)
    done = [r for r in rows if r.req.status == "Done"]
    confirmed = sum(1 for r in done if r.code != NOT_CONFIRMED)
    homeless = sorted({r.req.module for r in rows if r.req.module not in MODULES})
    layer = Counter(r.layer for r in rows)
    lines = [
        version_line,
        "",
        "# 10 · Requirements traceability matrix",
        "",
        f"Generated by `scripts/docs/adds_traceability.py` from `{workbook_name}`. Do not edit by "
        "hand: change the workbook (or the script's `MODULES` map) and run it again.",
        "",
        "## Summary",
        "",
        f"- **Rows:** {len(rows)} — "
        + ", ".join(f"{status[s]} {s}" for s in STATUSES if s in status)
        + ".",
        "- **Done rows with their code located from their own words:** "
        f"{confirmed} of {len(done)}; the other {len(done) - confirmed} say "
        f"\"{NOT_CONFIRMED}\" (they are built; the matrix just doesn't guess where).",
        "- **Rows by layer:** "
        + ", ".join(f"{name} {layer[name]}" for name in [*LAYERS.values(), "—"] if layer[name])
        + ".",
        "- **Modules with no architectural home:** "
        + (", ".join(homeless) if homeless else "none")
        + ".",
        "",
        "## Matrix",
        "",
        "| # | Feature | Layer | Skill | Release | Status | Code (Done rows) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.req.serial} | {short_title(r.req.feature)} | {r.layer} | {r.skill} | "
            f"{r.req.release} | {r.req.status} | {r.code} |"
        )
    lines += [
        "",
        "## Change log",
        "",
        "| Version | Date | Release | What changed | By |",
        "|---|---|---|---|---|",
        _change_row(version_line, workbook_name),
        "",
    ]
    return "\n".join(lines)


def _change_row(version_line: str, workbook_name: str) -> str:
    parts = [p.strip() for p in version_line.removeprefix("Version ").split("·")]
    version = parts[0] if parts else "v0.0.0"
    date = parts[1] if len(parts) > 1 else ""
    release = parts[2].removeprefix("Release ").strip() if len(parts) > 2 else ""
    owner = parts[4].removeprefix("Owner:").strip() if len(parts) > 4 else ""
    return f"| {version} | {date} | {release} | Generated from `{workbook_name}` | {owner} |"


DEFAULT_VERSION = (
    "Version v6.4.1 · 27 Nov 2026, 15:00 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV"
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--out", type=Path, default=Path("docs/architecture/design/10-traceability.md")
    )
    parser.add_argument("--version-line", default=DEFAULT_VERSION)
    parser.add_argument("--workbook-name", default=None)
    args = parser.parse_args(argv)
    try:
        reqs = read_workbook(args.workbook)
    except WorkbookError as exc:
        print(f"adds_traceability: {exc}", file=sys.stderr)
        return 2
    if not reqs:
        print("adds_traceability: no requirement rows", file=sys.stderr)
        return 2
    rows = build_rows(reqs, CodeIndex(args.repo))
    text = render(rows, args.version_line, args.workbook_name or args.workbook.name)
    out = args.out if args.out.is_absolute() else args.repo / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    done = [r for r in rows if r.req.status == "Done"]
    found = sum(1 for r in done if r.code != NOT_CONFIRMED)
    print(f"adds_traceability: {len(rows)} rows, {found} of {len(done)} Done rows located → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
