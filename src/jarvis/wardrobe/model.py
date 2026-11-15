# src/jarvis/wardrobe/model.py
"""R13 D2, D4 (docs/plans/r13-wardrobe.md): the wardrobe's records, frozen, JSON in and out.

One id per physical piece (`wi_` + 12 hex); a pair (`wp_`), a set (`ws_`), a place (`wl_`), a
photo (`wh_`), an event (`we_` + 20 hex) and a QR label (8 characters of lower-case base32, printed
with its number; the QR's payload is `jw1:<code>`). Every record is stored with SHORT keys (its
field aliases: the sealed index must stay under 900 KB at 600 maximal pieces, plan M9) and read
back from either the short or the long names. Free text is his own words, bounded; every other
value comes from the fixed lists here (the workbook's 8 categories and their types, 18 colours
and multicolour, patterns, features, occasions, weather, fabrics, care words, place kinds).

A label field read from a photo (size, brand, fabric, care) is a `Verified` value: `ok` only once
he confirms or types it (INV-10); an unverified field never reaches the model (`redact.py`).
Pure: no I/O and no clock (the times are passed in).
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, Any, Literal, get_args

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from jarvis.vision.results import COLOUR_NAMES
from jarvis.wardrobe.states import EventKind, State, eligible

# ---- ids ----------------------------------------------------------------------------------------
PIECE_ID = re.compile(r"^wi_[0-9a-f]{12}$")
PAIR_ID = re.compile(r"^wp_[0-9a-f]{8}$")
SET_ID = re.compile(r"^ws_[0-9a-f]{8}$")
PLACE_ID = re.compile(r"^wl_[0-9a-f]{8}$")
PHOTO_ID = re.compile(r"^wh_[0-9a-f]{12}$")
EVENT_ID = re.compile(r"^we_[0-9a-f]{20}$")
CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
LABEL_CODE = re.compile(r"^[a-z2-7]{8}$")
QR_PAYLOAD = re.compile(r"^jw1:([a-z2-7]{8})$")  # exactly this, and one of HIS labels (D7)
_HEX = {"wi": 12, "wp": 8, "ws": 8, "wl": 8, "wh": 12, "we": 20}
_B32 = "abcdefghijklmnopqrstuvwxyz234567"


def new_id(prefix: Literal["wi", "wp", "ws", "wl", "wh", "we"]) -> str:
    return f"{prefix}_{secrets.token_hex(_HEX[prefix] // 2)}"


def new_label_code() -> str:
    return "".join(secrets.choice(_B32) for _ in range(8))


def label_code_of(qr: str) -> str | None:
    """The code of a JARVIS label's QR payload, or None ("not a JARVIS label": never sent)."""
    m = QR_PAYLOAD.match(qr) if isinstance(qr, str) else None
    return m.group(1) if m else None


def _pattern(rx: re.Pattern[str]) -> AfterValidator:
    def check(v: str) -> str:
        if not rx.match(v):
            raise ValueError("not a valid id")
        return v

    return AfterValidator(check)


PieceId = Annotated[str, _pattern(PIECE_ID)]
PairId = Annotated[str, _pattern(PAIR_ID)]
SetId = Annotated[str, _pattern(SET_ID)]
PlaceId = Annotated[str, _pattern(PLACE_ID)]
PhotoId = Annotated[str, _pattern(PHOTO_ID)]
EventId = Annotated[str, _pattern(EVENT_ID)]
ClientId = Annotated[str, _pattern(CLIENT_ID)]
LabelCode = Annotated[str, _pattern(LABEL_CODE)]

