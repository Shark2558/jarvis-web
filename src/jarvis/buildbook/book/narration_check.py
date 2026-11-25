# src/jarvis/buildbook/book/narration_check.py
"""R6.4 D6 (docs/plans/r6-4-book-look.md): the checks a chapter's narration script passes, its
stamp and its status, for `pages --narration-*` (`gen/narration_cli.py`) and the compile
(`gen/compile_narration.py`). The format is `book/narration.py`; paths are the repository's.

- `resolve(script, plan)`: each spoken line with the page it is told on. The first page of the
  chapter opens it; `[page:<id>]` moves to the chapter's NEXT page (pages are told in order).
- `judge_script(root, plan, env)`: every problem, one line each (`<kind>: line <n> ...`, the file's
  line), and the status: `missing` | `failing` | `stale` | `ok` (failing beats stale):
  - `cues:` a page outside the chapter or out of order, a `show` that isn't one of
    `narration.SHOWS`, a `node` or `edge` not in that page's flowchart (or a page with none), a
    `count` that isn't `₹{{fact:<key>}}` / `{{fact:<key>}}` of a number, a cue after the words;
  - `numbers:` a typed number, or a fact key the pack doesn't know; `unverified:` an Unverified
    fact in a line that doesn't say so;
  - `spoken:` a backtick, a file name or path, a code name (snake_case, camelCase, a function
    call, a dotted name, a class or constant of the index), a web address;
  - `personal:` the pages' and flowcharts' word guard (`explain.private_kinds`);
  - `shape:` a line over `LINE_MAX` characters once filled; `pages:` a page of the chapter with
    no line, or with no written page to tell;
  - `stale:` not stamped, or a page's text or flowchart changed since the stamp.
- `page_stamp(root, page_id)`: the first 16 hex of the SHA-256 of a page's written sections (its
  file after the front matter, so restamping its `sources` changes nothing) and its flowchart
  file's bytes; None when the page isn't written.
- `minutes_of(texts)`: spoken words at `WPM` (150) a minute, rounded, at least 1.
No problem line quotes a spoken line; ids, keys and slugs only, when they are plain.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jarvis.buildbook.book import explain
from jarvis.buildbook.book.authored import Env
from jarvis.buildbook.book.chapters import ChapterPlan
from jarvis.buildbook.book.files import (
    FLOW_CAP_BYTES,
    HASH_LEN,
    PAGE_CAP_BYTES,
    AuthoredError,
    flow_path,
    front_of,
    load_flow,
    page_path,
    read_capped,
)
from jarvis.buildbook.book.flow import SLUG, FlowSpec
from jarvis.buildbook.book.narration import (
    CUE_ANYWHERE,
    LINE_MAX,
    SHOWS,
    Cue,
    Script,
    load_script,
    script_path,
)
from jarvis.buildbook.facts_model import PAGE_ID
from jarvis.buildbook.writer import checks, fill
from jarvis.buildbook.writer.model import FACT_PLACEHOLDER

STALE, MISSING = "stale: ", "missing"
WPM = 150  # spoken words a minute (the plan's estimate)
SHOWN = 40  # problems named for one script; the rest are counted
Status = Literal["missing", "stale", "failing", "ok"]
_PATH = re.compile(
    r"[/\\]|\b[\w-]+\.(?:py|js|mjs|css|html|json|md|toml|ya?ml|txt|sh|lock|gz|kts?|xml|cfg|ini|"
    r"env|wasm|onnx|glb)\b",
    re.I,
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CALL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\(")
_DOTTED = re.compile(r"\b[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\b")
_LOWER_CAMEL = re.compile(r"[a-z]{2,}[A-Z][A-Za-z0-9]*")
_HUMP = re.compile(r"[a-z][A-Z]")
_EDGE = re.compile(r"^([a-z][a-z0-9_]{0,30})>([a-z][a-z0-9_]{0,30})$")
_COUNT = re.compile(r"^(₹?)" + FACT_PLACEHOLDER.pattern + r"$")
_CODE_KEY = "narration.code_names"


@dataclass(frozen=True)
class Told:
    """One spoken line, resolved: its place (`n`, 1-based), its file line, its page."""

    n: int
    row: int
    page: str
    text: str
    cues: tuple[Cue, ...]


@dataclass(frozen=True)
class ScriptVerdict:
    status: Status
    problems: tuple[str, ...]
    script: Script | None = None
    told: tuple[Told, ...] = ()


# ---- pages and their order ----------------------------------------------------------------------
def _id(text: str) -> str:
    return text if re.fullmatch(PAGE_ID, text) else "a page"


def resolve(script: Script, plan: ChapterPlan) -> tuple[tuple[Told, ...], list[str]]:
    at, out, problems = 0, [], []
    for n, line in enumerate(script.lines, start=1):
        moves = [c for c in line.cues if c.kind == "page"]
        row = line.row
        if len(moves) > 1:
            problems.append(f"cues: line {row} moves page twice (one [page:...] a line)")
        elif moves:
            target = moves[0].target
            if line.cues[0].kind != "page":
                problems.append(f"cues: line {row}: [page:...] comes before its other cues")
            if target not in plan.pages:
                problems.append(f"cues: line {row}: [page:{_id(target)}] is not in this chapter")
            elif target != plan.pages[at]:
                if at + 1 < len(plan.pages) and target == plan.pages[at + 1]:
                    at += 1
                else:
                    nxt = plan.pages[at + 1] if at + 1 < len(plan.pages) else "none (the last)"
                    said = f"pages are told in the chapter's order; the next is {nxt}"
                    problems.append(f"cues: line {row}: {said}")
        out.append(Told(n, row, plan.pages[at], line.text, line.cues))
    return tuple(out), problems


# ---- one line's cues and words ------------------------------------------------------------------
def code_names(env: Env) -> frozenset[str]:
    """The index's class, function and constant names that look like code (a hump or `_`)."""
    got = env.sets.get(_CODE_KEY)
    if got is None:
        index = env.facts.index
        names = {n.rpartition(":")[2] for n in (*index.symbols, *index.constants)}
        got = frozenset(n for n in names if _HUMP.search(n) or "_" in n)
        env.sets[_CODE_KEY] = got
    return got


