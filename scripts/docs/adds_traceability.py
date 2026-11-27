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

Where the code is, never guessed. For a Done row, in this order:

1. a pointer reviewed against the code (`OVERRIDES`, serial -> repository path; checked by
   the ADD's verification on 27 Nov 2026, chapter 13), used only while that path exists;
2. a row the review could not tie to one place (`NOT_LOCATED`, serial -> the reason), shown
   as "not located: <reason>";
3. a use-case row (an id such as INV-01 or LND-14 in its title): the test named after it
   (`def test_inv01_…` or `def test_lnd_14_…`; unit tests before browser tests), else a test
   file that names the id; such a test imports and proves the code;
4. otherwise the row's own words: the code files of its module's packages are searched for the
   use-case id, or two distinctive words of the title in the same file (one, when the title has
   only one); the file with most of them wins, a word in its path counting extra. This is a lead
   to start reading, not a proof, and a new Done row stays on it until it is reviewed and given
   a pointer. No hit says "location not confirmed".

Rows not Done say "—". A pointer for a row that is missing, not Done or names a path that no
longer exists is reported on standard error (`stale_pointers`), never shown.

Only the title (cut to 80 characters) leaves the workbook: never its remarks, which can hold
personal details. Re-run at every release (workshop rules 3.8). The chapter's earlier change-log
rows are kept; `--change` says what this run changed. Exit 0 written, 2 bad input.
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
from types import MappingProxyType

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
NOT_LOCATED_PREFIX = "not located: "
TEST_ROOT = "tests"

# Done row -> the file (or folder) that carries it, each read against the row's full feature text
# and the code on 27 Nov 2026 (ADD chapter 13). Use-case rows (INV-, LND-, STY-, OPS-, AVT-) are
# not here: the test named after each use case is their pointer (rule 3).
OVERRIDES: Mapping[int, str] = MappingProxyType({
    1: "src/jarvis/core/brain.py",
    2: "src/jarvis/llm/brains.py",
    3: "src/jarvis/llm/base.py",
    4: "src/jarvis/storage/sessions.py",
    5: "src/jarvis/api/static/console-usage.js",
    6: "src/jarvis/core/persona.py",
    7: "src/jarvis/voice/service.py",
    8: "src/jarvis/tools/gateway.py",
    9: "src/jarvis/api/auth.py",
    10: ".github/workflows/ci.yml",
    11: "src/jarvis/api/static/console-deck.js",
    12: "src/jarvis/tools/google_calendar.py",
    13: "src/jarvis/tools/gmail.py",
    14: "src/jarvis/core/guardrails.py",
    15: "src/jarvis/permissions/service.py",
    16: "src/jarvis/tools/undo_delete.py",
    17: "src/jarvis/tools/reminders.py",
    18: "src/jarvis/tools/google_tasks.py",
    19: "src/jarvis/web/tools.py",
    20: "src/jarvis/web/tools.py",
    21: "src/jarvis/documents/extract.py",
    22: "src/jarvis/tools/external.py",
    23: "src/jarvis/drive/guard.py",
    24: "src/jarvis/places/tools.py",
    25: "src/jarvis/media/youtube.py",
    26: "src/jarvis/contacts/tools.py",
    27: "src/jarvis/quota/ledger.py",
    28: "src/jarvis/recall/service.py",
    29: "src/jarvis/recall/learning.py",
    30: "src/jarvis/brief/service.py",
    32: "Dockerfile",
    34: "src/jarvis/whatsapp/draft.py",
    36: "src/jarvis/telegram/service.py",
    37: "src/jarvis/activity/service.py",
    38: "src/jarvis/offline/service.py",
    42: "src/jarvis/packages/tools.py",
    43: "src/jarvis/groceries/tools.py",
    44: "src/jarvis/family/tools.py",
    46: "src/jarvis/tools/gmail_digest.py",
    51: "src/jarvis/vault/reminders.py",
    52: "src/jarvis/vault_inbox/service.py",
    53: "src/jarvis/kb/service.py",
    54: "src/jarvis/belongings/service.py",
    69: "src/jarvis/webpush/service.py",
    70: "src/jarvis/notify/policy.py",
    71: "src/jarvis/helpers/today/bills.py",
    75: "src/jarvis/helpers/house/chores.py",
    76: "src/jarvis/helpers/house/upkeep.py",
    77: "src/jarvis/helpers/house/weather.py",
    78: "src/jarvis/helpers/house/breach.py",
    82: "src/jarvis/api/static/console-voice-speech.js",
    88: "src/jarvis/homebridge/ha.py",
    101: "src/jarvis/helpers/house/upkeep.py",
    102: "src/jarvis/helpers/house/service_request.py",
    103: "android/app/src/main/java/io/github/shark2558/jarvis/shell/TalkTileService.kt",
    105: "android/app/src/main/java/io/github/shark2558/jarvis/inbox/FolderSync.kt",
    106: "android/app/src/main/java/io/github/shark2558/jarvis/health/HealthSync.kt",
    107: "src/jarvis/sos/service.py",
    109: "src/jarvis/selfwatch/jobs.py",
    110: "src/jarvis/backup/drill.py",
    111: "src/jarvis/billing/ledger.py",
    112: "src/jarvis/skills/registry.py",
    114: "src/jarvis/camera/alarm.py",
    115: "src/jarvis/faces/greeting.py",
    117: "src/jarvis/camera/history.py",
    119: "src/jarvis/camera/packages.py",
    125: "src/jarvis/helpers/nudges/standup.py",
    126: "src/jarvis/watch/sleep.py",
    127: "src/jarvis/privacy/service.py",
    134: "src/jarvis/helpers/today/birthdays.py",
    135: "src/jarvis/vitals/service.py",
    136: "src/jarvis/vitals/status.py",
    137: "src/jarvis/vitals/brief.py",
    138: "src/jarvis/health/service.py",
    139: "src/jarvis/health/changes.py",
    140: "src/jarvis/photos/picker.py",
    141: "src/jarvis/photos/api.py",
    142: "src/jarvis/integrations/github.py",
    143: "src/jarvis/integrations/youtube.py",
    144: "src/jarvis/people/research.py",
    145: "src/jarvis/api/static/console-people.js",
    146: "src/jarvis/people/research.py",
    147: "src/jarvis/offline/no_ai.py",
    148: "src/jarvis/offline/mode.py",
    149: "evals/r4_needles/run.py",
    150: "src/jarvis/ticks.py",
    151: "src/jarvis/people/privacy.py",
    156: "src/jarvis/api/static/console-voice-barge.js",
    157: "src/jarvis/api/static/console-voice-conversation.js",
    158: "src/jarvis/api/static/console-voice-mic.js",
    159: "src/jarvis/api/static/console-voice-micoff.js",
    160: "src/jarvis/api/static/console-voice-devices.js",
    161: "src/jarvis/buildbook/gen/__init__.py",
    162: "src/jarvis/buildbook/sealer.py",
    163: "src/jarvis/buildbook/book/pages",
    164: "src/jarvis/api/static/console-book-show.js",
    165: "src/jarvis/api/book_gate.py",
    166: "src/jarvis/api/book_show.py",
    167: "src/jarvis/buildbook/closing.py",
    168: "src/jarvis/buildbook/gen/snapshot.py",
    177: "src/jarvis/helpers/kitchen/recipes.py",
    178: "src/jarvis/helpers/kitchen/nutrition.py",
    179: "src/jarvis/helpers/kitchen/spend.py",
    180: "src/jarvis/helpers/kitchen/blocks.py",
    185: "src/jarvis/helpers/nudges/hydrate.py",
    186: "src/jarvis/helpers/today/pending.py",
    187: "src/jarvis/helpers/nudges/activity.py",
    188: "src/jarvis/helpers/nudges/freetime.py",
    189: "src/jarvis/helpers/today/upi.py",
    202: "src/jarvis/vitals/own.py",
    203: "src/jarvis/api/static/console-systems-modal.js",
    204: "src/jarvis/home/watchdog.py",
    205: "src/jarvis/api/static/console-people.js",
    206: "tests/browser/ui_checks.py",
    207: ".claude/agents/technical-writer.md",
    208: "scripts/markdy_export.py",
    209: "docs/architecture/JARVIS-Architecture.md",
    210: "scripts/check_doc_versions.py",
    211: "scripts/github_backfill.sh",
    212: "scripts/arch_coverage.py",
    213: "src/jarvis/api/static/console-dock.js",
    214: "src/jarvis/api/static/console-camera.js",
    215: "src/jarvis/api/app_shell.py",
    281: "src/jarvis/core/finish.py",
    282: "src/jarvis/tools/calendar_batch.py",
    283: "src/jarvis/series/service.py",
    284: "src/jarvis/brief/render.py",
    285: "src/jarvis/understand/service.py",
    286: "src/jarvis/api/static/console-attach.js",
    287: "deploy/cloudrun.sh",
    288: "src/jarvis/photos/imports.py",
    289: "src/jarvis/homebridge/face_folder.py",
    290: "src/jarvis/api/static/console-people.js",
    291: "src/jarvis/picture/research.py",
    292: "src/jarvis/vitals/words.py",
    293: "src/jarvis/vitals/own.py",
    378: "src/jarvis/buildbook/owner.py",
    380: "src/jarvis/buildbook/gen/tour.py",
    381: "src/jarvis/api/static/console-book-read.js",
    388: "src/jarvis/wardrobe/styling/tryon_card.py",
    390: "src/jarvis/api/static/console-book-chapter.js",
    391: "src/jarvis/buildbook/book/authored.py",
    392: "src/jarvis/offline/config.py",
    393: "src/jarvis/billing/service.py",
    394: "src/jarvis/api/static/console-book-fx.js",
})

# Done rows the review could not tie to one file or folder, and why.
NOT_LOCATED: Mapping[int, str] = MappingProxyType({
    31: "a property of the whole console (its phone layout, the browser's voice and passkeys "
        "through WebAuthn), not one file; chapter 07's visual gate checks it at 390×844",
    379: "R6.3's runtime Book writer was removed by R6.3.1 (ADR-21); row 391 is what replaced "
         "it, and the old trial's records are listed in chapter 04",
})
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
    how: str = ""  # reviewed | unlocated | test | words | none ("" for rows not Done)


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


def proving_test(ids: Sequence[str], index: CodeIndex) -> str | None:
    """The test file for a use case: one with a test named after its first id, else one whose
    text names it; unit tests before browser tests, then by path. None when there is none."""
    if not ids or not index.exists(TEST_ROOT):
        return None
    prefix, number = ids[0].split("-")
    named = re.compile(rf"def test_{prefix}_?0*{int(number)}_")
    mention = re.compile(rf"\b{re.escape(ids[0])}\b")
    tests = sorted(
        (
            (name, text)
            for name, text in index.files(TEST_ROOT)
            if name.endswith(".py") and name.rsplit("/", 1)[-1].startswith("test_")
        ),
        key=lambda item: (item[0].startswith(f"{TEST_ROOT}/browser/"), item[0]),
    )
    for pattern in (named, mention):
        hit = next((name for name, text in tests if pattern.search(text)), None)
        if hit:
            return hit
    return None


def pointer(
    req: Requirement,
    home: Home,
    index: CodeIndex,
    overrides: Mapping[int, str],
    unlocated: Mapping[int, str],
) -> tuple[str, str]:
    """(what the matrix shows, how it was found) for a Done row: rules 1-4 of the docstring."""
    path = overrides.get(req.serial)
    if path and index.exists(path):
        return _shown(path), "reviewed"
    if req.serial in unlocated:
        return NOT_LOCATED_PREFIX + unlocated[req.serial], "unlocated"
    ids = [m.lower() for m in CASE_ID.findall(req.feature)]
    test = proving_test(ids, index)
    if test:
        return f"{_shown(test)} (test)", "test"
    found = locate(req, home, index)
    return found, "none" if found == NOT_CONFIRMED else "words"


def stale_pointers(
    reqs: Sequence[Requirement],
    index: CodeIndex,
    overrides: Mapping[int, str],
    unlocated: Mapping[int, str],
) -> list[str]:
    """Reviewed pointers and reasons that no longer fit the workbook or the repository."""
    by = {r.serial: r for r in reqs}
    out: list[str] = []
    for serial in sorted({*overrides, *unlocated}):
        req = by.get(serial)
        if req is None:
            out.append(f"row {serial}: no such row")
        elif req.status != "Done":
            out.append(f"row {serial}: not Done ({req.status})")
        elif serial in overrides and not index.exists(overrides[serial]):
            out.append(f"row {serial}: {overrides[serial]} does not exist")
    return out


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


def build_rows(
    reqs: Sequence[Requirement],
    index: CodeIndex,
    *,
    overrides: Mapping[int, str] | None = None,
    unlocated: Mapping[int, str] | None = None,
) -> list[Row]:
    """One matrix row per requirement; the reviewed maps default to `OVERRIDES`, `NOT_LOCATED`."""
    overrides = OVERRIDES if overrides is None else overrides
    unlocated = NOT_LOCATED if unlocated is None else unlocated
    rows: list[Row] = []
    for req in reqs:
        home = MODULES.get(req.module)
        if home is None:
            rows.append(
                Row(req, "—", "—", NOT_CONFIRMED if req.status == "Done" else "—",
                    "none" if req.status == "Done" else "")
            )
            continue
        code, how = (
            pointer(req, home, index, overrides, unlocated) if req.status == "Done" else ("—", "")
        )
        rows.append(Row(req, LAYERS[home.layer], SKILLS[home.skill], code, how))
    return rows


def render(
    rows: Sequence[Row],
    version_line: str,
    workbook_name: str,
    *,
    previous: Sequence[str] = (),
    change: str | None = None,
) -> str:
    status = Counter(r.req.status for r in rows)
    done = [r for r in rows if r.req.status == "Done"]
    how = Counter(r.how for r in done)
    located = how["reviewed"] + how["test"] + how["words"]
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
        f"- **Done rows located:** {located} of {len(done)}: {how['reviewed']} by a pointer "
        "reviewed against the code (the script's `OVERRIDES`), "
        f"{how['test']} by the test named after its use case, {how['words']} by their own "
        f"words (a lead, not yet reviewed); {how['unlocated']} not located, each with its "
        f"reason; {how['none']} \"{NOT_CONFIRMED}\" (built, but the matrix doesn't guess "
        "where).",
        "- **Rows by layer:** "
        + ", ".join(f"{name} {layer[name]}" for name in [*LAYERS.values(), "—"] if layer[name])
        + ".",
        "- **Modules with no architectural home:** "
        + (", ".join(homeless) if homeless else "none")
        + ".",
        "",
        "## Matrix",
        "",
        "| # | Feature | Layer | Skill | Release | Status | Code, or the test that proves it "
        "(Done rows) |",
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
        *_log_rows(previous, version_line, workbook_name, change),
        "",
    ]
    return "\n".join(lines)


