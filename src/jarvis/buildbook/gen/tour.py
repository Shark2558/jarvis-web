# src/jarvis/buildbook/gen/tour.py
"""R6.3 D9 (docs/plans/r6-3-book-content.md "The short tour's first script"): the short tour,
filled and timed at CI. PART D builds this module; I0's stub builds no tour.

`build(repo, facts) -> Tour | None` (`jarvis.buildbook.tour_model`): `gen/tour.json` (the
Workshop's script the owner approved on 23 Nov 2026, copied verbatim) with every `{{key}}` filled
from the fact pack (an unknown key, a line over 400 characters once filled, or a digit typed
outside a placeholder is a GenError, except in the running example's quoted words and "3D"),
each scene's picture data (`from_show` copied from the show, or its own list, M6), and each
audience's timing (`tour_model.seconds`) inside the hard band. None: no script (an empty one).
"""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from jarvis.buildbook.facts_model import FactPack
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.tour_model import Tour, TourScript

# package data (pyproject.toml), read through importlib.resources (the deploy installs it)
SCRIPT_FILE: Traversable | Path = files("jarvis.buildbook.gen") / "tour.json"


def load_script(path: Traversable | Path | None = None) -> TourScript:
    return TourScript.model_validate_json((path or SCRIPT_FILE).read_bytes())


def build(repo: Repo, facts: FactPack) -> Tour | None:
    """I0's stub (part D replaces it): no tour (the book plays today's 11 scenes)."""
    return None


__all__ = ["SCRIPT_FILE", "build", "load_script"]
