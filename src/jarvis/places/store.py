# src/jarvis/places/store.py
"""The owner's Home and Work for Maps (slice 12 D3; Layer 7 via the `Docs` port).

    {prefix}maps_places/{uid}   blob (AES-256-GCM of {"home", "work"}), updated_at

The owner's own words, typed in Integrations → Maps: trusted, sent to Google only in a route call
(never in a place search). An address is personal data, so it is encrypted at rest exactly as the
owner's Google tokens are (`integrations.vault.TokenCipher`, the deployment's token key
`JARVIS_TOKEN_KEY`), bound to this owner and to Maps (AAD `maps_places/{uid}`: a blob copied onto
another owner's document, or read as a token, fails). Without a token key (dev) Home / Work stay
in this process only, never in the store in clear — as Google tokens do.

One clean line each (`one_line`, ≤ 200 characters); text that is only invisible characters is
refused, and so is anything the private-query guard flags (a phone or account number, an email
address) — an address needs neither. A damaged or undecryptable document fails closed
(`PlacesUnreadable`): "home" then can't be resolved and nothing is sent.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from jarvis.integrations.vault import TokenCipher, VaultError
from jarvis.storage.docs import Docs, Set
from jarvis.tools.card import one_line
from jarvis.web.guard import query_problem

PLACE_LIMIT = 200
FIELDS = ("home", "work")
Places = tuple[str | None, str | None]


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


def _fields(data: object) -> Places:
    """(home, work) from a decrypted record, each re-checked; PlacesUnreadable otherwise."""
    if not isinstance(data, dict):
        raise PlacesUnreadable("the saved Home / Work can't be read")
    out: list[str | None] = []
    for key in FIELDS:
        v = data.get(key)
        if v is None:
            out.append(None)
        elif isinstance(v, str) and len(v) <= PLACE_LIMIT:
            out.append(v or None)
        else:
            raise PlacesUnreadable("the saved Home / Work can't be read")
    return out[0], out[1]


class MapsPlaces:
    def __init__(self, docs: Docs, *, key: bytes | None = None, prefix: str = "jarvis_") -> None:
        self.docs = docs
        self._col = f"{prefix}maps_places"
        self._cipher = TokenCipher(key) if key is not None else None
        self._local: dict[str, Places] = {}  # no token key: this process only

    def _path(self, uid: str) -> str:
        if not uid or "/" in uid:
            raise ValueError("bad user id")
        return f"{self._col}/{uid}"

    @staticmethod
    def _aad(uid: str) -> str:
        return f"maps_places/{uid}"

    async def get(self, uid: str) -> Places:
        path = self._path(uid)
        if self._cipher is None:
            return self._local.get(uid, (None, None))
        doc = await self.docs.get(path)
        if doc is None:
            return None, None
        blob = doc.get("blob") if isinstance(doc, dict) else None
        if not isinstance(blob, str):
            raise PlacesUnreadable("the saved Home / Work can't be read")
        try:
            data = json.loads(self._cipher.decrypt(blob, aad=self._aad(uid)))
        except (VaultError, ValueError) as exc:
            raise PlacesUnreadable("the saved Home / Work can't be read") from exc
        return _fields(data)

    async def put(self, uid: str, *, home: object, work: object) -> Places:
        h, w = clean_place(home, "Home"), clean_place(work, "Work")
        path = self._path(uid)
        if self._cipher is None:
            self._local[uid] = (h, w)
            return h, w
        plain = json.dumps({"home": h, "work": w}).encode()
        record = {
            "blob": self._cipher.encrypt(plain, aad=self._aad(uid)),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        await self.docs.write([Set(path, record)])
        return h, w


__all__ = [
    "FIELDS",
    "PLACE_LIMIT",
    "MapsPlaces",
    "PlacesRejected",
    "PlacesUnreadable",
    "clean_place",
]
