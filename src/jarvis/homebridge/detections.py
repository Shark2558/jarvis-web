# src/jarvis/homebridge/detections.py
"""Frigate events -> cloud `Detection`s, filtered at home (R3 D1, D7, D8, D13, D20).

The first of two filters (the cloud has the second): a detection leaves the laptop only when ALL
hold:

- the bridge's own arm state is armed (while disarmed nothing about a person is ever sent);
- the label is one of the fixed list and the camera id has the safe shape;
- the camera has alarm zones the owner drew (nothing public, D20) and the object ENTERED one;
- it is the first time this Frigate event id is seen in such a zone (no stream of updates).

Everything Frigate says is untrusted text: the model below keeps only the fields used, every id is
checked against the wire vocabulary, and only the zones that matched leave the laptop. A recognised
face is forwarded only for an id the cloud synced as consented and only at Frigate's threshold; a
name typed into Frigate's UI never matches the `fp_` shape and is dropped.

Bridge-kit module: standard library, pydantic and `jarvis.home.ports` only.
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from jarvis.home.ports import (
    LABEL_ID,
    LABELS,
    PERSON_ID,
    Detection,
    FaceMatch,
)
from jarvis.homebridge.arm import ArmState

log = logging.getLogger(__name__)

MAX_PAYLOAD = 64 * 1024
MAX_SEEN = 512
RECOGNITION_THRESHOLD = 0.9
DELIVERY_WINDOW_S = 120.0
EVENT_ID_FORM = re.compile(r"^[A-Za-z0-9._:-]{1,50}$")


class _After(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    camera: str
    label: str
    sub_label: Any = None
    top_score: float | None = None
    score: float | None = None
    start_time: float
    end_time: float | None = None
    entered_zones: list[str] = []
    false_positive: bool = False


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    after: _After


def parse_message(payload: bytes) -> _Message | None:
    if len(payload) > MAX_PAYLOAD:
        return None
    try:
        return _Message.model_validate(json.loads(payload))
    except (ValueError, ValidationError):
        return None


def face_of(sub_label: Any, faces: frozenset[str]) -> FaceMatch | None:
    """Frigate's recognition result as a `FaceMatch`, only for a consented id at its threshold."""
    name: Any
    score: Any
    if isinstance(sub_label, list | tuple) and len(sub_label) == 2:
        name, score = sub_label
    else:
        return None
    if not isinstance(name, str) or not re.fullmatch(PERSON_ID, name) or name not in faces:
        return None
    if isinstance(score, bool) or not isinstance(score, int | float):
        return None
    if not 0 <= score <= 1 or score < RECOGNITION_THRESHOLD:
        return None
    return FaceMatch(person=name, score=float(score))


class Detections:
    def __init__(self, arm: ArmState) -> None:
        self._arm = arm
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._person_at: dict[tuple[str, str], float] = {}

    def _first_time(self, event_id: str) -> bool:
        if event_id in self._seen:
            return False
        self._seen[event_id] = None
        while len(self._seen) > MAX_SEEN:
            self._seen.popitem(last=False)
        return True

    def release(self, event_id: str) -> None:
        """The detection could not be posted: let this event's next update try again."""
        self._seen.pop(event_id, None)

    def person_seen_recently(self, camera: str, zone: str, now: float) -> bool:
        at = self._person_at.get((camera, zone))
        return at is not None and 0 <= now - at <= DELIVERY_WINDOW_S

    def filter(self, payload: bytes) -> Detection | None:
        """The detection to send up for this `frigate/events` payload, or None."""
        msg = parse_message(payload)
        if msg is None or msg.type == "end":
            return None
        ev = msg.after
        if ev.false_positive or ev.label not in LABELS or not re.fullmatch(LABEL_ID, ev.camera):
            return None
        if not EVENT_ID_FORM.fullmatch(ev.id):
            return None
        entered = [z for z in ev.entered_zones if re.fullmatch(LABEL_ID, z)]
        if ev.label == "person":  # the doorstep's "delivered" mark is local knowledge
            for zone in entered:
                self._person_at[(ev.camera, zone)] = ev.start_time
        settings = self._arm.settings
        if not self._arm.armed or settings is None:
            return None
        cam = settings.cameras.get(ev.camera)
        if cam is None:
            return None
        zones = tuple(z for z in entered if z in cam.alarm_zones)
        if not zones:
            return None
        score = ev.top_score if ev.top_score is not None else ev.score
        if score is None or not 0 <= score <= 1:
            return None  # not used up: a later update of this event may carry a score
        if not self._first_time(ev.id):
            return None
        try:
            return Detection(
                type="detection",
                id=f"det:{ev.id}",
                camera=ev.camera,
                zones=zones,
                label=ev.label,  # type: ignore[arg-type]
                start=ev.start_time,
                score=float(score),
                face=face_of(ev.sub_label, self._arm.faces),
            )
        except ValidationError:
            log.warning("a detection did not fit the wire vocabulary; dropped")
            return None


__all__ = ["DELIVERY_WINDOW_S", "Detections", "face_of", "parse_message"]
