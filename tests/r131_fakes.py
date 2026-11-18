# tests/r131_fakes.py -- R13.1 I0's shared fakes (imported bare: `from r131_fakes import ...`; CI
# runs plain pytest from the repository root, which is not on sys.path). Each part has its own file
# (`r131_fakes_a.py` ... `r131_fakes_d.py`, UNIQUE names). Every clock here is FIXED (IST): no
# test reads the real one. Nothing here talks to Google or spends anything.
#
#   NOW, ist(...), FixedClock       17 Nov 2026 09:00 IST; R13's helpers
#   T                               owner question 11's pilot by short name (R13's PILOT and a
#                                   second watch): shirt, striped (a patterned shirt), trousers,
#                                   blazer, rain_jacket, shoes (a pair), belt, watch, watch2,
#                                   kurta, pyjama, vest and under (two private basics)
#   jpeg(w, h, pad) / CROPS         made-up JPEGs with a real SOF marker (no pixel data, no person)
#   FakePhotoVault                  R13's `PhotoVault` (count, delete_all, get) over CROPS
#   sample_body(height, typed)      a `Body` version from the sample's proportions
#   seeded(docs, clock)             R13's seeded store + the second watch + photos on the kurta
#                                   (front and back) and the striped shirt (front and detail)
#   tryon_context(...)              a WardrobeContext: a keyring, the fixed clock, IST, the store,
#                                   the photo vault in `state("r13_parts")`, `tryon` -> provider
from __future__ import annotations

import struct
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from r13_fakes import IST, PILOT, UID, FixedClock, MemoryWardrobeStore, ev, ist, piece, seeded_store

from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.storage.docs import DocTx, MemoryDocs
from jarvis.wardrobe.ports import Commit, WardrobeContext, WardrobePart
from jarvis.wardrobe.tryon.model import Body, Measure, estimated

NOW = ist(2026, 11, 17, 9, 0)
RING = Keyring(bytes(range(77, 109)))
WATCH2 = piece("wi_0000000000c1", "watch", label="Brown leather watch", colour="brown",
               features={"strap": "leather"}, place=PILOT[19].place)  # fmt: skip
_P = [p.id for p in PILOT]
T = SimpleNamespace(
    shirt=_P[0], white=_P[1], striped=_P[2], tee=_P[3], trousers=_P[4], jeans=_P[5],
    kurta=_P[6], pyjama=_P[7], vest=_P[8], under=_P[10], shoes=(_P[15], _P[16]),
    sneakers=(_P[17], _P[18]), belt=_P[19], watch=_P[20], watch2=WATCH2.id,
    rain_jacket=_P[21], blazer=_P[22], shorts=_P[23],
)  # fmt: skip
PRIVATE = (T.vest, T.under)


def jpeg(width: int = 512, height: int = 512, pad: int = 0) -> bytes:
    """SOI, APP0 (JFIF), SOF0 with the size, a short SOS and EOI: `frame_size` reads it."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    sos = b"\xff\xda" + struct.pack(">HB", 8, 1) + b"\x01\x00\x00\x3f\x00"
    return b"\xff\xd8" + app0 + sof + sos + b"\x00" * pad + b"\xff\xd9"


CROPS: dict[str, bytes] = {
    "wh_00000000a001": jpeg(512, 384),  # the kurta, front
    "wh_00000000a002": jpeg(512, 384),  # the kurta, back
    "wh_00000000b001": jpeg(512, 512),  # the striped shirt, front
    "wh_00000000b002": jpeg(384, 384),  # the striped shirt, detail
}
PHOTOS = {T.kurta: ("wh_00000000a001", "wh_00000000a002"),
          T.striped: ("wh_00000000b001", "wh_00000000b002")}  # fmt: skip
VIEW_OF = {"wh_00000000a001": "front", "wh_00000000a002": "back",
           "wh_00000000b001": "front", "wh_00000000b002": "detail"}  # fmt: skip


class FakePhotoVault:
    """R13's catalog `PhotoVault` over CROPS (what `PhotoVault.get` opens for C's request)."""

    def __init__(self, crops: dict[str, bytes] | None = None) -> None:
        self.crops = dict(CROPS if crops is None else crops)
        self.opened: list[str] = []

    async def count(self, uid: str) -> int:
        return len(self.crops)

    async def delete_all(self, uid: str) -> int:
        n = len(self.crops)
        self.crops.clear()
        return n

    async def get(self, uid: str, photo: str) -> bytes | None:
        self.opened.append(photo)
        return self.crops.get(photo) if uid == UID else None


def sample_body(height: int = 172, typed: tuple[Measure, ...] = ("height",)) -> Body:
    return Body(**estimated(height), typed=typed, at=NOW)


async def seeded(
    docs: MemoryDocs | None = None, clock: FixedClock | None = None
) -> tuple[MemoryWardrobeStore, FixedClock]:
    """R13's seeded pilot (16 Nov 09:00 IST), the second watch and the photo ids, then NOW."""
    store, clk = await seeded_store(docs, clock or FixedClock(ist(2026, 11, 16, 9, 0)))

    async def fn(view: Any, tx: DocTx) -> Commit:
        recs = [view.pieces[pid].model_copy(update={"photos": ids}) for pid, ids in PHOTOS.items()]
        added = ev(WATCH2.id, "registered", clk(), place=WATCH2.place)
        return Commit(events=(added,), records=(*recs, WATCH2))

    await store.transact(UID, fn)
    clk.set(NOW)
    return store, clk


def tryon_context(
    store: MemoryWardrobeStore | None = None,
    *,
    docs: MemoryDocs | None = None,
    clock: FixedClock | None = None,
    settings: Settings | None = None,
    provider: Any = None,
    vault: FakePhotoVault | None = None,
    parts: dict[str, WardrobePart] | None = None,
    keyring: Keyring | None = RING,
) -> WardrobeContext:
    """A context for R13.1's parts: his zone IST, the fixed clock, R13's store, the photo vault
    as R13's catalog service (read late through `state("r13_parts")`), `tryon` -> `provider`."""
    found = dict(parts or {})
    found.setdefault(
        "catalog", WardrobePart("catalog", services={"photos": vault or FakePhotoVault()})
    )
    state = {"r13_parts": found}

    async def zone(uid: str) -> ZoneInfo:
        return IST

    return WardrobeContext(
        s=settings or Settings(_env_file=None), docs=docs if docs is not None else MemoryDocs(),
        keyring=keyring, audit=None, now=clock or FixedClock(NOW), zone=zone, state=state.get,
        store=lambda: store, tryon=lambda: provider,
    )  # fmt: skip


__all__ = [
    "CROPS",
    "IST",
    "NOW",
    "PHOTOS",
    "PRIVATE",
    "RING",
    "UID",
    "VIEW_OF",
    "WATCH2",
    "FakePhotoVault",
    "FixedClock",
    "T",
    "ist",
    "jpeg",
    "sample_body",
    "seeded",
    "tryon_context",
]
