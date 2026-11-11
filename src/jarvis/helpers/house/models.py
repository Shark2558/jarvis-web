# src/jarvis/helpers/house/models.py
"""Part B's data (docs/plans/r11-free-helpers.md data model, D10-D14). Pure models, no I/O.

- `Chore` (`chores/{uid}`): his label, how often (daily, on chosen weekdays, every N days), the
  time, and a rota of up to 6 member labels he types (adults only: no ages, no children's data).
  `turn` is whose turn it is for the occurrence `turn_day`; the turn moves on "done" and at each
  period's end (`chores.whose`), so the stored doc changes only when he changes it.
- `Upkeep` (`maintenance/{uid}`): an item every N days or months, its last-done day and a lead.
- `Outside` (`outside/{uid}`, sealed with `alerts_place`): his place (district, state, the
  coordinates rounded to 0.01 degrees, about 1 km), his weather thresholds, whether breach
  notices are watched, and the feeds' bookkeeping (when checked, an outage, the SACHET items
  seen and the warnings still active, whose outside words are kept only here, sealed).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LABEL_MAX = 40
MEMBER_MAX = 24
MAX_MEMBERS = 6
MAX_CHORES = 30
MAX_UPKEEP = 40
MAX_EVERY_DAYS = 90
MAX_UPKEEP_DAYS, MAX_UPKEEP_MONTHS = 3650, 120
MAX_LEAD_DAYS = 60
MAX_SEEN = 400
MAX_QUEUE = 200
MAX_WARNINGS = 20
OUTSIDE_TEXT_MAX = 200
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
Freq = Literal["daily", "weekly", "every"]
Unit = Literal["days", "months"]
_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_ID = r"^[0-9a-f]{8}$"
_DAY = r"^\d{4}-\d{2}-\d{2}$"
_PLACE_WORD = re.compile(r"^[A-Za-z][A-Za-z .'\-]{0,39}$")

# The states and union territories (his pick); SACHET's state feeds JARVIS has seen answer
# (others read the national feed `rss_india.xml`, which carries every state's warnings).
STATES: tuple[str, ...] = (
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
    "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
)  # fmt: skip
STATE_FEEDS: dict[str, str] = {"Kerala": "kerala", "Karnataka": "karnataka"}
# District headquarters, rounded to 0.01 degrees (public geography; approximate). Elsewhere he
# types his district centre's coordinates.
DISTRICT_CENTRES: dict[tuple[str, str], tuple[float, float]] = {
    ("Kerala", "thiruvananthapuram"): (8.52, 76.94), ("Kerala", "kollam"): (8.89, 76.61),
    ("Kerala", "pathanamthitta"): (9.26, 76.78), ("Kerala", "alappuzha"): (9.50, 76.34),
    ("Kerala", "kottayam"): (9.59, 76.52), ("Kerala", "idukki"): (9.85, 76.94),
    ("Kerala", "ernakulam"): (9.98, 76.28), ("Kerala", "thrissur"): (10.52, 76.21),
    ("Kerala", "palakkad"): (10.78, 76.65), ("Kerala", "malappuram"): (11.07, 76.07),
    ("Kerala", "kozhikode"): (11.26, 75.78), ("Kerala", "wayanad"): (11.61, 76.08),
    ("Kerala", "kannur"): (11.87, 75.37), ("Kerala", "kasaragod"): (12.50, 74.99),
}  # fmt: skip


def clean_text(value: object, limit: int) -> str:
    """One line of plain text (control characters out, spaces collapsed), cut to `limit`."""
    if not isinstance(value, str):
        return ""
    one = " ".join("".join(c if c >= " " and c != "\x7f" else " " for c in value).split())
    return one if len(one) <= limit else one[: limit - 1].rstrip() + "…"


def clean_label(value: object, *, limit: int = LABEL_MAX, what: str = "A label") -> str:
    """His own words for a label: required, one line, at most `limit` characters."""
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text.")
    one = " ".join("".join(c if c >= " " and c != "\x7f" else " " for c in value).split())
    if not one:
        raise ValueError(f"{what} can't be empty.")
    if len(one) > limit:
        raise ValueError(f"{what} is at most {limit} characters.")
    return one


def _hhmm(value: str) -> str:
    if not _HHMM.match(value):
        raise ValueError("A time is HH:MM, such as 09:00.")
    return value


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Chore(_Model):
    id: str = Field(pattern=_ID)
    label: str
    freq: Freq
    days: tuple[int, ...] = ()  # weekly: 0 = Monday ... 6 = Sunday
    every: int | None = None  # every N days (2-90), counted from `start`
    start: str = Field(pattern=_DAY)
    at: str = "09:00"
    members: tuple[str, ...] = ()
    turn: int = Field(default=0, ge=0)
    turn_day: str | None = Field(default=None, pattern=_DAY)
    last_done: str | None = Field(default=None, pattern=_DAY)

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        return clean_label(v, what="A chore")

    @field_validator("at")
    @classmethod
    def _at(cls, v: str) -> str:
        return _hhmm(v)

    @field_validator("members")
    @classmethod
    def _members(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) > MAX_MEMBERS:
            raise ValueError(f"A rota has at most {MAX_MEMBERS} people.")
        return tuple(clean_label(m, limit=MEMBER_MAX, what="A rota label") for m in v)

    @model_validator(mode="after")
    def _shape(self) -> Chore:
        if self.freq == "weekly" and (
            not self.days or sorted(set(self.days)) != list(self.days) or self.days[-1] > 6
        ):
            raise ValueError("A weekly chore needs its days, Monday to Sunday.")
        if self.freq == "every" and not (
            self.every is not None and 2 <= self.every <= MAX_EVERY_DAYS
        ):
            raise ValueError(f"'Every N days' is 2 to {MAX_EVERY_DAYS} days.")
        if self.members and self.turn >= len(self.members):
            raise ValueError("The turn must be one of the rota.")
        return self


class Upkeep(_Model):
    id: str = Field(pattern=_ID)
    label: str
    every: int = Field(ge=1)
    unit: Unit = "days"
    last_done: str = Field(pattern=_DAY)
    lead: int = Field(default=7, ge=0, le=MAX_LEAD_DAYS)

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        return clean_label(v, what="An upkeep item")

    @model_validator(mode="after")
    def _span(self) -> Upkeep:
        top = MAX_UPKEEP_DAYS if self.unit == "days" else MAX_UPKEEP_MONTHS
        if self.every > top:
            raise ValueError(f"At most every {top} {self.unit}.")
        return self


class Thresholds(_Model):
    """D12's defaults (IMD's "heavy rain" for the day); he may change them."""

    rain_hour_mm: float = Field(default=15.0, ge=5.0, le=100.0)
    rain_day_mm: float = Field(default=64.5, ge=20.0, le=300.0)
    feels_c: float = Field(default=40.0, ge=30.0, le=55.0)
    gust_kmh: float = Field(default=50.0, ge=30.0, le=150.0)


class Place(_Model):
    district: str
    state: str
    lat: float | None = Field(default=None, ge=6.0, le=38.0)  # India's mainland and islands
    lon: float | None = Field(default=None, ge=67.0, le=98.0)
    lgd: str | None = Field(default=None, pattern=r"^\d{1,6}$")  # LGD district code (optional)

    @field_validator("district")
    @classmethod
    def _district(cls, v: str) -> str:
        one = clean_label(v, what="Your district")
        if not _PLACE_WORD.match(one):
            raise ValueError("Type your district's name in English letters, such as Ernakulam.")
        return one

    @field_validator("state")
    @classmethod
    def _state(cls, v: str) -> str:
        if v not in STATES:
            raise ValueError("Pick your state from the list.")
        return v

    @field_validator("lat", "lon")
    @classmethod
    def _round(cls, v: float | None) -> float | None:
        return None if v is None else round(v, 2)

    @model_validator(mode="after")
    def _pair(self) -> Place:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Give both the latitude and the longitude, or neither.")
        return self

    def point(self) -> tuple[float, float] | None:
        """His rounded point: his own, else the district centre JARVIS knows, else None."""
        if self.lat is not None and self.lon is not None:
            return self.lat, self.lon
        return DISTRICT_CENTRES.get((self.state, self.district.lower()))

    def feed(self) -> str:
        return STATE_FEEDS.get(self.state, "india")


class FeedState(_Model):
    checked_at: str | None = None
    next_at: str | None = None
    ok_at: str | None = None
    fail_since: str | None = None


class WeatherSummary(_Model):
    day: str = Field(pattern=_DAY)
    t_max: float | None = None
    rain_from: str | None = None  # HH:MM local, the first hour rain is likely today
    at: str


class WeatherState(FeedState):
    summary: WeatherSummary | None = None


class Warning(_Model):
    """A SACHET warning still active for his district. `headline` / `instruction` are outside
    text (shown only in the panel, fenced); the alert text is built from `event` (a fixed word)."""

    ident: str
    root: str
    kind: str
    event: str
    until: str | None = None
    at: str
    headline: str = Field(default="", max_length=OUTSIDE_TEXT_MAX)
    instruction: str = Field(default="", max_length=OUTSIDE_TEXT_MAX)


class SachetState(FeedState):
    feed: str | None = None
    etag: str | None = Field(default=None, max_length=200)
    seen: tuple[str, ...] = ()
    queue: tuple[str, ...] = ()
    warnings: tuple[Warning, ...] = ()


class BreachState(_Model):
    checked_at: str | None = None
    last_day: str | None = Field(default=None, pattern=_DAY)
    notices: int = Field(default=0, ge=0)


class Outside(_Model):
    place: Place | None = None
    thresholds: Thresholds = Field(default_factory=Thresholds)
    breach_on: bool = False
    weather: WeatherState = Field(default_factory=WeatherState)
    sachet: SachetState = Field(default_factory=SachetState)
    breach: BreachState = Field(default_factory=BreachState)


__all__ = [
    "DISTRICT_CENTRES",
    "LABEL_MAX",
    "MAX_CHORES",
    "MAX_MEMBERS",
    "MAX_QUEUE",
    "MAX_SEEN",
    "MAX_UPKEEP",
    "MAX_WARNINGS",
    "MEMBER_MAX",
    "OUTSIDE_TEXT_MAX",
    "STATES",
    "STATE_FEEDS",
    "WEEKDAYS",
    "BreachState",
    "Chore",
    "FeedState",
    "Outside",
    "Place",
    "SachetState",
    "Thresholds",
    "Upkeep",
    "Warning",
    "WeatherState",
    "WeatherSummary",
    "clean_label",
    "clean_text",
]
