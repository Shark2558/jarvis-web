# src/jarvis/buildbook/gen/pages_index.py
"""R6.3 D3 (docs/plans/r6-3-book-content.md): the full book's pages index. PART A builds this
module; I0's stub lists no page.

`build(repo, facts) -> tuple[IndexedPage, ...]` (`jarvis.buildbook.facts_model`): every page from
the guide and the code, in a fixed order: the eight chapters of "JARVIS in plain words"
(`facts_model.CHAPTERS`), the 18 modules (`gen/modules.py`), the 73 cards under their modules,
the 22 console panels and the show, the 31 outside services: 152 pages on 47ee8fc. Each page's
`refs` are full, scrubbed paths, resolved by `gen/refs.resolve` (a reference that doesn't resolve
is a GenError) with a directory expanded to its files. The join puts them in `facts.json`.
"""

from __future__ import annotations

from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.gen.repo import Repo


def build(repo: Repo, facts: FactPack) -> tuple[IndexedPage, ...]:
    """I0's stub (part A replaces it): no pages."""
    return ()


__all__ = ["build"]
