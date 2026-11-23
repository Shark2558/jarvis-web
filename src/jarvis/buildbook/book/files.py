# src/jarvis/buildbook/book/files.py
"""R6.3.1 D1-D3, D5 (docs/plans/r6-3-1-book-at-build.md): the authored files read and written.
`authored` is the public face (it re-exports all of this); paths are the repository's.

- A page file, `src/jarvis/buildbook/book/pages/<page_id>.md`: YAML front matter between two
  `---` lines (`page` = the file name, `written_by` at most 60 characters, `written_on` a date,
  `sources` path -> the first 16 hex of the SHA-256 of that tracked file's bytes, written only by
  the stamp; no other field; no YAML anchors or aliases), then the body in R6.3's five-section
  wire format (`writer/checks.parse`). `load_page` -> `PageFile`.
- A flowchart, `.../flows/<page_id>.json` (`book/flow.py`): `load_flow` -> `FlowSpec` (a key
  given twice in one object is refused).
- `all_pages(root)` / `all_flows(root)`: every file of a folder (`root`: the checkout's top),
  what loaded by page id and what didn't by `<folder>/<name>`; `.gitkeep` is ignored, any other
  file, link or folder there is an error.
- Every load error is ONE `AuthoredError` naming the file (`pages/<name>`) and the problem in
  plain words: never the file's content, a key the writer typed, or an absolute path.
- `stamped(text, hashes)` rewrites only the `sources` block (the stamp, D5); `write_text` writes
  a file atomically.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Generic, TypeVar

import yaml
from pydantic import Field, ValidationError, field_validator

from jarvis.buildbook.book.flow import FlowSpec
from jarvis.buildbook.facts_model import PAGE_ID
from jarvis.buildbook.gen.repo import BOOK_DIR as _BOOK_DIR
from jarvis.buildbook.sections import Frozen
from jarvis.buildbook.writer import checks
from jarvis.buildbook.writer.model import SectionId

BOOK_DIR = _BOOK_DIR.rstrip("/")  # "src/jarvis/buildbook/book"
PAGES, FLOWS = "pages", "flows"
PAGE_CAP_BYTES, FLOW_CAP_BYTES = 256 * 1024, 64 * 1024
WRITTEN_BY_MAX, SOURCES_MAX, REF_MAX = 60, 1_000, 300
HASH_LEN = 16
KEPT_NAMES = frozenset({".gitkeep"})  # what may sit in the folders beside the files
T = TypeVar("T")
_HASH = re.compile(rf"^[0-9a-f]{{{HASH_LEN}}}$")
_FRONT = re.compile(r"\A---[ \t]*\n(.*?)^---[ \t]*$\n?", re.S | re.M)
_SOURCES = re.compile(r"^sources[ \t]*:")
_SECTIONS = ", ".join(f"## {h}" for h in ("In plain words", "Example (made up)", "How it works",
                                         "What it costs", "When it fails"))  # fmt: skip


class AuthoredError(Exception):
    """A page or flowchart file that can't be read: `<folder>/<file>: <problem>` in plain words."""


class FrontMatter(Frozen):
    page: str = Field(pattern=PAGE_ID)
    written_by: str = Field(min_length=1, max_length=WRITTEN_BY_MAX)
    written_on: date
    sources: dict[str, str] = Field(default_factory=dict)

    @field_validator("sources", mode="before")
    @classmethod
    def _hashes(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict) or len(value) > SOURCES_MAX:
            raise ValueError(f"sources maps at most {SOURCES_MAX:,} paths to their hashes")
        for path, digest in value.items():
            if not isinstance(path, str) or not 0 < len(path) <= REF_MAX:
                raise ValueError("every sources key is a repository path")
            if not isinstance(digest, str) or not _HASH.match(digest):
                raise ValueError("every sources value is 16 lower-case hex characters (--stamp)")
        return value


class PageFile(FrontMatter):
    sections: dict[SectionId, str]


@dataclass(frozen=True)
class Loaded(Generic[T]):
    items: dict[str, T]  # page id -> what loaded
    errors: dict[str, str]  # "pages/<name>" -> the problem, plain words


# ---- reading ------------------------------------------------------------------------------------
def page_path(root: Path, page_id: str) -> Path:
    return root / BOOK_DIR / PAGES / f"{page_id}.md"


def flow_path(root: Path, page_id: str) -> Path:
    return root / BOOK_DIR / FLOWS / f"{page_id}.json"


