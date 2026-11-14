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
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

TaskName = Literal["text", "code", "objects", "pose", "quality"]
TASKS: tuple[str, ...] = ("text", "code", "objects", "pose", "quality")
TEXT_MAX = 2000
POSE_POINTS = 33
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


class PoseData(_Strict):
    points: tuple[Point, ...] = Field(max_length=POSE_POINTS)  # empty: nobody in view


class QualityData(_Strict):
    light: Unit
    sharp: Unit


DATA: dict[str, type[_Strict]] = {
    "text": TextData,
    "code": CodeData,
    "objects": ObjectsData,
    "pose": PoseData,
    "quality": QualityData,
}


class Result(_Strict):
    task: TaskName
    v: int = Field(ge=1, le=99)
    at: int = Field(ge=0, lt=10**12)  # unix seconds
    ms: int = Field(ge=0, le=600_000)
    device: Literal["phone", "browser", "home"]
    ok: bool
    data: dict[str, Any]
    quality: Quality


def parse_result(raw: object) -> Result | None:
    """A Result whose data fits its task's schema, else None (dropped, never repaired)."""
    if not isinstance(raw, dict):
        return None
    try:
        result = Result.model_validate(raw)
        DATA[result.task].model_validate(result.data)
    except ValidationError:
        return None
    return result


__all__ = [
    "CODE_FORMATS",
    "DATA",
    "OBJECT_LABELS",
    "POSE_POINTS",
    "TASKS",
    "TEXT_MAX",
    "Quality",
    "Result",
    "TaskName",
    "parse_result",
]