# ---- the fixed lists (the workbook's sheet "Wardrobe Rules") ------------------------------------
Category = Literal[
    "tops", "bottoms", "base", "outerwear", "traditional", "footwear", "accessories", "activity"
]
CATEGORIES: tuple[Category, ...] = get_args(Category)
CATEGORY_WORDS: Mapping[str, str] = {
    "tops": "Tops",
    "bottoms": "Bottoms",
    "base": "Base layers and socks",
    "outerwear": "Outerwear",
    "traditional": "Traditional and festive",
    "footwear": "Footwear",
    "accessories": "Accessories",
    "activity": "Activity and other",
}
TYPES: Mapping[Category, tuple[str, ...]] = {
    "tops": ("shirt", "t_shirt", "polo", "top"),
    "bottoms": ("trousers", "chinos", "jeans", "shorts", "joggers"),
    "base": ("underpants", "briefs", "boxers", "vest", "undershirt", "thermal", "sock"),
    "outerwear": ("blazer", "jacket", "hoodie", "sweater", "coat", "rainwear"),
    "traditional": ("kurta", "pyjama", "mundu", "dhoti", "festive_layer"),
    "footwear": ("dress_shoe", "sneaker", "sandal", "slipper", "boot"),
    "accessories": ("watch", "belt", "tie", "cap", "scarf", "jewellery", "bag", "eyewear"),
    "activity": ("sleepwear", "gym", "swim", "work_gear"),
}
UNKNOWN_TYPE = "unknown"
# Private by default (D10); he may change any piece. Socks are not private.
PRIVATE_BY_DEFAULT: frozenset[str] = frozenset(
    {"underpants", "briefs", "boxers", "vest", "undershirt", "thermal"}
)
PAIRED_TYPES: frozenset[str] = frozenset({"sock", *TYPES["footwear"]})  # each side is a piece
COLOURS: tuple[str, ...] = (*COLOUR_NAMES, "multicolour")
PATTERNS: tuple[str, ...] = ("solid", "striped", "checked", "printed", "dotted", "textured")
FEATURES: Mapping[str, tuple[str, ...]] = {
    "sleeve": ("short", "long", "three_quarter", "sleeveless"),
    "collar": ("none", "spread", "button_down", "mandarin", "polo", "round", "v_neck"),
    "fit": ("slim", "regular", "loose"),
    "neck": ("comfortable", "tight"),  # STY-08: "no tight collars"
    "strap": ("leather", "metal", "fabric", "rubber"),
    "closure": ("buttons", "zip", "laces", "velcro", "slip_on", "buckle"),
    "side": ("left", "right"),
}
OCCASIONS: tuple[str, ...] = ("work", "formal", "casual", "festive", "sport", "travel", "home")
WEATHER: tuple[str, ...] = ("hot", "warm", "cool", "cold", "rain_ok")
FABRICS: tuple[str, ...] = (
    *("cotton", "linen", "silk", "wool", "polyester", "nylon", "viscose", "rayon", "denim"),
    *("leather", "elastane", "spandex", "khadi", "blend"),
)
CARE_WORDS: tuple[str, ...] = (
    *("machine_wash", "hand_wash", "dry_clean", "do_not_wash", "cold_wash", "warm_wash"),
    *("do_not_bleach", "tumble_dry", "do_not_tumble", "line_dry", "iron_low", "iron_medium"),
    *("iron_high", "do_not_iron", "wash_dark_separately"),
)
SIZE_RE = re.compile(r"^[0-9A-Z /.-]{1,12}$")
BRAND_RE = re.compile(r"^[A-Za-z0-9 &.'-]{1,30}$")
PlaceKind = Literal["storage", "intake", "basket", "return", "travel", "out"]
View = Literal["front", "back", "detail"]
Source = Literal["phone", "tap", "camera"]
How = Literal["qr", "match", "tap", "label", "owner"]
LABEL_MAX, PLACE_LABEL_MAX, NOTE_MAX, SET_PARTS = 60, 40, 120, (2, 6)


class _Rec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    def to_json(self) -> dict[str, Any]:
        """The stored form: short keys, defaults left out."""
        return self.model_dump(mode="json", by_alias=True, exclude_defaults=True)


class Verified(_Rec):
    """A label field: `ok` only once he confirmed or typed it (INV-10)."""

    v: str = Field(min_length=1, max_length=40)
    ok: bool = False


def _choice(values: tuple[str, ...]) -> AfterValidator:
    def check(v: str) -> str:
        if v not in values:
            raise ValueError("not one of the fixed words")
        return v

    return AfterValidator(check)


Colour = Annotated[str, _choice(COLOURS)]
Pattern = Annotated[str, _choice(PATTERNS)]
Occasion = Annotated[str, _choice(OCCASIONS)]
Weather = Annotated[str, _choice(WEATHER)]
Label = Annotated[str, Field(max_length=LABEL_MAX)]
TYPE_WORD = re.compile(r"^[a-z][a-z0-9_]{0,23}$")  # a TYPES word, unknown or one he added


