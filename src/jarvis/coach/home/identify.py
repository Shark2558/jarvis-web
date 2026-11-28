# src/jarvis/coach/home/identify.py
"""R8 (docs/plans/r8-vision.md v8.0.4 section 4.5a; the owner's D6; ADR-48; builder J): who a body
in the home camera's view is, on the home laptop, from R3's consented face library only. Ships in
the home kit.

`LaptopFaces.who(frame, points)` crops the head (from the pose's face points) out of the frame in
memory, finds the face there with OpenCV's YuNet, describes it with SFace (the same two pinned
files as the face groups, `jarvis.homebridge.face_engine.MODELS`, checked by size and SHA-256) and
compares it with the NAMED face groups only: each consented person's average face, read from the
face-groups store's file READ-ONLY (never a write: no group, crop or picture is ever added from the
live camera). A name counts only for an id the faces plugin holds as consented, and only at the
cloud's bar (`face_types.RECOGNISED` on the wire's scale, `face_types.confidence`). Otherwise the
answer is "" (unknown): a guest, saved as "Guest N" by the cloud (D6 final).

The crop, the face and its 128 numbers live only inside one call. The named averages are read
again at most every `CENTRES_EVERY_S` (a person enrolled or deleted is picked up within a minute).
"""

from __future__ import annotations

import importlib
import logging
import math
import sqlite3
import struct
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from jarvis.coach.home.engines import READY, Frame, pinned
from jarvis.homebridge.face_engine import MODELS
from jarvis.homebridge.face_types import DIM, PERSON, RECOGNISED, confidence, dot, unit

log = logging.getLogger(__name__)

CENTRES_EVERY_S = 60.0
RETRY_S = 60.0
DETECT_SCORE = 0.8
MIN_FACE = 40  # px: a smaller face is not told apart (as the face groups)
HEAD_POINTS = tuple(range(11))  # nose, eyes, ears, mouth
SEEN = 0.5  # a face point counts above this visibility
HEAD_SCALE = 2.6  # the crop's side, in ear-to-ear spans
_PACK = struct.Struct(f"<{DIM}f")
NO_LIBRARY = "the face reader's library is missing from the bridge"
NO_MODELS = "the face model files are not on this laptop yet"
NO_PEOPLE = "nobody is enrolled with consent yet"


class Identifier(Protocol):
    def status(self) -> str: ...

    def who(self, frame: Frame, points: Sequence[Mapping[str, float]]) -> str:
        """A consented person's id (fp_<12 hex>) or "" (unknown)."""
        ...


class NoOne:
    """No face library on this laptop: everyone is unknown."""

    def status(self) -> str:
        return NO_MODELS

    def who(self, frame: Frame, points: Sequence[Mapping[str, float]]) -> str:
        return ""


def named_centres(db: Path) -> dict[str, list[float]]:
    """{person id: unit average face} of the NAMED groups in the face-groups store, read-only."""
    if not db.is_file():
        return {}
    sums: dict[str, list[float]] = {}
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=2.0)
    try:
        rows = con.execute("SELECT person, vec FROM groups WHERE person IS NOT NULL").fetchall()
    finally:
        con.close()
    for person, vec in rows:
        if not isinstance(person, str) or PERSON.fullmatch(person) is None:
            continue
        if not isinstance(vec, bytes | bytearray) or len(vec) != _PACK.size:
            continue
        acc = sums.setdefault(person, [0.0] * DIM)
        for i, v in enumerate(_PACK.unpack(vec)):
            acc[i] += v
    out: dict[str, list[float]] = {}
    for person, acc in sums.items():
        try:
            out[person] = unit(acc)
        except ValueError:
            continue
    return out


def head_box(
    points: Sequence[Mapping[str, float]], width: int, height: int
) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) in pixels around the head, or None when the face isn't seen."""
    seen = [points[i] for i in HEAD_POINTS if i < len(points) and points[i]["visibility"] > SEEN]
    if len(seen) < 3:
        return None
    xs = [p["x"] * width for p in seen]
    ys = [p["y"] * height for p in seen]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    side = span * HEAD_SCALE
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    left, top = max(0, int(cx - side / 2)), max(0, int(cy - side / 2))
    right, bottom = min(width, int(cx + side / 2)), min(height, int(cy + side / 2))
    if right - left < MIN_FACE or bottom - top < MIN_FACE:
        return None
    return left, top, right, bottom


