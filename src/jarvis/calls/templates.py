# src/jarvis/calls/templates.py
"""Ready call templates (R18 A1; docs/plans/r18-calls.md section 2, rows 195-197; BUILD-BRIEF.md
"Rows"; Layer 5 Communication).

A template only writes a DRAFT (`calls.tools.PlaceArgs`): the card is built, estimated and
checked like any other (`cards.CardBuilder`) and every call is placed only after his tap on it.
Nothing here places, schedules or repeats a call.

- `laundry_pickup` (rows 195-196): book a pickup inside the windows he gives; the name to give;
  the address the shop has on file; no payment. In Malayalam first, then English, unless he
  chooses other languages.
- `laundry_status` (row 197): ask whether the laundry is ready and when it can come back; it
  may agree to a delivery time only inside the windows he gives (if any).
- `appointment`: book an appointment (a clinic, a service centre) inside his windows, giving his
  name (and the number he chooses) and the reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jarvis.calls.models import (
    E164,
    NAME_MAX,
    PURPOSE_MAX,
    Booking,
    TimeWindow,
    check_languages,
)
from jarvis.calls.tools import PlaceArgs
from jarvis.tools.card import one_line

LAUNDRY_PICKUP, LAUNDRY_STATUS, APPOINTMENT = "laundry_pickup", "laundry_status", "appointment"
LAUNDRY_LANGUAGES = ("ml-IN", "en-IN")
ORDER_MAX = 80
MSG_UNKNOWN = "That call template doesn't exist."
MSG_FIELDS = "Check the template's fields: {words}"


class TemplateRefused(ValueError):
    def __init__(self, words: str) -> None:
        super().__init__(words)
        self.code, self.words = "template", words


class _Fields(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str | None = Field(default=None, pattern=E164)
    contact: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    languages: tuple[str, ...] | None = None
    max_minutes: int | None = Field(default=None, ge=1, le=30)

    @model_validator(mode="after")
    def _who(self) -> _Fields:
        if not self.number and not self.contact:
            raise ValueError("give the number or the saved contact's name")
        if self.languages is not None:
            check_languages(self.languages)
        return self


class LaundryPickup(_Fields):
    windows: tuple[TimeWindow, ...] = Field(min_length=1, max_length=6)
    give_name: str = Field(min_length=1, max_length=NAME_MAX)
    items: int | None = Field(default=None, ge=1, le=200)


class LaundryStatus(_Fields):
    order: str | None = Field(default=None, min_length=1, max_length=ORDER_MAX)
    give_name: str = Field(min_length=1, max_length=NAME_MAX)
    windows: tuple[TimeWindow, ...] = Field(default=(), max_length=6)  # a delivery time, if any


class Appointment(_Fields):
    place: str = Field(min_length=1, max_length=NAME_MAX)
    reason: str = Field(min_length=1, max_length=PURPOSE_MAX - 80)
    windows: tuple[TimeWindow, ...] = Field(min_length=1, max_length=6)
    give_name: str = Field(min_length=1, max_length=NAME_MAX)
    give_number: str | None = Field(default=None, pattern=E164)
    duration_minutes: int = Field(default=30, ge=5, le=480)


def _who(f: _Fields) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if f.number:
        out["number"] = f.number
    if f.contact:
        out["contact"] = f.contact
    if f.max_minutes:
        out["max_minutes"] = f.max_minutes
    return out


def _laundry_pickup(f: LaundryPickup) -> dict[str, Any]:
    items = f" of {f.items} items" if f.items else ""
    name = one_line(f.give_name, NAME_MAX)
    return {
        "purpose": f"Book a laundry pickup{items}",
        "may_say": [
            f"The pickup is for {name}.",
            "The pickup address is the one the shop has on file.",
        ],
        "may_agree": ["A pickup time inside the given windows."],
        "languages": list(f.languages or LAUNDRY_LANGUAGES),
        "booking": Booking(
            windows=f.windows, give_name=name, reason="Laundry pickup", duration_minutes=30
        ).model_dump(mode="json"),
    }


def _laundry_status(f: LaundryStatus) -> dict[str, Any]:
    order = one_line(f.order or "", ORDER_MAX)
    name = one_line(f.give_name, NAME_MAX)
    out: dict[str, Any] = {
        "purpose": "Ask whether the laundry is ready and when it can be delivered",
        "may_say": [f"The laundry is under the name {name}."]
        + ([f"The order: {order}."] if order else []),
        "may_agree": [],
        "languages": list(f.languages or LAUNDRY_LANGUAGES),
    }
    if f.windows:
        out["may_agree"] = ["A delivery time inside the given windows."]
        out["booking"] = Booking(
            windows=f.windows, give_name=name, reason="Laundry delivery", duration_minutes=30
        ).model_dump(mode="json")
    return out


def _appointment(f: Appointment) -> dict[str, Any]:
    place, reason = one_line(f.place, NAME_MAX), one_line(f.reason, PURPOSE_MAX - 80)
    return {
        "purpose": f"Book an appointment at {place}: {reason}",
        "may_say": [
            f"The appointment is for {one_line(f.give_name, NAME_MAX)}.",
            f"The reason: {reason}.",
        ],
        "may_agree": ["An appointment time inside the given windows."],
        "languages": list(f.languages or ("en-IN",)),
        "booking": Booking(
            windows=f.windows,
            give_name=one_line(f.give_name, NAME_MAX),
            give_number=f.give_number,
            reason=f"Appointment at {place}",
            duration_minutes=f.duration_minutes,
        ).model_dump(mode="json"),
    }


_TEMPLATES: dict[str, tuple[type[_Fields], Any, str]] = {
    LAUNDRY_PICKUP: (LaundryPickup, _laundry_pickup, "Book a laundry pickup"),
    LAUNDRY_STATUS: (LaundryStatus, _laundry_status, "Ask about the laundry"),
    APPOINTMENT: (Appointment, _appointment, "Book an appointment"),
}
NAMES = tuple(_TEMPLATES)


def is_template(name: str) -> bool:
    return name in _TEMPLATES


def catalogue() -> list[dict[str, Any]]:
    """The templates for the Calls panel: name, title and the fields each takes."""
    return [
        {"name": n, "title": t, "fields": sorted(model.model_fields)}
        for n, (model, _, t) in _TEMPLATES.items()
    ]


def draft_from(name: str, fields: Mapping[str, Any]) -> PlaceArgs:
    """The template's draft for these fields, or TemplateRefused in plain words."""
    found = _TEMPLATES.get(name)
    if found is None:
        raise TemplateRefused(MSG_UNKNOWN)
    model, write, _ = found
    try:
        f = model.model_validate(dict(fields))
        return PlaceArgs.model_validate(_who(f) | write(f) | {"template": name})
    except ValidationError as exc:
        names = sorted({".".join(str(x) for x in e["loc"]) for e in exc.errors() if e["loc"]})
        custom = [str(e.get("ctx", {}).get("error", "")) for e in exc.errors() if not e["loc"]]
        words = "; ".join(w for w in custom if w) or ", ".join(names) or "the fields"
        raise TemplateRefused(MSG_FIELDS.format(words=words[:160])) from None


__all__ = [
    "APPOINTMENT",
    "LAUNDRY_LANGUAGES",
    "LAUNDRY_PICKUP",
    "LAUNDRY_STATUS",
    "NAMES",
    "Appointment",
    "LaundryPickup",
    "LaundryStatus",
    "TemplateRefused",
    "catalogue",
    "draft_from",
    "is_template",
]
