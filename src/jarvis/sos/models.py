# src/jarvis/sos/models.py
"""Emergency SOS: the contacts book and the phone's `sos` door payload (docs/plans/r7-mobile.md
D19, D20; docs/plans/r7-integration/phone-contract.md section 4).

- `Book` (sealed with the key purpose `sos` in `sos/{uid}`): his label for the message and at most
  `sos_max_contacts` (5) contacts. A contact is HIS label, optionally a phone number for the SMS
  screen, and, once they pressed Start on their join link, their Telegram user and chat ids. A
  pending join word is never kept: only its MAC (`join_mac`) and when it runs out.
- `parse_press`: the phone's `sos` body and the web sheet's `{"kind":"real"|"test"|"safe",
  "press_id"?, "at"?, "location"?: {"lat_e6","lon_e6","accuracy_m","age_s"}|null}`; only `kind`
  must be right, a bad place is dropped (strict integers: a coordinate is micro-degrees).
  Coordinates are used once to write the messages and are never stored, logged or audited.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

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


PRESS_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


@dataclass(frozen=True)
class Press:
    """One press as the phone or the web sheet sent it: only `kind` is needed. A place that does
    not validate is dropped (`dropped`), never a reason to refuse an SOS."""

    kind: Kind
    at: int | None = None
    location: Location | None = None
    press_id: str | None = None
    dropped: bool = False


def parse_press(raw: object) -> Press | None:
    """A press from a decoded JSON body; None only when there is no usable `kind`. Everything
    else (`v`, `at`, an extra key, a bad place, a bad press id) is best effort, because an SOS
    must go out whatever else is wrong with the request."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind not in KINDS:
        return None
    at = raw.get("at")
    pid = raw.get("press_id")
    place, dropped = raw.get("location"), False
    location: Location | None = None
    if place is not None:
        try:
            location = Location.model_validate(place)
        except ValidationError:
            dropped = True
    return Press(
        kind=kind,
        at=at if isinstance(at, int) and not isinstance(at, bool) and at >= 0 else None,
        location=location,
        press_id=pid if isinstance(pid, str) and PRESS_ID.fullmatch(pid) else None,
        dropped=dropped,
    )


__all__ = [
    "PRESS_ID",
    "Press",
    "parse_press",
    "CONTACT_ID",
    "DEFAULT_LABEL",
    "KINDS",
    "LABEL_MAX",
    "Book",
    "Contact",
    "Kind",
    "Location",
    "clean_label",
    "clean_phone",
]
