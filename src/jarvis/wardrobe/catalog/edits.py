# src/jarvis/wardrobe/catalog/edits.py
"""What a new piece and an edit may say (docs/plans/r13-wardrobe.md D2, D7, D10; INV-04, 09, 10).
Pure: no I/O, no clock (times are passed in).

- `NewPiece` / `new_record`: a type from the workbook's lists, `unknown` or one of his own; the
  category follows the type; private by default for underwear, vests, undershirts and thermals
  (D10); his label <= 60 characters, one line, never an ID or a password (the memory filter).
- `Edit` / `apply_edit`: a type change keeps the id; a change INTO a private-by-default type asks
  "Make it private?" until he answers; a colour or pattern he sets himself is locked, a suggestion
  (the phone's colour, the AI's tag) never overwrites a locked field and never locks one (INV-09);
  a label field read off a photo (`read=True`) is kept only in its parsed form and stays
  unverified until he types or confirms it; raw OCR text is refused, never stored (INV-10).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from jarvis.recall.sensitive import sensitive_reason
from jarvis.tools.card import one_line, strip_invisible
from jarvis.wardrobe.model import (
    BRAND_RE,
    CARE_WORDS,
    COLOURS,
    FABRICS,
    FEATURES,
    LABEL_MAX,
    OCCASIONS,
    PATTERNS,
    PRIVATE_BY_DEFAULT,
    SIZE_RE,
    TYPE_WORD,
    TYPES,
    UNKNOWN_TYPE,
    WEATHER,
    Piece,
    Verified,
)
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import STATED_CHOICES, State

ASK_PRIVATE = "Make it private? Private pieces are counted only, never named outside this tab."
SENSITIVE = "IDs go in the Vault; JARVIS doesn't keep passwords or card numbers."
NOT_A_TYPE = "That isn't a type I know: pick one from the list or add your own type first."
NOT_FIXED = "{what} must come from the fixed list."
NOT_PARSED = "That label text couldn't be read as a {what}: type it instead."
_FABRIC = re.compile(r"^([a-z]+)(?: (\d{1,3})%)?$")
LOCKABLE = ("type", "colour", "second", "pattern", "features", "formality", "label")


@dataclass(frozen=True)
class NewPiece:
    type: str
    label: str = ""
    colour: str | None = None
    pattern: str | None = None
    private: bool | None = None  # None: the type's default (D10)
    place: str | None = None  # a place id
    state: State | None = None  # registered as (Ready unless he says)
    client_id: str | None = None  # the phone's box id: a retry of one box is one piece (INV-08)
    features: Mapping[str, str] = field(default_factory=dict)
    formality: int | None = None
    occasions: tuple[str, ...] = ()
    weather: tuple[str, ...] = ()
    mess_ok: bool = False
    delicate: bool = False
    typed: bool = True  # he typed the label on an untainted turn: it vouches (D18)


@dataclass(frozen=True)
class Edit:
    type: str | None = None
    label: str | None = None
    colour: str | None = None
    second: str | None = None
    pattern: str | None = None
    features: Mapping[str, str] | None = None
    formality: int | None = None
    occasions: tuple[str, ...] | None = None
    weather: tuple[str, ...] | None = None
    mess_ok: bool | None = None
    delicate: bool | None = None
    private: bool | None = None
    size: str | None = None
    brand: str | None = None
    fabric: tuple[str, ...] | None = None
    care: tuple[str, ...] | None = None
    read: bool = False  # the label fields came off a photo: unverified (INV-10)
    verify: tuple[str, ...] = ()  # label fields he confirms as read: size, brand, fabric, care
    lock: tuple[str, ...] = ()
    unlock: tuple[str, ...] = ()
    suggested: bool = False  # the phone's colour or the AI's tag: never over a lock (INV-09)


def clean_label(text: object, limit: int = LABEL_MAX) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        raise Refused("A label is a few words of your own.")
    words = one_line(strip_invisible(text), limit + 1).strip()
    if len(words) > limit:
        raise Refused(f"A label is at most {limit} characters.")
    if words and sensitive_reason(words):
        raise Refused(SENSITIVE)
    return words


def category_of(type_: str, custom: Sequence[str]) -> str:
    found = next((c for c, ts in TYPES.items() if type_ in ts), None)
    if found is not None:
        return found
    if type_ == UNKNOWN_TYPE or (type_ in custom and TYPE_WORD.match(type_)):
        return "activity"
    raise Refused(NOT_A_TYPE)


def _fixed(values: Sequence[str] | None, allowed: Sequence[str], what: str) -> tuple[str, ...]:
    out = tuple(values or ())
    if any(v not in allowed for v in out):
        raise Refused(NOT_FIXED.format(what=what))
    return out


def _one(value: str | None, allowed: Sequence[str], what: str) -> str | None:
    if value is not None and value not in allowed:
        raise Refused(NOT_FIXED.format(what=what))
    return value


def _features(found: Mapping[str, str] | None) -> dict[str, str]:
    out = dict(found or {})
    if any(FEATURES.get(k) is None or v not in FEATURES[k] for k, v in out.items()):
        raise Refused(NOT_FIXED.format(what="A feature"))
    return out


def new_record(spec: NewPiece, pid: str, custom: Sequence[str], now: datetime) -> Piece:
    if spec.state is not None and spec.state not in STATED_CHOICES["registered"]:
        raise Refused("A new piece can start Ready, In use, In laundry or in review.")
    category = category_of(spec.type, custom)
    private = spec.private if spec.private is not None else spec.type in PRIVATE_BY_DEFAULT
    data: dict[str, Any] = {
        "id": pid, "category": category, "type": spec.type, "label": clean_label(spec.label),
        "colour": _one(spec.colour, COLOURS, "A colour"),
        "pattern": _one(spec.pattern, PATTERNS, "A pattern"),
        "features": _features(spec.features), "formality": spec.formality,
        "occasions": _fixed(spec.occasions, OCCASIONS, "An occasion"),
        "weather": _fixed(spec.weather, WEATHER, "A weather tag"),
        "mess_ok": spec.mess_ok, "delicate": spec.delicate, "private": private,
        "place": spec.place, "created_at": now, "updated_at": now,
        "locked": ("label",) if spec.label and spec.typed else (),
    }  # fmt: skip
    try:
        return Piece.model_validate(data)
    except ValueError:
        raise Refused("That piece couldn't be saved as it is: check its fields.") from None


# ---- label fields (INV-10): parsed forms only -------------------------------------------------
def _size(text: str) -> str:
    v = text.strip().upper()
    if not SIZE_RE.match(v):
        raise Refused(NOT_PARSED.format(what="size"))
    return v


def _brand(text: str) -> str:
    v = text.strip()
    if not BRAND_RE.match(v):
        raise Refused(NOT_PARSED.format(what="brand"))
    return v


def _fabric(text: str) -> str:
    m = _FABRIC.match(text.strip().lower())
    if not m or m.group(1) not in FABRICS or (m.group(2) and int(m.group(2)) > 100):
        raise Refused(NOT_PARSED.format(what="fabric"))
    return m.group(0)


def _care(text: str) -> str:
    v = text.strip().lower()
    if v not in CARE_WORDS:
        raise Refused(NOT_PARSED.format(what="care word"))
    return v


def _verified(value: str, ok: bool) -> Verified:
    return Verified(v=value, ok=ok)


def _label_fields(p: Piece, e: Edit) -> dict[str, Any]:
    ok = not e.read  # typed by him: verified; read off a photo: not until he confirms
    out: dict[str, Any] = {}
    if e.size is not None:
        out["size"] = _verified(_size(e.size), ok)
    if e.brand is not None:
        out["brand"] = _verified(_brand(e.brand), ok)
    if e.fabric is not None:
        out["fabric"] = tuple(_verified(_fabric(f), ok) for f in e.fabric[:4])
    if e.care is not None:
        out["care"] = tuple(_verified(_care(c), ok) for c in e.care[:8])
    for name in e.verify:  # he confirms what was read
        current = out.get(name, getattr(p, name, None))
        if isinstance(current, Verified):
            out[name] = current.model_copy(update={"ok": True})
        elif isinstance(current, tuple):
            out[name] = tuple(v.model_copy(update={"ok": True}) for v in current)
    return out


# ---- the edit ---------------------------------------------------------------------------------
def _attributes(e: Edit) -> dict[str, Any]:
    out: dict[str, Any] = {
        "colour": _one(e.colour, COLOURS, "A colour"),
        "second": _one(e.second, COLOURS, "A colour"),
        "pattern": _one(e.pattern, PATTERNS, "A pattern"), "formality": e.formality,
        "mess_ok": e.mess_ok, "delicate": e.delicate,
    }  # fmt: skip
    if e.features is not None:
        out["features"] = _features(e.features)
    if e.occasions is not None:
        out["occasions"] = _fixed(e.occasions, OCCASIONS, "An occasion")
    if e.weather is not None:
        out["weather"] = _fixed(e.weather, WEATHER, "A weather tag")
    if e.label is not None:
        out["label"] = clean_label(e.label)
    return {k: v for k, v in out.items() if v is not None}


def apply_edit(p: Piece, e: Edit, custom: Sequence[str]) -> Piece | str:
    """The edited record, or the question to ask first (ASK_PRIVATE)."""
    update = _attributes(e)
    if e.type is not None and e.type != p.type:
        update["category"], update["type"] = category_of(e.type, custom), e.type
        if e.type in PRIVATE_BY_DEFAULT and not p.private and e.private is None:
            return ASK_PRIVATE
    locked = set(p.locked) - set(e.unlock)
    if e.suggested:  # never over a lock, never a lock of its own
        update = {k: v for k, v in update.items() if k not in locked}
    else:
        locked |= {k for k in ("colour", "second", "pattern") if k in update}
    locked |= {k for k in e.lock if k in LOCKABLE}
    update |= _label_fields(p, e)
    if e.private is not None:
        update["private"] = e.private
    update["locked"] = tuple(sorted(locked))
    try:
        return Piece.model_validate({**p.model_dump(), **update})
    except ValueError:
        raise Refused("That change couldn't be saved as it is: check its fields.") from None


__all__ = [
    "ASK_PRIVATE",
    "LOCKABLE",
    "SENSITIVE",
    "Edit",
    "NewPiece",
    "apply_edit",
    "category_of",
    "clean_label",
    "new_record",
]
