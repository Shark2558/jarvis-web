# src/jarvis/places/store.py
"""The owner's Home and Work for Maps (slice 12 D3; Layer 7 via the `Docs` port).

    {prefix}maps_places/{uid}   home, work (plain text ≤ 200 characters, or absent), updated_at

The owner's own words, typed in Integrations → Maps: trusted, sent to Google only in a route call
(never in a place search). One clean line each (`one_line`); text that is only invisible
characters is refused, and so is anything the private-query guard flags (a phone or account
number, an email address) — an address needs neither. A damaged document fails closed
(`PlacesUnreadable`): "home" then can't be resolved and nothing is sent.
"""

from __future__ import annotations

from typing import Any

from jarvis.storage.docs import Docs, Set
from jarvis.tools.card import one_line
from jarvis.web.guard import query_problem

PLACE_LIMIT = 200
FIELDS = ("home", "work")


class PlacesRejected(ValueError):
    """The text can't be saved as a place; the message is plain words for the owner."""


class PlacesUnreadable(RuntimeError):
    """The saved Home / Work can't be read (fail closed)."""


def clean_place(value: object, label: str) -> str | None:
    """One clean line, None when empty; PlacesRejected for anything that can't be a place."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlacesRejected(f"{label}: type a place, or leave it empty.")
    if len(value) > PLACE_LIMIT * 2:
        raise PlacesRejected(f"{label}: at most {PLACE_LIMIT} characters.")
    text = one_line(value, PLACE_LIMIT * 2)
    if not text:
        if value.strip():
            raise PlacesRejected(f"{label}: that text has no visible characters.")
        return None
    if len(text) > PLACE_LIMIT:
        raise PlacesRejected(f"{label}: at most {PLACE_LIMIT} characters.")
    if (what := query_problem(text)) is not None:
        raise PlacesRejected(
            f"{label}: it looks like {what}. Type a place — an area, a street or a landmark."
        )
    return text


class MapsPlaces:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self.docs = docs
        self._col = f"{prefix}maps_places"

    def _path(self, uid: str) -> str:
        if not uid or "/" in uid:
            raise ValueError("bad user id")
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> tuple[str | None, str | None]:
        doc = await self.docs.get(self._path(uid))
        if doc is None:
            return None, None
        if not isinstance(doc, dict):
            raise PlacesUnreadable("the saved Home / Work can't be read")
        out: list[str | None] = []
        for key in FIELDS:
            v = doc.get(key)
            if v is None:
                out.append(None)
            elif isinstance(v, str) and len(v) <= PLACE_LIMIT:
                out.append(v or None)
            else:
                raise PlacesUnreadable("the saved Home / Work can't be read")
        return out[0], out[1]

    async def put(self, uid: str, *, home: object, work: object) -> tuple[str | None, str | None]:
        h, w = clean_place(home, "Home"), clean_place(work, "Work")
        data: dict[str, Any] = {"home": h, "work": w}
        await self.docs.write([Set(self._path(uid), data)])
        return h, w


__all__ = [
    "FIELDS",
    "PLACE_LIMIT",
    "MapsPlaces",
    "PlacesRejected",
    "PlacesUnreadable",
    "clean_place",
]