def _where(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _read(path: Path, cap: int, suffix: str) -> str:
    where = _where(path)
    if path.suffix != suffix or not re.fullmatch(PAGE_ID, path.stem):
        raise AuthoredError(f"{where}: the file name is not a page id (pg_<kind>_<id>{suffix})")
    try:
        with path.open("rb") as handle:
            data = handle.read(cap + 1)
    except OSError:
        raise AuthoredError(f"{where}: can't be read") from None
    if len(data) > cap:
        raise AuthoredError(f"{where}: over {cap:,} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise AuthoredError(f"{where}: not UTF-8 text") from None
    if "\x00" in text:
        raise AuthoredError(f"{where}: holds a NUL character")
    return text.removeprefix("\ufeff").replace("\r\n", "\n")


def plain_errors(exc: ValidationError) -> str:
    """A validation error in words: where (field names and 1-based positions) and the rule;
    never the value, and never a key the writer typed (an unknown field is just that)."""
    said = []
    for err in exc.errors()[:3]:
        if err["type"] == "extra_forbidden":
            said.append("an unknown field")
            continue
        loc = [str(p + 1) if isinstance(p, int) else p for p in err["loc"] if isinstance(p, int)
               or p in _FIELDS]  # fmt: skip
        msg = str(err["msg"]).removeprefix("Value error, ")
        said.append(f"{'.'.join(loc)}: {msg}" if loc else msg)
    more = f" (and {exc.error_count() - 3} more)" if exc.error_count() > 3 else ""
    return "; ".join(said) + more


_FIELDS = frozenset(
    {*FrontMatter.model_fields, "title", "dir", "nodes", "edges", "id", "label", "kind", "rank",
     "col", "ref", "from", "to", "style"}
)  # fmt: skip


def _yaml(raw: str, where: str) -> dict[str, object]:
    try:
        events = list(yaml.parse(raw, Loader=yaml.SafeLoader))
        if any(isinstance(e, yaml.AliasEvent) or getattr(e, "anchor", None) for e in events):
            raise AuthoredError(f"{where}: the front matter uses YAML anchors or aliases")
        data: object = yaml.safe_load(raw)
    except yaml.YAMLError:
        raise AuthoredError(f"{where}: the front matter is not YAML") from None
    if not isinstance(data, dict):
        raise AuthoredError(f"{where}: the front matter must be a mapping of its fields")
    return data


def load_page(path: Path) -> PageFile:
    where, text = _where(path), _read(path, PAGE_CAP_BYTES, ".md")
    found = _FRONT.match(text)
    if found is None:
        raise AuthoredError(f"{where}: no front matter (a '---' line, the fields, a '---' line)")
    try:
        front = FrontMatter.model_validate(_yaml(found.group(1), where))
    except ValidationError as exc:
        raise AuthoredError(f"{where}: front matter: {plain_errors(exc)}") from None
    if front.page != path.stem:
        raise AuthoredError(f"{where}: the page field must equal the file name")
    sections = checks.parse(text[found.end() :])
    if sections is None:
        raise AuthoredError(
            f"{where}: the body is not the five sections ({_SECTIONS}), in that order, with "
            "nothing before the first"
        )
    return PageFile.model_validate({**front.model_dump(), "sections": sections})


class _Twice(Exception):
    pass


def _once(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise _Twice
        out[key] = value
    return out


def load_flow(path: Path) -> FlowSpec:
    where, text = _where(path), _read(path, FLOW_CAP_BYTES, ".json")
    try:
        data = json.loads(text, object_pairs_hook=_once)
    except _Twice:
        raise AuthoredError(f"{where}: a key appears twice in one object") from None
    except json.JSONDecodeError as exc:
        raise AuthoredError(f"{where}: not JSON (line {exc.lineno}, column {exc.colno})") from None
    if not isinstance(data, dict):
        raise AuthoredError(f"{where}: a flowchart is an object (title, dir, nodes, edges)")
    try:
        return FlowSpec.model_validate(data)
    except ValidationError as exc:
        raise AuthoredError(f"{where}: {plain_errors(exc)}") from None


def _all(root: Path, folder: str, suffix: str, load: Callable[[Path], T]) -> Loaded[T]:
    base, items, errors = root / BOOK_DIR / folder, {}, {}
    if not base.is_dir():
        return Loaded({}, {})
    for path in sorted(base.iterdir()):
        name = f"{folder}/{path.name}"
        if path.name in KEPT_NAMES:
            continue
        if path.is_symlink() or not path.is_file() or path.suffix != suffix:
            errors[name] = f"{name}: not a {folder[:-1]} file ({folder}/<page_id>{suffix})"
            continue
        try:
            items[path.stem] = load(path)
        except AuthoredError as exc:
            errors[name] = str(exc)
    return Loaded(items, errors)


def all_pages(root: Path) -> Loaded[PageFile]:
    return _all(root, PAGES, ".md", load_page)


def all_flows(root: Path) -> Loaded[FlowSpec]:
    return _all(root, FLOWS, ".json", load_flow)


# ---- the stamp (D5) -----------------------------------------------------------------------------
def stamped(text: str, hashes: Mapping[str, str]) -> str:
    """The page file's text with only its `sources` block replaced (added at the end of the
    front matter when it had none); every other line stays as it was."""
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    found = _FRONT.match(text)
    if found is None:
        raise AuthoredError("no front matter to stamp")
    block = ["sources:" + ("" if hashes else " {}")]
    block += [f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in hashes.items()]
    kept: list[str] = []
    at: int | None = None
    inside = False
    for line in found.group(1).splitlines():
        if inside and (line[:1] in (" ", "\t") or not line.strip()):
            continue
        inside = bool(_SOURCES.match(line))
        if inside:
            at = len(kept) if at is None else at
            continue
        kept.append(line)
    at = len(kept) if at is None else at
    lines = [*kept[:at], *block, *kept[at:]]
    return text[: found.start(1)] + "\n".join(lines) + "\n" + text[found.end(1) :]


def write_text(path: Path, text: str) -> None:
    """Atomically (a temporary file beside it, then a rename)."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


__all__ = [
    "BOOK_DIR",
    "FLOWS",
    "FLOW_CAP_BYTES",
    "HASH_LEN",
    "PAGES",
    "PAGE_CAP_BYTES",
    "AuthoredError",
    "FrontMatter",
    "Loaded",
    "PageFile",
    "all_flows",
    "all_pages",
    "flow_path",
    "load_flow",
    "load_page",
    "page_path",
    "plain_errors",
    "stamped",
    "write_text",
]
