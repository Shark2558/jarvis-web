# tests/test_r64_i1_chapters_label.py -- R6.4 I1 (docs/plans/r6-4-book-look.md D3; the approved
# mockup's chip "R6.4 · v6.4.0 · 3f2a1c9"): `GET /v1/book/chapters` carries the sealed release's
# label beside its id, so the reader's release chip can say it. The label is optional: a view built
# without a sealed release (or an old answer) has none, and the reader then shows version and id.
# The route itself (the kept release's label, and each row's `lines`, the Continue card's "of 80")
# is pinned in test_r64_i0_routes.
from __future__ import annotations

import pytest
from pydantic import ValidationError

from jarvis.buildbook.writer import chapters
from jarvis.buildbook.writer.http import ChaptersView
from jarvis.buildbook.writer.model import PagesFile


def _file() -> PagesFile:
    return PagesFile(release="abcdef0", pages=(), modules={})


def test_the_chapters_view_carries_the_release_label() -> None:
    got = chapters.view(_file(), label="R6.4").model_dump(mode="json")
    assert got == {"release": "abcdef0", "label": "R6.4", "chapters": []}


def test_the_label_is_optional_and_checked() -> None:
    assert chapters.view(_file()).label is None
    for bad in ("6.4", "R6.4.1.2", "r6.4", "R6.4 <b>"):
        with pytest.raises(ValidationError):
            ChaptersView(release="abcdef0", label=bad)
