# src/jarvis/buildbook/writer/carry.py
"""R6.3 D11 (plan review H3); R6.3.1 D8: which pages a new release changed, by content. The free
carry of AI pages is gone with the runtime writer; the hashing stays (the basis of the authored
pages' staleness, `book/authored.source_hashes`).

A page is CHANGED when a file it cites changed content (by SHA-256 inside the two releases'
`source.zip`s; a directory reference is already expanded to its files, D3), its card's text in
the guide changed, or it is new.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Collection
from dataclasses import dataclass

from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.writer import packs


@dataclass(frozen=True)
class Tree:
    """One release's code by content: path -> SHA-256, and card id -> its text's SHA-256."""

    files: dict[str, str]
    cards: dict[str, str]


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def tree_of(zipped: bytes) -> Tree:
    """The release's files by content and its guide's cards, by repository path (R6's snapshot
    root taken off, review I1 H-2: two releases' roots differ)."""
    with zipfile.ZipFile(io.BytesIO(zipped)) as zf:
        members = {packs.member_name(i.filename): i for i in zf.infolist() if not i.is_dir()}
        hashes = {name: _sha(zf.read(i)) for name, i in members.items()}
        found = members.get(packs.GUIDE)
        guide = zf.read(found).decode("utf-8", "replace") if found is not None else ""
    all_ids = [m.group(1) for m in packs._CARD.finditer(guide)]
    return Tree(files=hashes, cards={c: _sha(t) for c, t in packs.cards(guide, all_ids).items()})


def is_changed(ip: IndexedPage, old: Tree, new: Tree) -> bool:
    if any(old.files.get(ref) != new.files.get(ref) for ref in ip.refs):
        return True
    return any(old.cards.get(c) != new.cards.get(c) for c in ip.sources if c.startswith("C"))


def changed_ids(
    new_facts: FactPack, known: Collection[str], old: Tree, new: Tree
) -> tuple[str, ...]:
    """The new release's pages that changed or are new (`known`: the page ids the older pages
    file had), in the pages index's order."""
    return tuple(ip.id for ip in new_facts.pages if ip.id not in known or is_changed(ip, old, new))


__all__ = ["Tree", "changed_ids", "is_changed", "tree_of"]
