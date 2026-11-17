# src/jarvis/wardrobe/tryon/model.py
"""R13.1's fixed tables and records (docs/plans/r13-1-try-on.md D4-D7, D13-D15, "Data model"):
I0's, the ONE source (the console gets them in the look; no part keeps a copy).

- Measurements (D4): six, whole cm, preview v2's ranges and its sample (172, 44, 96, 82, 96, 79);
  `range_words` refuse a value in words; `estimated(height)` fills what he didn't type from the
  sample's proportions; `Body` is one version (typed or estimated per field).
- Templates (D5): `TEMPLATE_OF` a type, `VARIANTS`, `TEMPLATE_SLOT`, `GARMENTS` (what See it on
  me may send), `useful_views` (the views worth asking for), `PALETTE` (the 18 colours and
  multicolour as RGB; no colour is mid-grey). Every template is "Approximate".
- The words the console and the share caption use (readiness, covered, the picture's label).
- Ids (a picture `tp_` + 12 hex, a request `tq_` + 16 hex, a saved comparison `tc_` + 8 hex),
  the collections and the AAD of every sealed document. No clock: callers pass times in.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from jarvis.wardrobe.model import TYPES, View
from jarvis.wardrobe.states import State

# ---- measurements (D4) -------------------------------------------------------------------------
Measure = Literal["height", "shoulders", "chest", "waist", "hips", "inseam"]
MEASURES: tuple[Measure, ...] = get_args(Measure)
RANGES: Mapping[Measure, tuple[int, int]] = {
    "height": (150, 195),
    "shoulders": (36, 54),
    "chest": (76, 124),
    "waist": (62, 120),
    "hips": (78, 126),
    "inseam": (66, 92),
}
SAMPLE: Mapping[Measure, int] = {
    "height": 172, "shoulders": 44, "chest": 96, "waist": 82, "hips": 96, "inseam": 79,
}  # fmt: skip
_RANGE_WORDS: Mapping[Measure, str] = {
    "height": "The figure can be {lo} to {hi} cm tall",
    "shoulders": "Shoulder width can be {lo} to {hi} cm",
    "chest": "The chest can be {lo} to {hi} cm",
    "waist": "The waist can be {lo} to {hi} cm",
    "hips": "The hips can be {lo} to {hi} cm",
    "inseam": "The inseam can be {lo} to {hi} cm",
}
ESTIMATED = "Estimated from your measurements"
ESTIMATE_NOTE = (
    "Each measurement comes back within about half a centimetre; changing several can move "
    "another by up to about 3 cm."
)
NO_FIGURE = "No figure yet: type your measurements."
EARLIER_MAX = 5  # versions kept besides the current one and a draft


def range_words(m: Measure) -> str:
    lo, hi = RANGES[m]
    return _RANGE_WORDS[m].format(lo=lo, hi=hi)


def in_range(m: Measure, value: int) -> bool:
    lo, hi = RANGES[m]
    return not isinstance(value, bool) and isinstance(value, int) and lo <= value <= hi


def estimated(height: int) -> dict[Measure, int]:
    """Every measurement from his height with the sample's proportions, inside its range."""
    out: dict[Measure, int] = {}
    for m in MEASURES:
        lo, hi = RANGES[m]
        out[m] = height if m == "height" else round(SAMPLE[m] * height / SAMPLE["height"])
        out[m] = min(hi, max(lo, out[m]))
    return out


