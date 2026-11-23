# src/jarvis/buildbook/writer/pages.py
"""R6.3 D3, D11, D14: pages as the reader gets them, and the release's pages file.

- `written(ip, sections, meta)`: a page from a draft's five sections (filled text, or the template
  with its placeholders) plus the generated "Where in the code" (`code`, never written by a brain).
- `generator_page(ip, facts)`: a page not written by AI yet ("Not written by AI yet", or "Changed in
  this release: waiting for your Update" for a changed one), from the fact pack only.
- `encode_file` / `decode_file`: the `PagesFile`, gzipped canonical JSON (mtime 0, so the same
  file seals to the same bytes), at most 2 MiB.
- `view` and `page_for`: `GET /v1/book/pages` and `GET /v1/book/pages/{id}` of a kept release.
"""

from __future__ import annotations

import gzip
import io
import json
from collections.abc import Mapping

from pydantic import ValidationError

from jarvis.buildbook.facts_model import PARTS, FactPack, IndexedPage, PartId
from jarvis.buildbook.model import MAX_LIMITATIONS
from jarvis.buildbook.writer import fill
from jarvis.buildbook.writer.http import BookPart, Chapter, PageRow, PagesView, Shown
from jarvis.buildbook.writer.model import (
    CHANGED_WAITING,
    DRAFT_SECTIONS,
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


def _page(
    ip: IndexedPage, texts: Mapping[SectionId, str], meta: PageMeta | None, changed: bool
) -> Page:
    body = tuple(
        PageSection(id=sid, heading=HEADINGS[sid], text=texts.get(sid, ""))
        for sid in DRAFT_SECTIONS
    )
    return Page(
        id=ip.id, kind=ip.kind, title=ip.title, part=ip.part, chapter=ip.chapter,
        sections=(*body, code_section(ip.refs)), meta=meta, changed=changed,
    )  # fmt: skip


def written(ip: IndexedPage, sections: Mapping[SectionId, str], meta: PageMeta | None) -> Page:
    return _page(ip, sections, meta, changed=False)


def fill_page(page: Page, facts: FactPack) -> Page:
    """The page with its placeholders filled from `facts` (ValueError: a section passes its cap)."""
    out = [
        s if s.id == "code" else s.model_copy(update={"text": fill.fill(s.text, facts)})
        for s in page.sections
    ]
    return Page.model_validate({**page.model_dump(), "sections": [s.model_dump() for s in out]})


def generator_page(ip: IndexedPage, facts: FactPack, *, changed: bool = False) -> Page:
    """The generator's text for a page no brain wrote (or whose code changed since)."""
    label = CHANGED_WAITING if changed else NOT_WRITTEN
    card = next((c for c in facts.cards if c.id in ip.sources), None)
    where = f" It belongs to the {card.module} module." if card is not None else ""
    texts: dict[SectionId, str] = {
        "plain": f"{label}. This page is about {ip.title}.{where}",
        "how": "Written from " + ", ".join(ip.sources) + "." if ip.sources else "",
    }
    return _page(ip, texts, None, changed)


# ---- the pages file ----------------------------------------------------------------------------
def encode_file(f: PagesFile) -> bytes:
    raw = json.dumps(f.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    data = gzip.compress(raw.encode("utf-8"), mtime=0)
    if len(data) > PAGES_FILE_CAP_BYTES:
        raise ValueError("a pages file is over its 2 MiB cap")
    return data


def decode_file(data: bytes) -> PagesFile:
    """ValueError (never a partial file): not gzip, too big, not JSON, not v1."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            raw = gz.read(FILE_CAP_PLAIN + 1)
    except (OSError, EOFError):
        raise ValueError("a pages file is not gzip") from None
    if len(raw) > FILE_CAP_PLAIN:
        raise ValueError("a pages file is too big")
    try:
        return PagesFile.model_validate_json(raw)
    except ValidationError:
        raise ValueError("a pages file is not a v1 pages file") from None


def ai_written(f: PagesFile | None) -> dict[str, Page]:
    """The pages of a file a brain wrote (with their meta), by id."""
    return {} if f is None else {p.id: p for p in f.pages if p.meta is not None}


# ---- the reader's views (D14) --------------------------------------------------------------------
def _chapters(
    part: PartId, facts: FactPack, rows: list[tuple[IndexedPage, PageRow]]
) -> tuple[Chapter, ...]:
    if part != "parts":
        title = dict(PARTS)[part]
        return (Chapter(id=part, title=title, pages=tuple(r for _, r in rows)),) if rows else ()
    titles = {m.id: m.title for m in facts.modules}
    order = list(dict.fromkeys(ip.chapter for ip, _ in rows))
    return tuple(
        Chapter(id=c, title=titles.get(c, c), pages=tuple(r for ip, r in rows if ip.chapter == c))
        for c in order
    )


def view(rid: str, facts: FactPack, f: PagesFile | None) -> PagesView:
    by = {p.id: p for p in (f.pages if f is not None else ())}
    parts = []
    for part, title in PARTS:
        rows = [
            (
                ip,
                PageRow(
                    id=ip.id,
                    kind=ip.kind,
                    title=ip.title,
                    written=getattr(by.get(ip.id), "meta", None),
                    changed=bool(getattr(by.get(ip.id), "changed", False)),
                ),
            )  # fmt: skip
            for ip in facts.pages
            if ip.part == part
        ]
        chapters = _chapters(part, facts, rows)
        if chapters:
            parts.append(BookPart(id=part, title=title, chapters=chapters))
    total = len(facts.limitations)
    return PagesView(
        release=rid,
        parts=tuple(parts),
        limitations=Shown(shown=min(total, MAX_LIMITATIONS), total=total),
    )


def page_for(page_id: str, facts: FactPack, f: PagesFile | None) -> Page | None:
    ip = facts.page(page_id)
    if ip is None:
        return None
    found = next((p for p in (f.pages if f is not None else ()) if p.id == page_id), None)
    return found or generator_page(ip, facts)


__all__ = [
    "ai_written",
    "code_section",
    "decode_file",
    "encode_file",
    "fill_page",
    "generator_page",
    "page_for",
    "view",
    "written",
]
