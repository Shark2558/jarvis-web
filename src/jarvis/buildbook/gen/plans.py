# src/jarvis/buildbook/gen/plans.py
"""R6 D2, D4: what the generator reads from `docs/plans/*.md` (text only; scrubbed first, D3).

- `release_label`: from the highest `r<N>[-<M>]-*.md` plan ("R6", "R5.1"); "R0" with none.
- `read_plans`: every plan, newest first (release plans by number, then phase slices by slice).
- `decisions`: each plan's title and its D-headings, once each, in any of the three styles the
  plans use (`**D1 · Title.**`, `### D1 · Title`, `- **D1 — Title.**`), as "D1 · Title".
- `fit_rows`: the release plans' "Architecture fit" / "How it fits the architecture" tables.
- `limitations`: "Not in this plan", Risks, Needs the owner / you first, Open questions,
  Deferred — the first sentence of each item (<= 200 characters), newest plan first, <= 80.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from jarvis.buildbook.gen.code import clip
from jarvis.buildbook.gen.fallback import RELEASE_PLAN as _RELEASE
from jarvis.buildbook.gen.fallback import label_of
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.model import MAX_LIMITATIONS
from jarvis.buildbook.sections import FitRow, Limitation, PlanDecisions

PLANS = "docs/plans/"
TEXT_MAX, TITLE_MAX, DECISION_MAX = 200, 300, 200
_SLICE = re.compile(r"^phase\d+-slice(\d+)([a-z]?)-")
_SEP = r"(?:\s*[·—–:-]\s+|\s+)"
_D_HEADS = (
    re.compile(rf"^\*\*D(\d+){_SEP}(.+?)\*\*"),
    re.compile(rf"^#{{2,4}}\s+D(\d+){_SEP}(.+?)\s*$"),
    re.compile(rf"^[-*]\s+\*\*D(\d+){_SEP}(.+?)\*\*"),
)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_ITEM = re.compile(r"^(?:[-*]|\d{1,2}\.)\s+(.*)$")
# "Not in this plan:" alone on its line, a list after it: read as a heading
_LEAD_IN = re.compile(r"^\**(Not in this (?:plan|slice|release))\**:\s*$", re.IGNORECASE)
_INLINE_NOT = re.compile(r"\bNot in this (?:plan|slice|release):\s*(.+)", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(\[])")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("open_question", re.compile(r"^open questions", re.IGNORECASE)),
    ("risk", re.compile(r"^risks\b", re.IGNORECASE)),
    ("needs_owner", re.compile(r"^needs (?:the owner|you)", re.IGNORECASE)),
    ("not_in_plan", re.compile(r"^(?:not in this (?:plan|slice|release)|out of scope)", re.I)),
    ("deferred", re.compile(r"^(?:deferred|next waves)", re.IGNORECASE)),
)
_FIT = re.compile(r"architecture fit|how it fits the architecture", re.IGNORECASE)


@dataclass(frozen=True)
class Plan:
    path: str
    label: str  # "R6", "R5.1" or "" (a phase slice)
    title: str
    lines: tuple[str, ...]  # the plan's text, already scrubbed


def _order(path: str) -> tuple[int, int, int, str]:
    name = path.rsplit("/", 1)[-1]
    rel, sl = _RELEASE.match(name), _SLICE.match(name)
    if rel:
        return (2, int(rel.group(1)), int(rel.group(2) or 0), name)
    if sl:
        return (1, int(sl.group(1)), ord(sl.group(2) or "@"), name)
    return (0, 0, 0, name)


def plan_paths(repo: Repo) -> tuple[str, ...]:
    found = (p for p in repo.under(PLANS) if p.endswith(".md") and p.count("/") == 2)
    return tuple(sorted(found, key=_order, reverse=True))


def release_label(repo: Repo) -> str:
    labelled = [p for p in plan_paths(repo) if label_of(p)]
    return label_of(labelled[0]) if labelled else "R0"


def plain_md(text: str) -> str:
    """Markdown emphasis, code ticks and links reduced to their words, on one line."""
    text = _LINK.sub(r"\1", text).replace("**", "").replace("`", "")
    return " ".join(text.split())


def read_plans(repo: Repo, scrub: Scrubber) -> tuple[Plan, ...]:
    out = []
    for path in plan_paths(repo):
        text = scrub.clean(repo.text(path) or "")
        lines = tuple(text.splitlines())
        head = next((ln for ln in lines if ln.startswith("# ")), "# " + path)
        out.append(Plan(path, label_of(path), clip(plain_md(head[2:]), TITLE_MAX), lines))
    return tuple(out)


# ---- decisions -------------------------------------------------------------------------------
def _heads(plan: Plan) -> tuple[str, ...]:
    seen: dict[int, str] = {}
    for line in plan.lines:
        for pattern in _D_HEADS:
            m = pattern.match(line.strip())
            if m and int(m.group(1)) not in seen:
                seen[int(m.group(1))] = clip(
                    f"D{m.group(1)} · {plain_md(m.group(2))}", DECISION_MAX
                )
                break
    return tuple(seen.values())


def decisions(read: tuple[Plan, ...]) -> tuple[PlanDecisions, ...]:
    return tuple(
        PlanDecisions(plan=p.path, release=p.label, title=p.title, decisions=_heads(p))
        for p in read
    )


# ---- sections and items ----------------------------------------------------------------------
def _sections(plan: Plan) -> Iterator[tuple[str, list[str]]]:
    """(heading text, its lines) for every heading, in order; the text before any heading too."""
    title, body = "", list[str]()
    for line in plan.lines:
        m = _HEADING.match(line) or _LEAD_IN.match(line)
        if m:
            yield title, body
            title, body = plain_md(m.group(m.lastindex or 1)), []
        else:
            body.append(line)
    yield title, body


def _items(body: list[str]) -> list[str]:
    """Top-level list items (continuation lines joined); else the first paragraph."""
    items: list[list[str]] = []
    open_item = False
    for line in body:
        m = _ITEM.match(line)
        if m:
            items.append([m.group(1)])
            open_item = True
        elif open_item and line.strip():
            items[-1].append(line.strip())
        else:
            open_item = False  # a blank line ends the item's text
    if items:
        return [plain_md(" ".join(i)) for i in items]
    return _paragraphs(body)[:1]


def _paragraphs(body: list[str]) -> list[str]:
    out, cur = [], []
    for line in [*body, ""]:
        if line.strip() and not line.lstrip().startswith("|") and not _ITEM.match(line):
            cur.append(line.strip())
        elif cur:
            out.append(plain_md(" ".join(cur)))
            cur = []
    return out


def first_sentence(text: str, limit: int = TEXT_MAX) -> str:
    first = _SENTENCE_END.split(text.strip(), maxsplit=1)[0].strip()
    first = first[:1].upper() + first[1:]
    return clip(first, limit)


def _kind(title: str) -> str | None:
    bare = re.sub(r"^\d+\.\s*", "", title)
    return next((k for k, pattern in _KINDS if pattern.search(bare)), None)


def _plan_limits(plan: Plan) -> Iterator[Limitation]:
    def lim(kind: str, text: str) -> Limitation:
        return Limitation.model_validate(
            {"text": first_sentence(text), "kind": kind, "source": plan.path, "release": plan.label}
        )

    for title, body in _sections(plan):
        kind = _kind(title) if title else None
        if kind:
            yield from (lim(kind, t) for t in _items(body) if t.strip())
            continue
        for para in _paragraphs(body):
            m = _INLINE_NOT.search(para)
            if m and m.group(1).strip():
                yield lim("not_in_plan", m.group(1))


def limitations(read: tuple[Plan, ...]) -> tuple[Limitation, ...]:
    out: list[Limitation] = []
    for plan in read:
        out.extend(_plan_limits(plan))
        if len(out) >= MAX_LIMITATIONS:
            break
    return tuple(out[:MAX_LIMITATIONS])


# ---- architecture fit ------------------------------------------------------------------------
def _cells(line: str) -> list[str]:
    return [plain_md(c) for c in line.strip().strip("|").split("|")]


def _table(body: list[str]) -> list[dict[str, str]]:
    rows = [ln for ln in body if ln.lstrip().startswith("|")]
    if len(rows) < 3:
        return []
    head = [h.lower() for h in _cells(rows[0])]
    if not head or head[0] != "feature" or not any("layer" in h for h in head):
        return []
    col = {
        k: next((i for i, h in enumerate(head) if k in h), -1)
        for k in ("layer", "phase", "verdict")
    }
    out = []
    for row in rows[2:]:
        cells = _cells(row)
        pick = {k: cells[i] if 0 <= i < len(cells) else "" for k, i in col.items()}
        out.append({"feature": cells[0], **pick})
    return out


def fit_rows(read: tuple[Plan, ...]) -> tuple[FitRow, ...]:
    out = []
    for plan in read:
        if not plan.label:
            continue
        body = next((b for t, b in _sections(plan) if _FIT.search(t)), [])
        for row in _table(body):
            out.append(
                FitRow(
                    release=plan.label,
                    feature=clip(row["feature"], 160),
                    layer=clip(row["layer"], 160),
                    phase=clip(row["phase"], 60),
                    verdict=clip(row["verdict"], 160),
                )
            )
    return tuple(out)


__all__ = [
    "Plan",
    "decisions",
    "first_sentence",
    "fit_rows",
    "label_of",
    "limitations",
    "plain_md",
    "plan_paths",
    "read_plans",
    "release_label",
]
