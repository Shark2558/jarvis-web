# src/jarvis/sos/models.py
"""Emergency SOS: the contacts book and the phone's `sos` door payload (docs/plans/r7-mobile.md
D19, D20; docs/plans/r7-integration/phone-contract.md section 4).

- `Book` (sealed with the key purpose `sos` in `sos/{uid}`): his label for the message and at most
  `sos_max_contacts` (5) contacts. A contact is HIS label, optionally a phone number for the SMS
  screen, and, once they pressed Start on their join link, their Telegram user and chat ids. A
  pending join word is never kept: only its MAC (`join_mac`) and when it runs out.
- `SosIn`: `{"v":1,"kind":"real"|"test"|"safe","at","location":{"lat_e6","lon_e6","accuracy_m",
  "age_s"}|null}`; strict integers (a coordinate is micro-degrees). Coordinates are used once to
  write the messages and are never stored, logged or audited.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

Kind = Literal["real", "test", "safe"]
KINDS: tuple[Kind, ...] = ("real", "test", "safe")
LABEL_MAX = 40
DEFAULT_LABEL = "the owner of this JARVIS"
_PHONE = re.compile(r"^\+?[0-9]{6,15}$")
_PHONE_JUNK = re.compile(r"[\s().-]")
CONTACT_ID = r"^c_[0-9a-f]{10}$"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def clean_label(text: object) -> str:
    """His own words, one line: control and format characters (bidi tricks) dropped, spaces
    folded, at most 40 characters ("" when nothing is left)."""
    if not isinstance(text, str):
        return ""
    kept = "".join(c for c in text if unicodedata.category(c)[0] != "C")
    return " ".join(kept.split())[:LABEL_MAX].strip()


def clean_phone(text: object) -> str | None:
    """A number for the SMS screen: digits with an optional leading +, 6 to 15 digits."""
    if not isinstance(text, str):
        return None
    bare = _PHONE_JUNK.sub("", text.strip())
    return bare if _PHONE.fullmatch(bare) else None


class Contact(_Frozen):
    id: str = Field(pattern=CONTACT_ID)
    label: str = Field(min_length=1, max_length=LABEL_MAX)
    phone: str | None = Field(default=None, pattern=_PHONE.pattern)
    tg_user: int | None = None
    tg_chat: int | None = None
    joined_at: str | None = None
    join_mac: str | None = Field(default=None, max_length=128)
    join_until: float | None = None
    added_at: str = ""

    @property
    def joined(self) -> bool:
        return self.tg_chat is not None and self.tg_user is not None


class Book(_Frozen):
    label: str = Field(default=DEFAULT_LABEL, min_length=1, max_length=LABEL_MAX)
    label_set: bool = False
    contacts: tuple[Contact, ...] = ()


class Location(_Frozen):
    lat_e6: StrictInt = Field(ge=-90_000_000, le=90_000_000)
    lon_e6: StrictInt = Field(ge=-180_000_000, le=180_000_000)
    accuracy_m: StrictInt = Field(ge=0, le=100_000)
    age_s: StrictInt = Field(ge=0, le=86_400)


class SosIn(_Frozen):
    """The phone's `sos` body (and the web sheet's, with `at` left to the server)."""

    v: StrictInt = Field(ge=1, le=1)
    kind: Kind
    at: StrictInt = Field(ge=0)
    location: Location | None = None


__all__ = [
    "CONTACT_ID",
    "DEFAULT_LABEL",
    "KINDS",
    "LABEL_MAX",
    "Book",
    "Contact",
    "Kind",
    "Location",
    "SosIn",
    "clean_label",
    "clean_phone",
]
