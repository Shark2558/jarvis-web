# src/jarvis/buildbook/writer/chapters.py
"""R6.4 D5, D6 (docs/plans/r6-4-book-look.md): one release's chapters as the routes give them,
from its pages file alone: `GET /v1/book/chapters` (`view`) and `GET /v1/book/chapters/{id}`
(`one`).

A pages file compiled from v6.4.0 on carries its chapters (`PagesFile.narration`). One sealed
before has none: its chapters are worked out from its own pages (`book/chapters.py`, the same
rule), none narrated, so the reader's contents are the same shape for every kept release.
"""

from __future__ import annotations

from jarvis.buildbook.book import chapters as ch
from jarvis.buildbook.writer.http import ChapterPage, ChapterRow, ChaptersView, ChapterView
from jarvis.buildbook.writer.model import BookChapter, PagesFile


def chapters_of(f: PagesFile) -> tuple[BookChapter, ...]:
    if f.narration is not None:
        return f.narration.chapters
    return tuple(BookChapter(id=c.id, title=c.title, kind=c.kind, pages=c.pages)
                 for c in ch.chapters(f.pages))  # fmt: skip


def view(f: PagesFile) -> ChaptersView:
    rows = tuple(
        ChapterRow(
            id=c.id,
            title=c.title,
            kind=c.kind,
            pages=c.pages,
            minutes=c.minutes,
            narrated=c.narrated,
        )  # fmt: skip
        for c in chapters_of(f)
    )
    return ChaptersView(release=f.release, chapters=rows)


def one(f: PagesFile, chapter_id: str) -> ChapterView | None:
    found = next((c for c in chapters_of(f) if c.id == chapter_id), None)
    if found is None:
        return None
    titles = {p.id: p.title for p in f.pages}
    return ChapterView(
        release=f.release, id=found.id, title=found.title, kind=found.kind,
        pages=tuple(ChapterPage(id=p, title=titles.get(p, p)) for p in found.pages),
        lines=found.lines, minutes=found.minutes, narrated=found.narrated, written=found.written,
    )  # fmt: skip


__all__ = ["chapters_of", "one", "view"]