def _count(cue: Cue, row: int, env: Env) -> list[str]:
    found = _COUNT.match(cue.target)
    got = env.facts.values.get(found.group(2)) if found else None
    value = got.value if got is not None else None
    if not isinstance(value, int | float) or isinstance(value, bool):
        return [f"cues: line {row}: [count:...] is ₹{{{{fact:<key>}}}} or {{{{fact:<key>}}}} of a "
                "number the pack knows"]  # fmt: skip
    return []


def _slug(text: str) -> str:
    return text if re.fullmatch(SLUG, text) else "..."


def cue_problems(t: Told, flow: FlowSpec | None, env: Env) -> list[str]:
    row, pid, out = t.row, t.page, []
    kinds = Counter(c.kind for c in t.cues)
    out += [f"cues: line {row} has two [{k}:...] (one a line)" for k in ("show", "count")
            if kinds[k] > 1]  # fmt: skip
    nodes = {n.id for n in flow.nodes} if flow else set()
    edges = {(e.from_, e.to) for e in flow.edges} if flow else set()
    for c in t.cues:
        if c.kind == "show" and c.target not in SHOWS:
            out.append(f"cues: line {row}: [show:...] is one of {', '.join(SHOWS)}")
        elif c.kind == "show" and c.target == "overview" and flow is None:
            out.append(f"cues: line {row}: [show:overview] needs a flowchart; {pid} has none")
        elif c.kind in ("node", "edge") and flow is None:
            out.append(f"cues: line {row}: {pid} has no flowchart to light (use [show:...])")
        elif c.kind == "node" and c.target not in nodes:
            out.append(f"cues: line {row}: [node:{_slug(c.target)}] is not a box of {pid}")
        elif c.kind == "edge":
            m = _EDGE.match(c.target)
            if m is None or (m.group(1), m.group(2)) not in edges:
                out.append(f"cues: line {row}: [edge:...] is not a connector of {pid} (from>to)")
        elif c.kind == "count":
            out += _count(c, row, env)
    return out


def _code(typed: str, env: Env) -> bool:
    if _CALL.search(typed) or _DOTTED.search(typed):
        return True
    names = code_names(env)
    return any("_" in w or _LOWER_CAMEL.fullmatch(w) or w in names for w in _WORD.findall(typed))


def _numbers(t: Told, env: Env) -> list[str]:
    unknown = fill.unknown_keys(t.text, env.facts)
    out = [
        f"numbers: line {t.row}: {{{{fact:{k}}}}} is not a fact key (see --narration-pack)"
        if explain.quotable(k, env.scrub)
        else f"numbers: line {t.row}: a {{{{fact:...}}}} key that is not a fact key"
        for k in unknown
    ]
    if not unknown and not checks._numbers_ok(t.text, env.facts):
        out.append(f"numbers: line {t.row}: a typed number (write {{{{fact:<key>}}}})")
    weak = [k for k in fill.keys_in(t.text) if k in env.facts.values
            and not env.facts.values[k].verified]  # fmt: skip
    if weak and not any(w in t.text.lower() for w in checks.UNVERIFIED_WORDS):
        out.append(f'unverified: line {t.row}: an Unverified fact; say "Unverified" in the line')
    return out


def spoken_problems(t: Told, env: Env) -> list[str]:
    row, typed = t.row, FACT_PLACEHOLDER.sub(" ", t.text)
    out = _numbers(t, env)
    if "`" in typed:
        out.append(f"spoken: line {row}: a backtick (no code is read aloud)")
    if _PATH.search(typed):
        out.append(f"spoken: line {row}: a file name or a path (say what the part does)")
    if _code(typed, env):
        out.append(f"spoken: line {row}: a code name (say what it does in plain words)")
    if CUE_ANYWHERE.search(typed):
        out.append(f"cues: line {row}: a cue after its words (cues open the line)")
    filled = fill.fill(t.text, env.facts)
    kinds = explain.private_kinds(filled, env.scrub, env.emails)
    if "url" in kinds:
        out.append(f"spoken: line {row}: a web address")
    if rest := [k for k in kinds if k != "url"]:
        out.append(f"personal: line {row}: {', '.join(rest)} (no personal data or secrets)")
    if len(filled) > LINE_MAX:
        size = f"{len(filled)} characters once filled (at most {LINE_MAX})"
        out.append(f"shape: line {row} is {size}")
    return out


