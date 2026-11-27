# src/jarvis/vision/results.py
"""R7 D13, I0 seam 8: the vision engine's Result contract, on the server.

The same shapes `console-vision.js` produces in the browser (and that a camera on the home
laptop may deliver later through the bridge's plug-ins). A task is the only code that touches a
frame; what it returns is plain data checked here against its schema: numbers in ranges, labels
from the task's own list, text of at most 2,000 characters, and NOTHING else (an unknown field is
refused, so pixels can never ride along). `parse_result` drops anything that does not fit.

    Result = {task, v, at, ms, device: "phone" | "browser" | "home", ok, data, quality}

This is a contract file: it changes only with a line in INTEGRATION-B.md, because the use cases
of R8-R10 build against it. Part B owns the folder from I0 on.

R13 I0 (docs/plans/r13-wardrobe.md D7-D9, seam 11; the line in R7's INTEGRATION-B.md): four
wardrobe tasks, `WARDROBE_TASKS` (embed, colour, person, face), that only the two pixel panels run
(Camera and Camera -> Wardrobe). Their results are checked here too (`parse_result(raw,
wardrobe=True)`), but `TASKS` stays the five: a wardrobe result is never a kept vision result
(`parse_result` without `wardrobe=True`, the kept-results route's, refuses them).

R8 I0 (docs/plans/r8-vision.md v8.0.2 section 4.2, seams S1 and S26; the lines in R7's
INTEGRATION-B.md): two more tasks, `hands` v1 (MediaPipe Hand Landmarker: at most 2 hands, each
`side`, `score` and exactly `HAND_POINTS` 21 points) and `digits` v1 (the numbers on a
seven-segment display, a blood-pressure monitor's: at most 4 lines of 0..999), and `pose` v2: the
owner's D6 ("track all"): `bodies`, up to `BODIES_MAX` 4, each `{track, who, points}` (`track`
follows one body from frame to frame; `who` is "" unknown, "me" or an enrolled person's `fp_` id,
from R3's consented face library on the home laptop only). A v1 pose result (`points`, one body)
still fits; a result never carries both.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

TaskName = Literal["text", "code", "objects", "pose", "quality", "hands", "digits"]
TASKS: tuple[str, ...] = ("text", "code", "objects", "pose", "quality", "hands", "digits")
WardrobeTask = Literal["embed", "colour", "person", "face"]
WARDROBE_TASKS: tuple[str, ...] = ("embed", "colour", "person", "face")
EMBED_DIMS = 1280  # MobileNet v2's pooled features, uint8 (D7, D8)
EMBED_B64 = 1708  # 1,280 bytes in base64: inside console-vision.js plain()'s 2,000 characters
EMBED_MODELS: tuple[str, ...] = ("mnv2-int8-1", "mnv2-fp32-1")  # never compared across models
BOXES_MAX = 20
# The 18 named colours the colour task picks the nearest of (ΔE in Lab); "multicolour" when two
# clusters are close (its `second` names the other)
COLOUR_NAMES: tuple[str, ...] = (
    *("black", "white", "grey", "charcoal", "navy", "blue", "light_blue", "green", "olive"),
    *("yellow", "orange", "red", "maroon", "pink", "purple", "brown", "beige", "khaki"),
)
TEXT_MAX = 2000
POSE_POINTS = 33
HAND_POINTS = 21  # R8: MediaPipe's hand landmarks (wrist, then four per finger)
HANDS_MAX = 2
HAND_SIDES: tuple[str, ...] = ("left", "right")
BODIES_MAX = 4  # R8 D6: everyone in view, at most four bodies
TRACK_MAX = 63
WHO = r"^(?:|me|fp_[0-9a-f]{12})$"  # unknown, the owner, or a consented person (R3's PERSON_ID)
DIGIT_LINES_MAX = 4
DIGIT_MAX = 999
# The 80 everyday things the object model knows (the COCO list MediaPipe's detector uses)
OBJECT_LABELS: tuple[str, ...] = tuple(
    "person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant "
    "stop_sign parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe "
    "backpack umbrella handbag tie suitcase frisbee skis snowboard sports_ball kite baseball_bat "
    "baseball_glove skateboard surfboard tennis_racket bottle wine_glass cup fork knife spoon "
    "bowl banana apple sandwich orange broccoli carrot hot_dog pizza donut cake chair couch "
    "potted_plant bed dining_table toilet tv laptop mouse remote keyboard cell_phone microwave "
    "oven toaster sink refrigerator book clock vase scissors teddy_bear hair_drier "
    "toothbrush".split()
)
CODE_FORMATS: tuple[str, ...] = (
    "qr_code",
    "ean_13",
    "ean_8",
    "upc_a",
    "upc_e",
    "code_128",
    "code_39",
    "itf",
    "data_matrix",
    "pdf_417",
    "aztec",
)
Unit = Annotated[float, Field(ge=0.0, le=1.0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Quality(_Strict):
    light: Unit
    sharp: Unit


class TextData(_Strict):
    text: str = Field(max_length=TEXT_MAX)
    confidence: Unit | None = None


class Code(_Strict):
    format: Literal[CODE_FORMATS]  # type: ignore[valid-type]
    value: str = Field(max_length=TEXT_MAX)


class CodeData(_Strict):
    codes: tuple[Code, ...] = Field(max_length=20)


class Box(_Strict):
    x: Unit
    y: Unit
    w: Unit
    h: Unit


class Thing(_Strict):
    label: Literal[OBJECT_LABELS]  # type: ignore[valid-type]
    score: Unit
    box: Box


class ObjectsData(_Strict):
    objects: tuple[Thing, ...] = Field(max_length=50)


class Point(_Strict):
    x: Annotated[float, Field(ge=-1.0, le=2.0)]  # a point may sit just outside the frame
    y: Annotated[float, Field(ge=-1.0, le=2.0)]
    z: Annotated[float, Field(ge=-10.0, le=10.0)]
    visibility: Unit


class Body(_Strict):
    """R8 pose v2: one body in view; `who` is never a name."""

    track: Annotated[int, Field(ge=0, le=TRACK_MAX, strict=True)]
    who: str = Field(default="", pattern=WHO)
    points: tuple[Point, ...] = Field(max_length=POSE_POINTS)


class PoseData(_Strict):
    points: tuple[Point, ...] = Field(default=(), max_length=POSE_POINTS)  # v1: one body
    bodies: tuple[Body, ...] = Field(default=(), max_length=BODIES_MAX)  # v2 (D6): everyone

    @model_validator(mode="after")
    def _one_shape(self) -> PoseData:
        if self.points and self.bodies:
            raise ValueError("a pose result is v1 (points) or v2 (bodies), never both")
        if len({b.track for b in self.bodies}) != len(self.bodies):
            raise ValueError("two bodies with one track")
        return self


class HandPoint(_Strict):
    x: Annotated[float, Field(ge=-1.0, le=2.0)]
    y: Annotated[float, Field(ge=-1.0, le=2.0)]
    z: Annotated[float, Field(ge=-10.0, le=10.0)]


class Hand(_Strict):
    side: Literal[HAND_SIDES]  # type: ignore[valid-type]
    score: Unit
    points: tuple[HandPoint, ...] = Field(min_length=HAND_POINTS, max_length=HAND_POINTS)


class HandsData(_Strict):
    hands: tuple[Hand, ...] = Field(max_length=HANDS_MAX)  # empty: no hand in view


class DigitLine(_Strict):
    value: Annotated[int, Field(ge=0, le=DIGIT_MAX, strict=True)]
    score: Unit


class DigitsData(_Strict):
    """R8 D7: the lines a seven-segment display shows, top to bottom (never stored unconfirmed)."""

    lines: tuple[DigitLine, ...] = Field(max_length=DIGIT_LINES_MAX)


class QualityData(_Strict):
    light: Unit
    sharp: Unit


class EmbedData(_Strict):
    v: str = Field(min_length=EMBED_B64, max_length=EMBED_B64, pattern=r"^[A-Za-z0-9+/]+=*$")
    dims: Literal[1280]
    model: Literal[EMBED_MODELS]  # type: ignore[valid-type]


class ColourData(_Strict):
    name: Literal[(*COLOUR_NAMES, "multicolour")]  # type: ignore[valid-type]
    second: Literal[COLOUR_NAMES] | None = None  # type: ignore[valid-type]
    share: Unit


class FoundData(_Strict):
    """`person` (SSD "person" >= 0.5) and `face` (UltraFace >= 0.7, after NMS): what the check
    found in the bitmap the crop is made from; one hit refuses what is kept or sent (D9)."""

    found: bool
    count: int = Field(ge=0, le=BOXES_MAX)
    boxes: tuple[Box, ...] = Field(max_length=BOXES_MAX)


WARDROBE_DATA: dict[str, type[_Strict]] = {
    "embed": EmbedData,
    "colour": ColourData,
    "person": FoundData,
    "face": FoundData,
}
DATA: dict[str, type[_Strict]] = {
    "text": TextData,
    "code": CodeData,
    "objects": ObjectsData,
    "pose": PoseData,
    "quality": QualityData,
    "hands": HandsData,
    "digits": DigitsData,
}


class Result(_Strict):
    task: TaskName | WardrobeTask
    v: int = Field(ge=1, le=99)
    at: int = Field(ge=0, lt=10**12)  # unix seconds
    ms: int = Field(ge=0, le=600_000)
    device: Literal["phone", "browser", "home"]
    ok: bool
    data: dict[str, Any]
    quality: Quality


def parse_result(raw: object, *, wardrobe: bool = False) -> Result | None:
    """A Result whose data fits its task's schema, else None (dropped, never repaired). Only
    `TASKS` (R7's five, R8's `hands` and `digits`) unless `wardrobe` (R13: the wardrobe routes' own
    check)."""
    if not isinstance(raw, dict):
        return None
    schemas = {**DATA, **WARDROBE_DATA} if wardrobe else DATA
    try:
        result = Result.model_validate(raw)
        schema = schemas.get(result.task)
        if schema is None:
            return None
        schema.model_validate(result.data)
    except ValidationError:
        return None
    return result


__all__ = [
    "BOXES_MAX",
    "CODE_FORMATS",
    "COLOUR_NAMES",
    "DATA",
    "EMBED_B64",
    "EMBED_DIMS",
    "EMBED_MODELS",
    "BODIES_MAX",
    "Body",
    "DigitLine",
    "DigitsData",
    "HAND_POINTS",
    "HAND_SIDES",
    "HANDS_MAX",
    "Hand",
    "HandPoint",
    "HandsData",
    "PoseData",
    "WARDROBE_DATA",
    "WARDROBE_TASKS",
    "OBJECT_LABELS",
    "POSE_POINTS",
    "TASKS",
    "TEXT_MAX",
    "WHO",
    "Quality",
    "Result",
    "TaskName",
    "WardrobeTask",
    "parse_result",
]
