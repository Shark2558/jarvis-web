# tests/r13_fakes_a.py -- R13 Part A's fakes (imported bare: `from r13_fakes_a import ...`).
#
#   conformance_store(docs, now)   A's REAL sealed store on MemoryDocs with a test keyring: I0's
#                                  `tests/test_r13_fold_conformance.py` finds it and runs every
#                                  case on it too (the fold, the dedup, the time rule, one commit)
#   ROOT, ring()                   the test keyring (32 fixed bytes; never a real key)
#   catalog(...)                   the whole Part A on fakes: store, service, photos, bin, tools
#   jpeg(w, h, extra)              a structurally valid baseline JPEG of that size (no pixels)
#   fp(seed)                       a 1,708-character base64 fingerprint (1,280 uint8)
#   FakeEyes                       `BrainEyes.look` stand-in: records the call, answers JSON
#
# Every clock is FIXED (`r13_fakes.FixedClock`, `ist`); nothing here reads the real one.
from __future__ import annotations

import base64
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from r13_fakes import UID, FixedClock, ist

from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.wardrobe.catalog.store import CatalogStore

ROOT = bytes(range(101, 133))
OTHER = "owner-x"


def ring() -> Keyring:
    return Keyring(ROOT)


def conformance_store(docs: MemoryDocs, now: Callable[[], datetime]) -> CatalogStore:
    """A's real store, as I0's conformance test builds every store."""
    return CatalogStore(docs, ring(), now)


def settings(**over: Any) -> Settings:
    return Settings(_env_file=None).model_copy(update=over)


@dataclass
class Catalog:
    docs: MemoryDocs
    clock: FixedClock
    store: CatalogStore
    undo: UndoBin
    part: Any = None
    state: dict[str, Any] = field(default_factory=dict)


def catalog(
    docs: MemoryDocs | None = None,
    *,
    clock: FixedClock | None = None,
    s: Settings | None = None,
    keyring: Keyring | None = None,
    eyes: Any = None,
    billing: Any = None,
) -> Catalog:
    """Part A built through its real `build(ctx)` on fakes, its bin registered like the wiring."""
    from zoneinfo import ZoneInfo

    from jarvis.wardrobe.catalog.part import build
    from jarvis.wardrobe.ports import WardrobeContext

    docs = docs if docs is not None else MemoryDocs()
    clock = clock or FixedClock(ist(2026, 11, 16, 9, 0))
    state: dict[str, Any] = {}
    undo = UndoBin(DeletedStore(docs), clock=clock)
    state["undo"] = undo
    if eyes is not None:
        state["brain_eyes"] = eyes

    async def zone(uid: str) -> ZoneInfo:
        return ZoneInfo("Asia/Kolkata")

    ctx = WardrobeContext(
        s=s or settings(),
        docs=docs,
        keyring=keyring if keyring is not None else ring(),
        audit=None,
        now=clock,
        zone=zone,
        state=state.get,
    )
    part = build(ctx)
    found = part.services.get("bin")
    if found is not None:
        undo.register("wardrobe_item", found, found)
    store = part.services.get("store")
    return Catalog(docs, clock, store, undo, part, state)  # type: ignore[arg-type]


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def jpeg(width: int = 512, height: int = 384, *, extra: bytes = b"") -> bytes:
    """A well-formed baseline JPEG's structure: SOI, an APP1 (dropped by the cleaner), DQT, SOF0
    of `width` x `height`, DHT, SOS with a little entropy data (plus `extra`), EOI. Never
    decoded."""
    app1 = _segment(0xE1, b"Exif\x00\x00GPS-LAT-LONG")
    dqt = _segment(0xDB, b"\x00" + bytes(range(64)))
    sof = _segment(0xC0, struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00")
    dht = _segment(0xC4, b"\x00" + bytes([1] + [0] * 15) + b"\x00")
    scan = b"\x12\x34" + extra.replace(b"\xff", b"\x00") + b"\x00\x56"  # entropy data
    sos = _segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + scan
    return b"\xff\xd8" + app1 + dqt + sof + dht + sos + b"\xff\xd9"


def fp(seed: int) -> str:
    """A uint8 fingerprint of 1,280 values as base64 (1,708 characters)."""
    raw = bytes((seed * 31 + i * 7) % 256 for i in range(1280))
    out = base64.b64encode(raw).decode()
    assert len(out) == 1708
    return out


@dataclass
class FakeEyes:
    """Stands in for `picture.eyes.BrainEyes`: `look` records the call and answers `answer`;
    `cant` makes it refuse like the real one (No-AI, no seeing brain, the limit)."""

    answer: str = '{"category": "tops", "type": "shirt", "colour": "navy", "pattern": "solid"}'
    cost_usd: float = 0.0001
    cant: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def look(self, uid: str, system: str, ask: str, picture: Any, *, max_tokens: int) -> Any:
        self.calls.append({"uid": uid, "system": system, "ask": ask, "max_tokens": max_tokens})
        if self.cant is not None:
            raise self.cant
        return _Glance(self.answer, self.cost_usd, "claude-haiku-5-5")


@dataclass(frozen=True)
class _Glance:
    text: str
    cost_usd: float
    model: str


__all__ = [
    "OTHER",
    "ROOT",
    "UID",
    "Catalog",
    "FakeEyes",
    "catalog",
    "conformance_store",
    "fp",
    "jpeg",
    "ring",
    "settings",
]
