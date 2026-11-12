# tests/r11_1_fakes_c.py -- R11.1 Part C's fakes: hand-made JPEG bytes (never a photo of a real
# person), a face engine that "recognises" the made-up people written into a test picture, and a
# fake Frigate face library. Imported as a top-level module (`from r11_1_fakes_c import ...`).
from __future__ import annotations

import base64
import math
import re
import struct

from jarvis.homebridge.face_types import DIM, SeenFace

A = "fp_3a9c12ab34cd"
B = "fp_000000000001"
CROP_NEEDLE = b"CROP-NEEDLE-7f3a91"
PICTURE_NEEDLE = b"PICTURE-NEEDLE-91c2e4"
# sixteen or more numbers in a row: what a leaked embedding looks like in JSON or a log line
EMBEDDING = re.compile(r"(?:-?\d+\.\d+(?:e-?\d+)?\s*,\s*){16,}")


def jpeg_bytes(
    width: int = 8, height: int = 8, *, sof: int = 0xC0, tail: bytes = b"\x12\x34", app: bytes = b""
) -> bytes:
    """A structurally valid JPEG of the declared size (not decodable into a real picture)."""
    return (
        b"\xff\xd8"
        + app
        + b"\xff\xdb\x00\x43\x00"
        + bytes(64)
        + bytes([0xFF, sof])
        + struct.pack(">HBHHB", 11, 8, height, width, 1)
        + b"\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + tail
        + b"\xff\xd9"
    )


def vec(person: int, wobble: int = 0) -> tuple[float, ...]:
    """A unit vector: the same made-up person with another wobble is 0.96 alike, another ~0."""
    v = [0.0] * DIM
    v[person % DIM] = 1.0
    v[(person + 40 + wobble) % DIM] = 0.2
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


def picture(*people: int, n: int = 0, needle: bool = False) -> bytes:
    """A test "photo": a valid JPEG whose scan data names the made-up people in it (by number)
    and which picture it is. `ScriptedEngine` reads them back."""
    who = ",".join(str(p) for p in people)
    tail = f"<people:{who};n:{n}>".encode() + (PICTURE_NEEDLE if needle else b"")
    return jpeg_bytes(64, 64, tail=tail)


class ScriptedEngine:
    """A face engine for tests: finds exactly the people `picture()` wrote into the bytes. Every
    crop carries CROP_NEEDLE, so a test can prove no crop ever crossed to the cloud."""

    def __init__(self, *, ready: str = "ready") -> None:
        self.ready = ready
        self.seen: list[bytes] = []
        self.own_files: list[bool] = []

    def status(self) -> str:
        return self.ready

    def faces(self, jpeg: bytes, *, own_file: bool = False) -> list[SeenFace]:
        self.seen.append(jpeg)
        self.own_files.append(own_file)
        start = jpeg.find(b"<people:")
        if start < 0:
            return []
        body = jpeg[start + 8 : jpeg.index(b">", start)].decode()
        who, n = body.split(";n:")
        out = []
        for p in (int(x) for x in who.split(",") if x):
            crop = b"\xff\xd8\xff" + CROP_NEEDLE + f"-{p}-{n}".encode()
            out.append(SeenFace(vec(p, int(n) % 30), 0.95, 120, crop))
        return out


class FakeLib:
    """Frigate's face library (`FaceLibraryPort`): pictures by library name; `down` = no answer."""

    def __init__(self) -> None:
        self.pictures: dict[str, list[bytes]] = {}
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise RuntimeError("frigate 10.0.0.5 exploded")

    async def counts(self) -> dict[str, int]:
        self._check()
        return {k: len(v) for k, v in self.pictures.items()}

    async def register(self, name: str, image: bytes, content_type: str) -> None:
        self._check()
        self.pictures.setdefault(name, []).append(image)

    async def delete(self, name: str) -> None:
        self._check()
        self.pictures.pop(name, None)

    async def recent(self) -> list[str]:
        return []

    async def recent_image(self, file: str) -> bytes:
        return b""

    async def classify(self, name: str, file: str) -> None:
        return None


def _base64_forms(needle: bytes) -> list[str]:
    """The needle as it reads inside base64 text, at each of the three byte alignments."""
    out = []
    for lead in range(3):
        text = base64.b64encode(b"\0" * lead + needle).decode()
        out.append(text[(0, 2, 3)[lead] : -4])
    return out


def leaks(blob: bytes | str) -> list[str]:
    """What a cloud-side text must never hold: a picture's or a crop's bytes (raw or base64) or
    anything shaped like an embedding. Returns the kinds found (empty = clean)."""
    text = blob.decode("latin-1") if isinstance(blob, bytes) else blob
    found = []
    for kind, needle in (("crop", CROP_NEEDLE), ("picture", PICTURE_NEEDLE)):
        if needle.decode() in text or any(form in text for form in _base64_forms(needle)):
            found.append(kind)
    if EMBEDDING.search(text):
        found.append("embedding")
    return found
