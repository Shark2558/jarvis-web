# src/jarvis/buildbook/book/narration.py
"""R6.4 D6 (docs/plans/r6-4-book-look.md): a chapter's narration script, the file the Workshop
writes at build time: `src/jarvis/buildbook/book/narration/<chapter_id>.md` (the chapter ids of
`book/chapters.py`). The writers' guide is `AUTHORING-NARRATION.md`; the checks are
`book/narration_check.py`.

The file is YAML front matter between two `---` lines, then the spoken lines:

    ---
    chapter: module_vault              # equal to the file name, a chapter of the book
    written_by: Workshop · Mark XXIV
    written_on: 2026-11-25
    pages:                             # written only by `pages --narration-stamp`: each page of
      pg_module_vault: 1a2b3c4d5e6f7a8b  # the chapter -> 16 hex of its text and its flowchart
    ---
    - [page:pg_module_vault] [show:title] This chapter is about how documents reach JARVIS.
    - [node:file] It starts when you add a file.

One spoken line per list item (`- ` at the start of a file line; blank lines between are fine,
nothing else is). A line may open with cues in square brackets: `[page:<page_id>]` (the player
moves to that page: the chapter's next one), `[show:title|plain|example|how|costs|fails|overview]`
(what the stage shows), `[node:<id>]` (light a box of the page's flowchart), `[edge:<from>><to>]`
(trace a connector) and `[count:₹{{fact:<key>}}]` or `[count:{{fact:<key>}}]` (a count-up). Numbers
are `{{fact:<key>}}` placeholders, as on the pages. Pure data and parsing here: frozen pydantic
models (extra fields refused); every load error is ONE `AuthoredError` naming the file and the
file line, never its text.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from jarvis.buildbook.book.chapters import CHAPTER_ID
from jarvis.buildbook.book.files import (
    BOOK_DIR,
    HASH_LEN,
    AuthoredError,
    Loaded,
    front_of,
    plain_errors,
    read_capped,
    yaml_mapping,
)
from jarvis.buildbook.facts_model import PAGE_ID
from jarvis.buildbook.sections import Frozen

NARRATION = "narration"
NARRATION_CAP_BYTES = 128 * 1024
WRITTEN_BY_MAX = 60
LINE_MAX = 240  # characters a spoken line holds once its facts are filled
RAW_MAX = 600  # characters of a line as written (its placeholders are long)
LINES_MAX = 400
CUES_MAX = 6
TARGET_MAX = 120
PAGES_MAX = 60
CueKind = Literal["page", "show", "node", "edge", "count"]
CUE_KINDS: tuple[CueKind, ...] = ("page", "show", "node", "edge", "count")
ShowTarget = Literal["title", "plain", "example", "how", "costs", "fails", "overview"]
SHOWS: tuple[ShowTarget, ...] = ("title", "plain", "example", "how", "costs", "fails", "overview")
KEPT_NAMES = frozenset({".gitkeep"})
_HASH = re.compile(rf"^[0-9a-f]{{{HASH_LEN}}}$")
_ITEM = re.compile(r"^- (?P<rest>.*)$")
_CUE = re.compile(r"^\[(?P<kind>[a-z]{1,10}):(?P<target>[^\[\]\n]{1,120})\][ \t]*")
CUE_ANYWHERE = re.compile(r"\[(?:page|show|node|edge|count):")


class Cue(Frozen):
    kind: CueKind
    target: str = Field(min_length=1, max_length=TARGET_MAX)


class Spoken(Frozen):
    """One list item as written: its file line, its cues and its words (placeholders kept)."""

    row: int = Field(ge=1)
    cues: tuple[Cue, ...] = Field(default=(), max_length=CUES_MAX)
    text: str = Field(min_length=1, max_length=RAW_MAX)


class ScriptFront(Frozen):
    chapter: str = Field(pattern=CHAPTER_ID)
    written_by: str = Field(min_length=1, max_length=WRITTEN_BY_MAX)
    written_on: date
    pages: dict[str, str] = Field(default_factory=dict)

    @field_validator("pages", mode="before")
    @classmethod
    def _stamps(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict) or len(value) > PAGES_MAX:
            raise ValueError(f"pages maps at most {PAGES_MAX} page ids to their stamps")
        for page, digest in value.items():
            if not isinstance(page, str) or not re.fullmatch(PAGE_ID, page):
                raise ValueError("every pages key is a page id")
            if not isinstance(digest, str) or not _HASH.match(digest):
                raise ValueError("every pages value is 16 lower-case hex (--narration-stamp)")
        return value


class Script(ScriptFront):
    lines: tuple[Spoken, ...] = Field(min_length=1, max_length=LINES_MAX)


# ---- reading ------------------------------------------------------------------------------------
def script_path(root: Path, chapter_id: str) -> Path:
    return root / BOOK_DIR / NARRATION / f"{chapter_id}.md"


def _spoken(row: int, raw: str, where: str) -> Spoken:
    found = _ITEM.match(raw)
    if found is None:
        raise AuthoredError(f"{where}: line {row} is not a list item ('- ' then one spoken line)")
    rest, cues = found.group("rest").strip(), []
    while rest.startswith("["):
        cue = _CUE.match(rest)
        if cue is None:
            raise AuthoredError(f"{where}: line {row}: a cue is written [kind:target]")
        kind = cue.group("kind")
        if not cue.group("target").strip():
            raise AuthoredError(f"{where}: line {row}: a cue names nothing ([kind:] is empty)")
        if kind not in CUE_KINDS:
            raise AuthoredError(
                f"{where}: line {row}: [{kind}:...] is not a cue (page, show, node, edge, count)"
            )
        cues.append(Cue.model_validate({"kind": kind, "target": cue.group("target").strip()}))
        rest = rest[cue.end() :]
    if not rest.strip():
        raise AuthoredError(f"{where}: line {row} has no words after its cues")
    if len(cues) > CUES_MAX:
        raise AuthoredError(f"{where}: line {row} has more than {CUES_MAX} cues")
    if len(rest) > RAW_MAX:
        raise AuthoredError(f"{where}: line {row} is over {RAW_MAX} characters as written")
    return Spoken(row=row, cues=tuple(cues), text=rest.strip())


def _lines(body: str, first: int, where: str) -> list[Spoken]:
    out = []
    for n, raw in enumerate(body.split("\n"), start=first):
        if raw.strip():
            out.append(_spoken(n, raw.rstrip(), where))
    if not out:
        raise AuthoredError(f"{where}: no spoken lines ('- ' list items) after the front matter")
    if len(out) > LINES_MAX:
        raise AuthoredError(f"{where}: more than {LINES_MAX} spoken lines")
    return out


def load_script(path: Path) -> Script:
    where = f"{NARRATION}/{path.name}"
    text = read_capped(path, NARRATION_CAP_BYTES, ".md", CHAPTER_ID, "a chapter id (module_vault)")
    parts = front_of(text)
    if parts is None:
        raise AuthoredError(f"{where}: no front matter (a '---' line, the fields, a '---' line)")
    head, body, first = parts
    try:
        front = ScriptFront.model_validate(yaml_mapping(head, where))
    except ValidationError as exc:
        raise AuthoredError(f"{where}: front matter: {plain_errors(exc)}") from None
    if front.chapter != path.stem:
        raise AuthoredError(f"{where}: the chapter field must equal the file name")
    return Script.model_validate({**front.model_dump(), "lines": _lines(body, first, where)})


def all_scripts(root: Path) -> Loaded[Script]:
    """Every file of `narration/`: what loaded by chapter id, what didn't by `narration/<name>`."""
    base, items, errors = root / BOOK_DIR / NARRATION, {}, {}
    if not base.is_dir():
        return Loaded({}, {})
    for path in sorted(base.iterdir()):
        name = f"{NARRATION}/{path.name}"
        if path.name in KEPT_NAMES:
            continue
        if path.is_symlink() or not path.is_file() or path.suffix != ".md":
            errors[name] = f"{name}: not a narration file ({NARRATION}/<chapter_id>.md)"
            continue
        try:
            items[path.stem] = load_script(path)
        except AuthoredError as exc:
            errors[name] = str(exc)
    return Loaded(items, errors)


__all__ = [
    "CUES_MAX",
    "CUE_ANYWHERE",
    "CUE_KINDS",
    "LINES_MAX",
    "LINE_MAX",
    "NARRATION",
    "NARRATION_CAP_BYTES",
    "SHOWS",
    "Cue",
    "CueKind",
    "Script",
    "ScriptFront",
    "ShowTarget",
    "Spoken",
    "all_scripts",
    "load_script",
    "script_path",
]