class LaptopFaces:
    def __init__(
        self,
        models_dir: Path,
        groups_db: Path,
        consented: Callable[[str], bool],
        *,
        match: float,
        load: Callable[[str], Any] = importlib.import_module,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dir = models_dir
        self._db = groups_db
        self._consented = consented
        self._match = match
        self._load = load
        self._clock = clock
        self._cv: Any = None
        self._det: Any = None
        self._rec: Any = None
        self._why = ""
        self._why_at = -RETRY_S
        self._centres: dict[str, list[float]] = {}
        self._centres_at = -CENTRES_EVERY_S

    def install(self, cv: Any, detector: Any, recogniser: Any) -> None:
        """The loaded parts (tests give fakes for the two models)."""
        self._cv, self._det, self._rec, self._why = cv, detector, recogniser, ""

    def _start(self) -> str:
        try:
            cv = self._load("cv2")
        except ImportError:
            return NO_LIBRARY
        paths = [self._dir / pin.name for pin in MODELS]
        if not all(pinned(p, pin) for p, pin in zip(paths, MODELS, strict=True)):
            return NO_MODELS
        try:
            det = cv.FaceDetectorYN.create(str(paths[0]), "", (320, 320), DETECT_SCORE, 0.3, 20)
            rec = cv.FaceRecognizerSF.create(str(paths[1]), "")
        except Exception as exc:  # noqa: BLE001 - OpenCV's text stays out of the log
            log.error("the face models could not be loaded", extra={"error": type(exc).__name__})
            return NO_LIBRARY
        self.install(cv, det, rec)
        return ""

    def status(self) -> str:
        if self._det is None and self._clock() - self._why_at >= RETRY_S:
            self._why_at = self._clock()
            self._why = self._start()
        if self._det is None:
            return self._why
        return READY if self._people() else NO_PEOPLE

    def _people(self) -> dict[str, list[float]]:
        if self._clock() - self._centres_at >= CENTRES_EVERY_S:
            self._centres_at = self._clock()
            try:
                self._centres = named_centres(self._db)
            except sqlite3.Error as exc:
                log.info("the face groups could not be read", extra={"error": type(exc).__name__})
        return {p: c for p, c in self._centres.items() if self._consented(p)}

    def who(self, frame: Frame, points: Sequence[Mapping[str, float]]) -> str:
        if self.status() != READY:
            return ""
        box = head_box(points, frame.width, frame.height)
        if box is None:
            return ""
        try:
            vector = self._describe(frame, box)
        except Exception as exc:  # noqa: BLE001 - one look, never the loop
            log.info("a face could not be looked at", extra={"error": type(exc).__name__})
            return ""
        if vector is None:
            return ""
        best, score = "", 0.0
        for person, centre in self._people().items():
            cosine = dot(vector, centre)
            if cosine > score:
                best, score = person, cosine
        return best if best and confidence(score, self._match) >= RECOGNISED else ""

    def _describe(self, frame: Frame, box: tuple[int, int, int, int]) -> list[float] | None:
        left, top, right, bottom = box
        crop = frame.image[top:bottom, left:right]
        self._det.setInputSize((int(crop.shape[1]), int(crop.shape[0])))
        _, found = self._det.detect(crop)
        rows = sorted(found if found is not None else (), key=lambda r: -float(r[14]))
        if not rows or float(rows[0][14]) < DETECT_SCORE:
            return None
        row = rows[0]
        if min(float(row[2]), float(row[3])) < MIN_FACE / 2:
            return None
        aligned = self._rec.alignCrop(crop, row)
        raw = [float(v) for v in self._rec.feature(aligned).reshape(-1)]
        if len(raw) != DIM or not all(math.isfinite(v) for v in raw):
            return None
        return unit(raw)


__all__ = ["Identifier", "LaptopFaces", "NoOne", "head_box", "named_centres"]
