# src/jarvis/buildbook/writer/pages.py
"""R6.3 D3, D14; R6.3.1 D4, D7: pages as the reader gets them, and a release's pages and flows
files.

- `written(ip, sections, meta)`: a page from its five written sections (filled text) plus the
  generated "Where in the code" (`code`, never written).
- `generator_page(ip, facts)`: a page nobody has written yet, or whose file fails its checks
  ("Not written yet"), from the fact pack only.
- `encode_file` / `decode_file`: the `PagesFile` (v2), gzipped canonical JSON (mtime 0, so the
  same pages compile to the same bytes), at most 2 MiB; a gzip bomb is refused before it is
  parsed. `encode_flows` / `decode_flows`: the flowcharts by page id, canonical JSON, at most
  1 MiB (`FlowSpec`s dumped by alias, so an edge's `from` is "from").
- `view(f)`, `page_for(page_id, f)` and `served(page, flows)`: `GET /v1/book/pages` and
  `GET /v1/book/pages/{id}` from one release's files alone (the page JSON gains `flow`).
"""

from __future__ import annotations

import gzip
import io
import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from jarvis.buildbook.book.flow import FlowSpec
from jarvis.buildbook.facts_model import PARTS, FactPack, IndexedPage, PartId
from jarvis.buildbook.model import MAX_LIMITATIONS
from jarvis.buildbook.writer import fill
from jarvis.buildbook.writer.http import BookPart, Chapter, PageRow, PagesView, Shown
from jarvis.buildbook.writer.model import (
    DRAFT_SECTIONS,
    FLOWS_FILE_CAP_BYTES,
    HEADINGS,
    NOT_WRITTEN,
    PAGES_FILE_CAP_BYTES,
    SECTION_CAPS,
    Page,
    PageMeta,
    PageSection,
    PagesFile,
    SectionId,
)

FILE_CAP_PLAIN = 16 * PAGES_FILE_CAP_BYTES  # a gzip bomb is refused before it is parsed


def code_section(refs: tuple[str, ...]) -> PageSection:
    lines, size = [], 0
    for ref in refs:
        line = f"`{ref}`"
        if size + len(line) + 1 > SECTION_CAPS["code"]:
            break
        lines.append(line)
        size += len(line) + 1
    return PageSection(id="code", heading=HEADINGS["code"], text="\n".join(lines), refs=refs)


def _page(ip: IndexedPage, texts: Mapping[SectionId, str], meta: PageMeta | None) -> Page:
    body = tuple(
        PageSection(id=sid, heading=HEADINGS[sid], text=texts.get(sid, ""))
        for sid in DRAFT_SECTIONS
    )
    return Page(
        id=ip.id, kind=ip.kind, title=ip.title, part=ip.part, chapter=ip.chapter,
        sections=(*body, code_section(ip.refs)), meta=meta,
    )  # fmt: skip


def written(ip: IndexedPage, sections: Mapping[SectionId, str], meta: PageMeta | None) -> Page:
    return _page(ip, sections, meta)


def fill_page(page: Page, facts: FactPack) -> Page:
    """The page with its placeholders filled from `facts` (ValueError: a section passes its cap)."""
    out = [
        s if s.id == "code" else s.model_copy(update={"text": fill.fill(s.text, facts)})
        for s in page.sections
    ]
    return Page.model_validate({**page.model_dump(), "sections": [s.model_dump() for s in out]})


def generator_page(ip: IndexedPage, facts: FactPack) -> Page:
    """The generator's text for a page not written yet (or whose file fails its checks)."""
    card = next((c for c in facts.cards if c.id in ip.sources), None)
    where = f" It belongs to the {card.module} module." if card is not None else ""
    texts: dict[SectionId, str] = {
        "plain": f"{NOT_WRITTEN}. This page is about {ip.title}.{where}",
        "how": "Written from " + ", ".join(ip.sources) + "." if ip.sources else "",
    }
    return _page(ip, texts, None)