def _version_of(row: str) -> str:
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    return cells[0] if cells else ""


def _log_rows(
    previous: Sequence[str], version_line: str, workbook_name: str, change: str | None
) -> list[str]:
    """The earlier rows (oldest first), then this version's row, never a version twice."""
    mine = _change_row(version_line, workbook_name, change)
    kept = [r for r in previous if _version_of(r) != _version_of(mine)]
    return [*kept, mine]


def previous_log(text: str) -> list[str]:
    """The change-log rows of an earlier copy of the chapter (none when it has no change log)."""
    _, sep, log = text.partition("\n## Change log\n")
    if not sep:
        return []
    return [ln for ln in log.splitlines() if re.match(r"^\| v\d+\.\d+\.\d+ \|", ln)]


def _change_row(version_line: str, workbook_name: str, change: str | None = None) -> str:
    parts = [p.strip() for p in version_line.removeprefix("Version ").split("·")]
    version = parts[0] if parts else "v0.0.0"
    date = parts[1] if len(parts) > 1 else ""
    release = parts[2].removeprefix("Release ").strip() if len(parts) > 2 else ""
    owner = parts[4].removeprefix("Owner:").strip() if len(parts) > 4 else ""
    what = change or f"Generated from `{workbook_name}`"
    return f"| {version} | {date} | {release} | {what} | {owner} |"


DEFAULT_VERSION = (
    "Version v6.4.2 · 27 Nov 2026, 19:30 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV"
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
    parser.add_argument("--change", default=None, help="this run's 'What changed' cell")
    args = parser.parse_args(argv)
    try:
        reqs = read_workbook(args.workbook)
    except WorkbookError as exc:
        print(f"adds_traceability: {exc}", file=sys.stderr)
        return 2
    if not reqs:
        print("adds_traceability: no requirement rows", file=sys.stderr)
        return 2
    index = CodeIndex(args.repo)
    rows = build_rows(reqs, index)
    for problem in stale_pointers(reqs, index, OVERRIDES, NOT_LOCATED):
        print(f"adds_traceability: stale pointer, {problem}", file=sys.stderr)
    out = args.out if args.out.is_absolute() else args.repo / args.out
    before = out.read_text(encoding="utf-8") if out.is_file() else ""
    name = args.workbook_name or args.workbook.name
    text = render(
        rows, args.version_line, name, previous=previous_log(before), change=args.change
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    done = [r for r in rows if r.req.status == "Done"]
    found = sum(1 for r in done if r.how in {"reviewed", "test", "words"})
    print(f"adds_traceability: {len(rows)} rows, {found} of {len(done)} Done rows located → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
