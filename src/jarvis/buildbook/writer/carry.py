# src/jarvis/buildbook/writer/carry.py
"""R6.3 D11, D12 (plan review H3): which pages a new release changed, and the free carry.

A page is CHANGED when a file it cites changed content (by SHA-256 inside the two releases'
`source.zip`s; a directory reference is already expanded to its files, D3), its card's text in
the guide changed, or it is new; otherwise it is carried. `carry` builds the new release's pages
file with NO brain call: every unchanged AI page from its template, refilled from the new
release's facts (a template whose fact is gone counts as changed), every changed one as the
generator's text labelled "Changed in this release: waiting for your Update". So a release sealed
without an Update loses no AI page, and the newest pages file always carries the rest.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Collection
from dataclasses import dataclass

from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.writer import fill, packs, pages
from jarvis.buildbook.writer.model import Page, PagesFile


@dataclass(frozen=True)
class Tree:
    """One release's code by content: path -> SHA-256, and card id -> its text's SHA-256."""

    files: dict[str, str]
    cards: dict[str, str]


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def tree_of(zipped: bytes) -> Tree:
    with zipfile.ZipFile(io.BytesIO(zipped)) as zf:
        hashes = {i.filename: _sha(zf.read(i)) for i in zf.infolist() if not i.is_dir()}
        guide = zf.read(packs.GUIDE).decode("utf-8", "replace") if packs.GUIDE in hashes else ""
    all_ids = [m.group(1) for m in packs._CARD.finditer(guide)]
    return Tree(files=hashes, cards={c: _sha(t) for c, t in packs.cards(guide, all_ids).items()})


def is_changed(ip: IndexedPage, old: Tree, new: Tree) -> bool:
    if any(old.files.get(ref) != new.files.get(ref) for ref in ip.refs):
        return True
    return any(old.cards.get(c) != new.cards.get(c) for c in ip.sources if c.startswith("C"))


def changed_ids(
    new_facts: FactPack, old_facts: FactPack | None, old: Tree, new: Tree
) -> tuple[str, ...]:
    """The new release's pages that changed or are new (in the pages index's order)."""
    known = {p.id for p in old_facts.pages} if old_facts is not None else set()
    return tuple(ip.id for ip in new_facts.pages if ip.id not in known or is_changed(ip, old, new))


def _refilled(template: Page, facts: FactPack) -> Page | None:
    texts = [s.text for s in template.sections]
    if any(fill.unknown_keys(t, facts) for t in texts):
        return None
    try:
        return pages.fill_page(template, facts)
    except ValueError:
        return None


def carry(rid: str, facts: FactPack, old: PagesFile | None, changed: Collection[str]) -> PagesFile:
    """The new release's pages file from the newest one, free: no brain is called."""
    templates = {t.id: t for t in (old.templates if old is not None else ())}
    written = pages.ai_written(old)
    out_pages: list[Page] = []
    out_templates: list[Page] = []
    for ip in facts.pages:
        if ip.id not in written and ip.id not in templates:
            continue  # never written by AI: the reader shows the generator's text
        template = templates.get(ip.id)
        filled = None if ip.id in changed or template is None else _refilled(template, facts)
        if filled is not None and template is not None:
            out_pages.append(filled)
            out_templates.append(template)
        else:
            out_pages.append(pages.generator_page(ip, facts, changed=True))
    return PagesFile(release=rid, pages=tuple(out_pages), templates=tuple(out_templates))


def to_write(facts: FactPack, carried: PagesFile | None) -> tuple[str, ...]:
    """The pages an update writes: every page without carried AI text (changed, new or left)."""
    have = {p.id for p in (carried.pages if carried is not None else ()) if p.meta is not None}
    return tuple(ip.id for ip in facts.pages if ip.id not in have)


__all__ = ["Tree", "carry", "changed_ids", "is_changed", "to_write", "tree_of"]