# ---- the pages file and the flows file ----------------------------------------------------------
def _canonical(tree: object) -> bytes:
    return json.dumps(tree, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def encode_file(f: PagesFile) -> bytes:
    data = gzip.compress(_canonical(f.model_dump(mode="json")), mtime=0)
    if len(data) > PAGES_FILE_CAP_BYTES:
        raise ValueError("a pages file is over its 2 MiB cap")
    return data


def unzipped(data: bytes) -> bytes:
    """A pages file's JSON bytes (ValueError: not gzip, or past 16 times the cap once open)."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            raw = gz.read(FILE_CAP_PLAIN + 1)
    except (OSError, EOFError):
        raise ValueError("a pages file is not gzip") from None
    if len(raw) > FILE_CAP_PLAIN:
        raise ValueError("a pages file is too big")
    return raw


def decode_file(data: bytes) -> PagesFile:
    """ValueError (never a partial file): not gzip, too big, not JSON, not v2."""
    try:
        return PagesFile.model_validate_json(unzipped(data))
    except ValidationError:
        raise ValueError("a pages file is not a v2 pages file") from None


def _flow_json(spec: FlowSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json", by_alias=True, exclude_none=True)


def encode_flows(flows: Mapping[str, FlowSpec]) -> bytes:
    data = _canonical({pid: _flow_json(f) for pid, f in flows.items()})
    if len(data) > FLOWS_FILE_CAP_BYTES:
        raise ValueError("a flows file is over its 1 MiB cap")
    return data


def decode_flows(data: bytes) -> dict[str, dict[str, Any]]:
    """Page id -> its flowchart as JSON, each one checked again (ValueError, never a part)."""
    if len(data) > FLOWS_FILE_CAP_BYTES:
        raise ValueError("a flows file is over its cap")
    try:
        raw = json.loads(data)
        if not isinstance(raw, dict):
            raise ValueError("a flows file is an object")
        specs = {str(k): FlowSpec.model_validate(v) for k, v in raw.items()}
    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("a flows file is not a flows file") from None
    return {k: _flow_json(s) for k, s in specs.items()}


# ---- the reader's views (D14) --------------------------------------------------------------------
def _chapters(f: PagesFile, part: PartId, rows: list[tuple[Page, PageRow]]) -> tuple[Chapter, ...]:
    if part != "parts":
        title = dict(PARTS)[part]
        return (Chapter(id=part, title=title, pages=tuple(r for _, r in rows)),) if rows else ()
    order = list(dict.fromkeys(p.chapter for p, _ in rows))
    return tuple(
        Chapter(id=c, title=f.modules.get(c, c), pages=tuple(r for p, r in rows if p.chapter == c))
        for c in order
    )


def view(f: PagesFile) -> PagesView:
    parts = []
    for part, title in PARTS:
        rows = [
            (p, PageRow(id=p.id, kind=p.kind, title=p.title, written=p.meta))
            for p in f.pages
            if p.part == part
        ]
        chapters = _chapters(f, part, rows)
        if chapters:
            parts.append(BookPart(id=part, title=title, chapters=chapters))
    shown = min(f.limitations, MAX_LIMITATIONS)
    return PagesView(
        release=f.release, parts=tuple(parts), limitations=Shown(shown=shown, total=f.limitations)
    )


def page_for(page_id: str, f: PagesFile) -> Page | None:
    return next((p for p in f.pages if p.id == page_id), None)


def served(page: Page, flows: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    """The page as the route sends it: `Page` JSON plus `flow` (its flowchart, or null)."""
    return {**page.model_dump(mode="json"), "flow": flows.get(page.id)}


__all__ = [
    "code_section",
    "decode_file",
    "decode_flows",
    "encode_file",
    "encode_flows",
    "fill_page",
    "generator_page",
    "page_for",
    "served",
    "unzipped",
    "view",
    "written",
]