# ---- the stamp (staleness) ----------------------------------------------------------------------
def page_stamp(root: Path, page_id: str) -> str | None:
    try:
        text = read_capped(page_path(root, page_id), PAGE_CAP_BYTES, ".md", PAGE_ID, "a page id")
    except AuthoredError:
        return None
    parts = front_of(text)
    if parts is None:
        return None
    flow, extra = flow_path(root, page_id), b""
    if flow.is_symlink():
        return None
    if flow.is_file():
        try:
            extra = flow.read_bytes()[: FLOW_CAP_BYTES + 1]
        except OSError:
            return None
    return hashlib.sha256(parts[1].encode("utf-8") + b"\x00" + extra).hexdigest()[:HASH_LEN]


def stale_problems(script: Script, plan: ChapterPlan, now: Mapping[str, str | None]) -> list[str]:
    if not script.pages:
        return [f"{STALE}not stamped yet: run `pages --narration-stamp {plan.id}`"]
    out = []
    for pid in plan.pages:
        got = now.get(pid)
        if got is None:
            continue  # a page with no written text: failing, said once (`judge_script`)
        if pid not in script.pages:
            out.append(f"{STALE}{pid} is new to this chapter")
        elif script.pages[pid] != got:
            out.append(f"{STALE}{pid} changed since the script was stamped")
    gone = sorted(set(script.pages) - set(plan.pages))
    return out + [f"{STALE}{pid} is no longer in this chapter" for pid in gone]


# ---- the whole check ----------------------------------------------------------------------------
def flow_of(root: Path, page_id: str) -> FlowSpec | None:
    """A page's flowchart, or None (no file, a link, or one that fails: its page check says why)."""
    path = flow_path(root, page_id)
    if not path.exists() or path.is_symlink():
        return None
    try:
        return load_flow(path)
    except AuthoredError:
        return None


def flows_of(root: Path, plan: ChapterPlan) -> dict[str, FlowSpec | None]:
    return {pid: flow_of(root, pid) for pid in plan.pages}


def _capped(found: list[str]) -> list[str]:
    unique = list(dict.fromkeys(found))
    if len(unique) <= SHOWN:
        return unique
    return [*unique[:SHOWN], f"and {len(unique) - SHOWN} more problems"]


def check_script(script: Script, plan: ChapterPlan, root: Path, env: Env) -> ScriptVerdict:
    told, problems = resolve(script, plan)
    now = {pid: page_stamp(root, pid) for pid in plan.pages}
    flows = flows_of(root, plan)
    problems += [f"pages: {p} has no written page to tell (write it first)" for p, h in now.items()
                 if h is None]  # fmt: skip
    for t in told:
        problems += cue_problems(t, flows[t.page], env) + spoken_problems(t, env)
    said = {t.page for t in told}
    problems += [f"pages: {p} has no line (every page is told at least once)" for p in plan.pages
                 if p not in said]  # fmt: skip
    stale = stale_problems(script, plan, now)
    status: Status = "failing" if problems else "stale" if stale else "ok"
    return ScriptVerdict(status, tuple(_capped(problems + stale)), script, told)


def judge_script(root: Path, plan: ChapterPlan, env: Env) -> ScriptVerdict:
    """One chapter's script: its status and problems, from its file under `root`."""
    path = script_path(root, plan.id)
    if not path.exists() and not path.is_symlink():
        return ScriptVerdict("missing", (MISSING,))
    try:
        script = load_script(path)
    except AuthoredError as exc:
        return ScriptVerdict("failing", (str(exc),))
    return check_script(script, plan, root, env)


def stamps(root: Path, plan: ChapterPlan) -> dict[str, str]:
    """page id -> its stamp now, for every written page of the chapter (`--narration-stamp`)."""
    now = {pid: page_stamp(root, pid) for pid in plan.pages}
    return {pid: h for pid, h in now.items() if h is not None}


def words_of(text: str) -> int:
    return len(text.split())


def minutes_of(texts: Iterable[str]) -> int:
    total = sum(words_of(t) for t in texts)
    return max(1, (total + WPM // 2) // WPM) if total else 0


__all__ = [
    "MISSING",
    "STALE",
    "WPM",
    "ScriptVerdict",
    "Status",
    "Told",
    "check_script",
    "code_names",
    "cue_problems",
    "flow_of",
    "flows_of",
    "judge_script",
    "minutes_of",
    "page_stamp",
    "resolve",
    "spoken_problems",
    "stale_problems",
    "stamps",
    "words_of",
]
