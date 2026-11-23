# src/jarvis/buildbook/tour_serve.py
"""R6.3 D9 (docs/plans/r6-3-book-content.md; review H1): what the show serves of the short tour.
PART D builds this module; I0's stubs answer None (no tour: today's 11-scene show).

- `tour_lines(book, audience, words) -> {"scenes": [...], "seconds": float} | None`: the filled
  tour of `book.tour` for ONE audience (a guest's without T16 and without any owner-only line or
  Rs), each scene as `tour_model.TourScene` dumps it (JSON), `{h}` and its kin filled by
  `lines.render`'s `words`; `seconds` that audience's timer. None: the book has no tour.
- `tour_line_text(book, line_id, audience) -> str | None`: the text `POST /v1/book/show/speak`
  reads for a `tNNbMM` id, ONLY when that line and its scene are the session's audience's; an
  owner-only line in a guest session is None (the route says 404 `unknown_line`, H1).
`show_script.py` (I0's join) calls both; nothing else here reads Book settings or a session.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from jarvis.buildbook.model import Audience, Book
from jarvis.buildbook.tour_model import TOUR_LINE_ID

TOUR_LINE = re.compile(TOUR_LINE_ID)


def tour_lines(book: Book, audience: Audience, words: Mapping[str, str]) -> dict[str, Any] | None:
    """I0's stub (part D replaces it): no tour."""
    return None


def tour_line_text(book: Book, line_id: str, audience: Audience) -> str | None:
    """I0's stub (part D replaces it): no tour line."""
    return None


__all__ = ["TOUR_LINE", "tour_line_text", "tour_lines"]