class Piece(_Rec):
    id: PieceId = Field(alias="i")
    category: Category = Field(alias="c")
    type: str = Field(alias="t", min_length=1, max_length=24)  # a TYPES word, unknown or his own
    label: Label = Field(default="", alias="l")  # his words (fenced wherever they go)
    colour: Colour | None = Field(default=None, alias="co")
    second: Colour | None = Field(default=None, alias="c2")
    pattern: Pattern | None = Field(default=None, alias="pa")
    locked: tuple[str, ...] = Field(default=(), alias="lk", max_length=12)  # never overwritten
    features: Mapping[str, str] = Field(default_factory=dict, alias="f")
    size: Verified | None = Field(default=None, alias="sz")
    brand: Verified | None = Field(default=None, alias="br")
    fabric: tuple[Verified, ...] = Field(default=(), alias="fa", max_length=4)
    care: tuple[Verified, ...] = Field(default=(), alias="ca", max_length=8)
    formality: int | None = Field(default=None, alias="fo", ge=1, le=5)
    occasions: tuple[Occasion, ...] = Field(default=(), alias="oc")
    weather: tuple[Weather, ...] = Field(default=(), alias="we")
    mess_ok: bool = Field(default=False, alias="mo")
    delicate: bool = Field(default=False, alias="de")
    private: bool = Field(default=False, alias="pr")
    place: PlaceId | None = Field(default=None, alias="pl")
    place_at: datetime | None = Field(default=None, alias="pt")  # when last confirmed there
    state: State = Field(default="ready", alias="st")  # the fold's, never set by hand
    back_to: State | None = Field(default=None, alias="bt")
    hold: str | None = Field(default=None, alias="ho", max_length=24)  # a fixed reason word
    expected_back: date | None = Field(default=None, alias="eb")  # the latest sent_out's due
    wear: str | None = Field(default=None, alias="wr", max_length=40)  # a wear's plan or event
    wears: int = Field(default=0, alias="wn", ge=0)
    last_worn: datetime | None = Field(default=None, alias="lw")
    label_code: LabelCode | None = Field(default=None, alias="lc")
    photos: tuple[PhotoId, ...] = Field(default=(), alias="ph", max_length=3)
    fp_model: str | None = Field(default=None, alias="fm", max_length=16)
    merged_into: PieceId | None = Field(default=None, alias="mi")
    events: int = Field(default=0, alias="ne", ge=0)  # events in its log (pages of 200)
    created_at: datetime | None = Field(default=None, alias="ct")
    updated_at: datetime | None = Field(default=None, alias="ut")

    @model_validator(mode="after")
    def _fixed_words(self) -> Piece:
        if not TYPE_WORD.match(self.type):
            raise ValueError("a type is a short word")
        if any(FEATURES.get(k) is None or v not in FEATURES[k] for k, v in self.features.items()):
            raise ValueError("a feature must come from the fixed lists")
        return self

    @property
    def eligible(self) -> bool:
        return eligible(self.state) and self.merged_into is None


class Pair(_Rec):
    id: PairId = Field(alias="i")
    pieces: tuple[PieceId, PieceId] = Field(alias="p")
    paired_on: date | None = Field(default=None, alias="d")


class SetPart(_Rec):
    piece: PieceId = Field(alias="p")
    alone: bool = Field(default=False, alias="a")  # "can be worn alone"


class PieceSet(_Rec):
    id: SetId = Field(alias="i")
    label: Annotated[str, Field(max_length=PLACE_LABEL_MAX)] = Field(default="", alias="l")
    parts: tuple[SetPart, ...] = Field(alias="p", min_length=SET_PARTS[0], max_length=SET_PARTS[1])


class Place(_Rec):
    id: PlaceId = Field(alias="i")
    label: Annotated[str, Field(min_length=1, max_length=PLACE_LABEL_MAX)] = Field(alias="l")
    kind: PlaceKind = Field(default="storage", alias="k")
    baseline_at: datetime | None = Field(default=None, alias="b")  # INV-02 coverage
    camera: None = Field(default=None, alias="cam")  # later (R8): a fixed camera's zone


class WardrobeLabel(_Rec):
    code: LabelCode = Field(alias="c")
    number: int = Field(alias="n", ge=1, le=9999)
    piece: PieceId | None = Field(default=None, alias="p")


class Evidence(_Rec):
    how: How = Field(alias="h")
    score: float | None = Field(default=None, alias="s", ge=0.0, le=1.0)
    crossed: bool | None = Field(default=None, alias="x")  # a later fixed camera's fields
    released: bool | None = Field(default=None, alias="r")  # (LND-02: no release -> review)


