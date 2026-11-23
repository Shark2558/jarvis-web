# src/jarvis/buildbook/gen/facts.py
"""R6.3 D2 (docs/plans/r6-3-book-content.md): the fact pack, computed at CI from the release's own
code, never typed. PART A builds this module; I0's stub returns an empty pack.

`build(repo, scrub) -> FactPack` (`jarvis.buildbook.facts_model`): `values` (every key of
`FACT_TOUR_KEYS`, every literal module constant as `path:NAME`, every setting as
`settings.<name>`), `index`, `routes` (M9), `settings`, `collections`, `modules` and `cards` (the
guide and `gen/modules.py`), `screens`, `services` (`gen/services.py`, M7), `loc` (D2a),
`limitations` (G4). Paths SCRUBBED (`scrub.clean`, H6). Deterministic, standard library only.
The join (`gen/write.py`) sets `release` and `pages` and checks the pack: don't set them here.
"""

from __future__ import annotations

from jarvis.buildbook.facts_model import FactPack
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import Scrubber


def build(repo: Repo, scrub: Scrubber) -> FactPack:
    """I0's stub (part A replaces it): an empty pack."""
    return FactPack()


__all__ = ["build"]
