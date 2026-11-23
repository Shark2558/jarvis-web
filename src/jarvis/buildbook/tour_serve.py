# src/jarvis/buildbook/tour_serve.py
"""R6.3 D9 (docs/plans/r6-3-book-content.md; review H1): what the show serves of the short tour.

- `tour_lines(book, audience, words) -> {"scenes": [...], "seconds": float} | None`: that
  audience's filled tour, `book.tour.owner` or `book.tour.guest` (a guest's has no T16, no
  owner-only line and no Rs: the generator made it so), each scene as `tour_model.TourScene`
  dumps it (JSON), `{h}` and its kin filled by `lines.render`'s `words`; `seconds` its timer.
  None: the book has no tour (an older book: today's 11-scene show).
- `tour_line_text(book, line_id, audience, words=None) -> str | None`: the text `POST
  /v1/book/show/speak` reads for a `tNNbMM` id, ONLY when that line and its scene are in the
  session's audience's own tour and neither is marked for the other audience; an owner-only line
  in a guest session is None (the route says 404 `unknown_line`, H1). With `words`, its `{h}` and
  kin are filled as the script's are.
`show_script.py` (I0's join) calls both; nothing here reads Book settings, a session or a clock.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from jarvis.buildbook.model import Audience, Book
from jarvis.buildbook.tour_model import TOUR_LINE_ID, AudienceTour, TourScene

TOUR_LINE = re.compile(TOUR_LINE_ID)
KIN = ("h", "his", "by")  # lines.render's words: the honorific, its possessive, the credit


def render(text: str, words: Mapping[str, str]) -> str:
    """`{h}`, `{his}` and `{by}` filled in one pass (as `lines.render` does); a word the show
    didn't give is left as it is."""
    values = {f"{{{k}}}": words[k] for k in KIN if k in words}
    if not values:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in values))
    return pattern.sub(lambda m: values[m.group(0)], text)


def _own(book: Book, audience: Audience) -> AudienceTour | None:
    tour = getattr(book, "tour", None)
    if tour is None:
        return None
    return tour.owner if audience == "owner" else tour.guest


def _scene(scene: TourScene, words: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = scene.model_dump(mode="json")
    out["beats"] = [{**b, "text": render(b["text"], words)} for b in out["beats"]]
    return out


def tour_lines(book: Book, audience: Audience, words: Mapping[str, str]) -> dict[str, Any] | None:
    own = _own(book, audience)
    if own is None:
        return None
    return {"scenes": [_scene(s, words) for s in own.scenes], "seconds": own.seconds}


def _mine(audience: Audience, *marks: str) -> bool:
    """A line (or scene) mark the session may hear: its own, or both."""
    return all(m in ("both", audience) for m in marks)


def tour_line_text(
    book: Book, line_id: str, audience: Audience, words: Mapping[str, str] | None = None
) -> str | None:
    if not TOUR_LINE.fullmatch(line_id):
        return None
    own = _own(book, audience)
    if own is None:
        return None
    for scene in own.scenes:
        for beat in scene.beats:
            if beat.id == line_id and _mine(audience, scene.audience, beat.audience):
                return beat.text if words is None else render(beat.text, words)
    return None


__all__ = ["KIN", "TOUR_LINE", "render", "tour_line_text", "tour_lines"]