class Body(BaseModel):
    """One version of his measurements; `typed` names the ones he typed (the rest estimated)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    height: int
    shoulders: int
    chest: int
    waist: int
    hips: int
    inseam: int
    typed: tuple[Measure, ...] = ()
    at: datetime

    @model_validator(mode="after")
    def _ranges(self) -> Body:
        for m in MEASURES:
            if not in_range(m, getattr(self, m)):
                raise ValueError(range_words(m))
        if len(set(self.typed)) != len(self.typed):
            raise ValueError("a measurement is typed once")
        return self

    def values(self) -> dict[Measure, int]:
        return {m: getattr(self, m) for m in MEASURES}


# ---- garment templates, colours and views (D5, D6, D13.1) ---------------------------------------
Template = Literal[
    "shirt", "tee", "kurta", "trousers", "shorts", "wrap", "jacket", "shoe", "sandal", "belt",
    "watch", "socks",
]  # fmt: skip
TEMPLATES: tuple[Template, ...] = get_args(Template)
TEMPLATE_OF: Mapping[str, Template] = {
    "shirt": "shirt",
    **dict.fromkeys(("t_shirt", "polo", "top"), "tee"),
    "kurta": "kurta",
    **dict.fromkeys(("trousers", "chinos", "jeans", "joggers", "pyjama"), "trousers"),
    "shorts": "shorts",
    **dict.fromkeys(("mundu", "dhoti"), "wrap"),
    **dict.fromkeys(
        ("blazer", "jacket", "coat", "hoodie", "sweater", "rainwear", "festive_layer"), "jacket"
    ),
    **dict.fromkeys(("dress_shoe", "boot", "sneaker"), "shoe"),
    **dict.fromkeys(("sandal", "slipper"), "sandal"),
    "belt": "belt",
    "watch": "watch",
    "sock": "socks",
}
VARIANTS: Mapping[Template, tuple[str, ...]] = {
    "shirt": ("tucked", "untucked"),
    "tee": ("tucked", "untucked"),
    "kurta": ("knee",),
    "wrap": ("ankle",),
    "jacket": ("open", "closed"),
}
TEMPLATE_SLOT: Mapping[Template, str] = {
    **dict.fromkeys(("shirt", "tee", "kurta"), "top"),
    **dict.fromkeys(("trousers", "shorts", "wrap"), "bottom"),
    "jacket": "outer",
    **dict.fromkeys(("shoe", "sandal"), "shoes"),
    "belt": "belt",
    "watch": "watch",
    "socks": "socks",
}
GARMENTS: frozenset[Template] = frozenset(
    {"shirt", "tee", "kurta", "trousers", "shorts", "wrap", "jacket"}
)  # the only templates See it on me may send (shoes, belt, watch and socks never)
TUCKABLE: frozenset[Template] = frozenset({"shirt", "tee"})
TUCKED_CODES = frozenset({"business_formal", "business_casual"})  # tucked by default (D6)
REMOVABLE_SLOTS = frozenset({"outer", "belt", "watch", "socks"})  # "Remove" (D7)
PRIVATE_SLOTS = frozenset({"base", "underwear"})  # never drawn as themselves (D6)
Layers = Literal["all", "no_outer", "base"]
LAYERS: tuple[Layers, ...] = get_args(Layers)
VIEW_YAW: Mapping[str, int] = {"front": 0, "side": 90, "back": 180}  # degrees (AVT-02)
BACK_USEFUL = frozenset({"tops", "outerwear", "traditional"})  # back views worth asking for
PALETTE: Mapping[str, tuple[int, int, int]] = {
    "black": (28, 28, 30), "white": (240, 240, 236), "grey": (140, 140, 144),
    "charcoal": (64, 66, 70), "navy": (30, 42, 80), "blue": (40, 90, 170),
    "light_blue": (150, 190, 225), "green": (40, 120, 60), "olive": (110, 110, 50),
    "yellow": (230, 200, 60), "orange": (230, 130, 40), "red": (190, 40, 40),
    "maroon": (110, 30, 40), "pink": (230, 150, 180), "purple": (110, 60, 140),
    "brown": (110, 75, 50), "beige": (215, 200, 170), "khaki": (190, 170, 120),
    "multicolour": (150, 130, 160),
}  # fmt: skip
NO_COLOUR_RGB = (128, 128, 128)  # mid-grey, with the card "no colour set"
APPROXIMATE = "Approximate"
Approx = Literal["template", "texture", "colour"]  # what is an estimate on a slot (AVT-06/08)


def template_of(type_: str) -> Template | None:
    """The default template for a type; None: an image card only (tie, cap, his own types...)."""
    return TEMPLATE_OF.get(type_)


def templates_for(slot: str) -> tuple[Template, ...]:
    """The templates he may pick for a slot (another of the same slot, or "image card only")."""
    return tuple(t for t in TEMPLATES if TEMPLATE_SLOT[t] == slot)


def category_of(type_: str) -> str | None:
    return next((c for c, types in TYPES.items() if type_ in types), None)


def useful_views(type_: str) -> tuple[View, ...]:
    """Front for every garment; back for tops, outerwear and traditional (AVT-04)."""
    if template_of(type_) is None:
        return ()
    return ("front", "back") if category_of(type_) in BACK_USEFUL else ("front",)


def rgb_of(colour: str | None) -> tuple[int, int, int]:
    return PALETTE.get(colour or "", NO_COLOUR_RGB)


# ---- words --------------------------------------------------------------------------------------
READY = "Ready"
COVERED = "Base layer (covered)"
ONE_SHOE = "Draft: one shoe missing"
DRAFT_WORDS: Mapping[State, str] = {
    "in_use": "Draft: in use",
    "in_laundry": "Draft: in the laundry",
    "washing": "Draft: in the laundry",
    "drying": "Draft: in the laundry",
    "needs_prep": "Draft: needs pressing",
    "with_provider": "Draft: at the laundry shop",
    "needs_repair": "Draft: needs a repair",
    "review": "Draft: needs a quick check",
    "archived": "Draft: archived",
}
GENERATED = "Generated 2D style preview — not a photo; the fit is not exact"
CREDENTIALS = "Google adds Content Credentials (C2PA)"
NOT_IN_PICTURE = "Not in the picture"
YES = "YES"  # his consent, typed exactly (letters only, trimmed)


def reserved_words(event: str) -> str:
    """ "Draft: reserved for your 18:00 event" (`event` from R13's `texts.event_words`)."""
    return f"Draft: reserved for {event}"


# ---- ids, collections, sealing (D14, "Data model") -----------------------------------------------
PICTURE_ID = r"^tp_[0-9a-f]{12}$"
REQUEST_ID = r"^tq_[0-9a-f]{16}$"
SAVED_ID = r"^tc_[0-9a-f]{8}$"
TRYON, PERSON, CONSENT = "tryon", "tryon_person", "tryon_consent"
PICTURE, SPEND = "tryon_picture", "tryon_spend"
PURPOSE, PHOTO_PURPOSE = "tryon", "tryon_photos"  # keyring purposes
SAVED_MAX, OPTIONS_MAX, KEPT_MAX, LISTED_MAX, DONE_MAX = 10, 12, 24, 50, 50
PICTURE_KEEP_DAYS = 30  # owner question 3 (17 Nov 2026): 30 days unless Keep; `tryon_keep_days`
TRYON_DOC_MAX_KB = 200
PHOTO_SIDE_MAX = 1568
ANSWER_MAX_BYTES = 16 * 1024 * 1024  # a picture in Google's answer
PRESSES_A_MINUTE = 6  # POST /v1/seeme/pictures
BUSY_MINUTES, SETTLE_HOURS, SPEND_KEEP_MONTHS = 10, 1, 13
CALL_DEADLINE_S = 120.0


def new_picture_id() -> str:
    return "tp_" + secrets.token_hex(6)


def new_saved_id() -> str:
    return "tc_" + secrets.token_hex(4)


def aad_tryon(uid: str) -> str:
    return f"tryon/{uid}/v1"


def aad_person(uid: str) -> str:
    return f"tryon/person/{uid}/v1"


def aad_consent(uid: str) -> str:
    return f"tryon/consent/{uid}/v1"


def aad_picture(uid: str, picture: str) -> str:
    return f"tryon/picture/{uid}/{picture}/v1"


__all__ = [
    "ANSWER_MAX_BYTES",
    "APPROXIMATE",
    "BACK_USEFUL",
    "BUSY_MINUTES",
    "CALL_DEADLINE_S",
    "CONSENT",
    "COVERED",
    "CREDENTIALS",
    "DONE_MAX",
    "DRAFT_WORDS",
    "EARLIER_MAX",
    "ESTIMATED",
    "ESTIMATE_NOTE",
    "GARMENTS",
    "GENERATED",
    "KEPT_MAX",
    "LAYERS",
    "LISTED_MAX",
    "MEASURES",
    "NOT_IN_PICTURE",
    "NO_COLOUR_RGB",
    "NO_FIGURE",
    "ONE_SHOE",
    "OPTIONS_MAX",
    "PALETTE",
    "PERSON",
    "PHOTO_PURPOSE",
    "PHOTO_SIDE_MAX",
    "PICTURE_KEEP_DAYS",
    "PICTURE",
    "PICTURE_ID",
    "PRESSES_A_MINUTE",
    "PRIVATE_SLOTS",
    "PURPOSE",
    "RANGES",
    "READY",
    "REMOVABLE_SLOTS",
    "REQUEST_ID",
    "SAMPLE",
    "SAVED_ID",
    "SAVED_MAX",
    "SETTLE_HOURS",
    "SPEND",
    "SPEND_KEEP_MONTHS",
    "TEMPLATES",
    "TEMPLATE_OF",
    "TEMPLATE_SLOT",
    "TRYON",
    "TRYON_DOC_MAX_KB",
    "TUCKABLE",
    "TUCKED_CODES",
    "VARIANTS",
    "VIEW_YAW",
    "YES",
    "Approx",
    "Body",
    "Layers",
    "Measure",
    "Template",
    "aad_consent",
    "aad_person",
    "aad_picture",
    "aad_tryon",
    "category_of",
    "estimated",
    "in_range",
    "new_picture_id",
    "new_saved_id",
    "range_words",
    "reserved_words",
    "rgb_of",
    "template_of",
    "templates_for",
    "useful_views",
]