class Event(_Rec):
    """One append-only ledger entry (D4). `at` is the corrected capture time the store settled;
    `recorded` the server's time of recording (ties); `sent` the device's clock when it sent."""

    id: EventId = Field(alias="i")
    client_id: ClientId | None = Field(default=None, alias="ci")
    piece: PieceId = Field(alias="p")
    kind: EventKind = Field(alias="k")
    at: datetime = Field(alias="a")
    sent: datetime | None = Field(default=None, alias="se")
    recorded: datetime = Field(alias="r")
    source: Source = Field(alias="so")
    via: str = Field(default="panel", alias="v", min_length=1, max_length=40)
    verified: bool = Field(default=True, alias="ve")
    evidence: Evidence = Field(
        default_factory=lambda: Evidence.model_validate({"how": "tap"}), alias="ev"
    )
    to: State | None = Field(default=None, alias="to")  # a STATED kind's state
    place: PlaceId | None = Field(default=None, alias="pl")
    load: str | None = Field(default=None, alias="lo", max_length=24)
    batch: str | None = Field(default=None, alias="ba", max_length=24)
    due: date | None = Field(default=None, alias="du")  # `sent_out`: the shop's date (LND-14)
    plan: str | None = Field(default=None, alias="pn", max_length=40)
    voids: EventId | None = Field(default=None, alias="vo")  # `corrected` only
    rev_seen: int | None = Field(default=None, alias="rv", ge=0)
    note: str = Field(default="", alias="n", max_length=NOTE_MAX)

    def sort_key(self) -> tuple[datetime, datetime, str]:
        return (self.at, self.recorded, self.id)


class WardrobeSettings(_Rec):
    """His own choices, in the sealed index (D13, D7, D10, D12)."""

    calendar: str | None = Field(default=None, alias="cal", max_length=300)  # from his list only
    fields: tuple[Literal["title", "location"], ...] = Field(default=("title",), alias="fld")
    lead_h: int = Field(default=12, alias="ld", ge=0, le=48)
    plan_alerts: bool = Field(default=True, alias="pa")
    ai_tagging: bool = Field(default=False, alias="ai")
    auto_swap: bool = Field(default=False, alias="as")
    show_private: bool = Field(default=False, alias="sp")
    custom_types: tuple[Annotated[str, Field(max_length=24)], ...] = Field(default=(), alias="ty")


class WardrobeView(_Rec):
    """The index as every part reads it (A's `WardrobeStore.view`): `rev` goes up once a commit."""

    uid: str = Field(alias="u", min_length=1, max_length=128)
    rev: int = Field(default=0, alias="rv", ge=0)
    pieces: Mapping[str, Piece] = Field(default_factory=dict, alias="pc")
    pairs: Mapping[str, Pair] = Field(default_factory=dict, alias="pr")
    sets: Mapping[str, PieceSet] = Field(default_factory=dict, alias="ps")
    places: Mapping[str, Place] = Field(default_factory=dict, alias="pl")
    labels: Mapping[str, WardrobeLabel] = Field(default_factory=dict, alias="lb")
    settings: WardrobeSettings = Field(default_factory=WardrobeSettings, alias="st")
    tag_month: str | None = Field(default=None, alias="tm", pattern=r"^\d{4}-\d{2}$")
    tag_inr: float = Field(default=0.0, alias="ti", ge=0.0)  # month-to-date tagging (his zone)
    # every document carries `updated_at` under that very name: R14's drill samples on it
    updated_at: datetime | None = Field(default=None, alias="updated_at")

    def piece(self, pid: str) -> Piece | None:
        return self.pieces.get(pid)

    def active(self) -> tuple[Piece, ...]:
        return tuple(
            p for p in self.pieces.values() if p.state != "archived" and p.merged_into is None
        )


__all__ = [
    "BRAND_RE",
    "CARE_WORDS",
    "CATEGORIES",
    "CATEGORY_WORDS",
    "CLIENT_ID",
    "COLOURS",
    "EVENT_ID",
    "FABRICS",
    "FEATURES",
    "LABEL_CODE",
    "OCCASIONS",
    "PAIRED_TYPES",
    "PAIR_ID",
    "PATTERNS",
    "PHOTO_ID",
    "PIECE_ID",
    "PLACE_ID",
    "PRIVATE_BY_DEFAULT",
    "QR_PAYLOAD",
    "SET_ID",
    "SIZE_RE",
    "TYPES",
    "UNKNOWN_TYPE",
    "WEATHER",
    "Category",
    "Event",
    "Evidence",
    "Pair",
    "Piece",
    "PieceSet",
    "Place",
    "SetPart",
    "Verified",
    "WardrobeLabel",
    "WardrobeSettings",
    "WardrobeView",
    "label_code_of",
    "new_id",
    "new_label_code",
]
