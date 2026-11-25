# src/jarvis/buildbook/writer/texts.py
"""The full book's own words (R6.3 D14; R6.3.1 D7; R6.4): the pages routes' refusals, plain and
owner-facing, by code (`http.Refusal.detail`). Never a vendor's text, a path or a page's text.
"""

from __future__ import annotations

STATUS = {
    "not_primary": 403, "owner_only": 403, "no_page": 404, "no_pages": 404, "unavailable": 503,
    "rate_limited": 429, "no_chapter": 404, "bad_query": 422,
}  # fmt: skip

REFUSED: dict[str, str] = {
    "not_primary": "Only the main owner's console reads the full book.",
    "no_page": "That page isn't in this release's full book.",
    "no_pages": "This release was sealed before its full book was written.",
    "unavailable": "The full book can't be read right now. Try again in a moment.",
    "rate_limited": "Too many requests; wait a moment.",
    "no_chapter": "That chapter isn't in this release's full book.",  # R6.4 D5
    "bad_query": "Search for a word or two: 2 to 60 characters.",  # R6.4 D4
}


class PagesRefused(Exception):
    """A refusal the pages routes answer as `http.Refusal`: its code, status and plain words."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.status = STATUS.get(code, 404)
        self.detail = REFUSED.get(code, REFUSED["no_page"])


__all__ = ["REFUSED", "STATUS", "PagesRefused"]
