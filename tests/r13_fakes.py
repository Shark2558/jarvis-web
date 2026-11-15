# tests/r13_fakes.py -- R13 I0's shared fakes (imported bare: `from r13_fakes import ...`; CI runs
# plain pytest from the repository root, which is not on sys.path). Each part has its own file
# (`r13_fakes_a.py` ... `r13_fakes_d.py`). Every clock here is FIXED (IST helpers): no test reads
# the real one (plan D15, the R14 hotfix-2 lesson). Nothing here talks to Google or spends anything.
#
#   ist(y, m, d, hh, mm)         that moment in Asia/Kolkata, as an aware UTC datetime
#   FixedClock(at)               a callable clock: advance(...), set(at)
#   piece(id, ...), ev(id, kind, at, ...)   a Piece record and an Event, with sensible defaults
#   RecordingWriter, RecordingObserver      B's review writer and an observer, recording
#   memory_store(docs, now)      the in-memory WardrobeStore (r13_fakes_store.py)
#   wardrobe_context(...)        a WardrobeContext on MemoryDocs with a fixed clock
#   PILOT                        the pilot set (owner question 14): 24 pieces, a pair of shoes,
#                                socks in pairs, two near-identical vests, a watch and a belt
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from r13_fakes_store import MemoryWardrobeStore, fold, memory_store

from jarvis.config import Settings
from jarvis.storage.docs import DocTx, MemoryDocs, Op, Set
from jarvis.wardrobe.model import Event, Evidence, Pair, Piece, Place, new_id
from jarvis.wardrobe.ports import PieceChange, ReviewNeeded, WardrobeContext
from jarvis.wardrobe.states import EventKind, State

UID = "owner-w"
IST = ZoneInfo("Asia/Kolkata")
PREFIX = "jarvis_"


def ist(y: int, m: int, d: int, hh: int = 12, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST).astimezone(UTC)


class FixedClock:
    """A clock that moves only when told to (`advance`, `set`)."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> datetime:
        self.at = self.at + timedelta(**delta)
        return self.at

    def set(self, at: datetime) -> None:
        self.at = at


def piece(pid: str, type_: str = "shirt", **fields: Any) -> Piece:
    """A record with the type's category (fields: any Piece field by its long name)."""
    from jarvis.wardrobe.model import TYPES

    category = next((c for c, ts in TYPES.items() if type_ in ts), "activity")
    return Piece.model_validate({"id": pid, "category": category, "type": type_, **fields})


def ev(
    pid: str,
    kind: EventKind,
    at: datetime,
    *,
    sent: datetime | None = None,
    verified: bool = True,
    how: str = "tap",
    score: float | None = None,
    source: str = "tap",
    via: str = "panel",
    to: State | None = None,
    place: str | None = None,
    plan: str | None = None,
    due: date | None = None,
    batch: str | None = None,
    load: str | None = None,
    voids: str | None = None,
    client_id: str | None = None,
    recorded: datetime | None = None,
    note: str = "",
) -> Event:
    return Event.model_validate(
        {
            "id": new_id("we"),
            "client_id": client_id,
            "piece": pid,
            "kind": kind,
            "at": at,
            "sent": sent,
            "recorded": recorded or at,
            "source": source,
            "via": via,
            "verified": verified,
            "evidence": Evidence(how=how, score=score),  # type: ignore[arg-type]
            "to": to,
            "place": place,
            "plan": plan,
            "due": due,
            "batch": batch,
            "load": load,
            "voids": voids,
            "note": note,
        }
    )


@dataclass
class RecordingWriter:
    """B's `ReviewWriter`: reads its document through the commit's `tx` (before any write) and
    returns one Set; records what it was asked; `fail` makes it raise."""

    needed: list[tuple[ReviewNeeded, ...]] = field(default_factory=list)
    fail: bool = False
    prefix: str = PREFIX

    async def entries(
        self, uid: str, view: object, tx: DocTx, needed: Sequence[ReviewNeeded]
    ) -> Sequence[Op]:
        if self.fail:
            raise RuntimeError("the review queue could not be written")
        self.needed.append(tuple(needed))
        path = f"{self.prefix}wardrobe_review/{uid}"
        doc = await tx.get(path) or {"events": [], "pieces": []}
        events = [*doc["events"], *(n.event for n in needed if n.event)]
        pieces = sorted({*doc["pieces"], *(n.piece for n in needed if n.piece)})
        return [Set(path, {"events": events, "pieces": pieces})]


@dataclass
class RecordingObserver:
    heard: list[PieceChange] = field(default_factory=list)
    fail: bool = False

    async def changed(self, change: PieceChange) -> None:
        if self.fail:
            raise RuntimeError("an observer that breaks")
        self.heard.append(change)


def wardrobe_context(
    docs: MemoryDocs | None = None,
    *,
    now: FixedClock | None = None,
    settings: Settings | None = None,
    state: dict[str, Any] | None = None,
    store: MemoryWardrobeStore | None = None,
) -> WardrobeContext:
    """A context with a FIXED clock (16 Nov 2026, 12:00 IST unless given) and his zone IST."""
    clock = now or FixedClock(ist(2026, 11, 16))
    found = dict(state or {})

    async def zone(uid: str) -> ZoneInfo:
        return IST

    return WardrobeContext(
        s=settings or Settings(_env_file=None),
        docs=docs if docs is not None else MemoryDocs(),
        keyring=None,
        audit=None,
        now=clock,
        zone=zone,
        state=found.get,
        store=lambda: store,
    )


def _ids(prefix: str, n: int) -> list[str]:
    hexes = {"wi": 12, "wl": 8, "wp": 8}[prefix]
    return [f"{prefix}_{i:0{hexes}x}" for i in range(1, n + 1)]


PLACES: tuple[Place, ...] = tuple(
    Place.model_validate({"id": pid, "label": label, "kind": kind})
    for pid, (label, kind) in zip(
        _ids("wl", 6),
        [
            ("Drawer 2", "storage"),
            ("Shirt rack", "storage"),
            ("Shoe rack", "storage"),
            ("Accessory tray", "storage"),
            ("Laundry basket", "basket"),
            ("Travel bag", "travel"),
        ],
        strict=True,
    )
)
_DRAWER, _RACK, _SHOES, _TRAY = (p.id for p in PLACES[:4])
_SPEC: tuple[tuple[str, dict[str, Any]], ...] = (
    ("shirt", {"label": "Light blue office shirt", "colour": "light_blue", "formality": 4}),
    ("shirt", {"label": "White formal shirt", "colour": "white", "formality": 5}),
    ("shirt", {"label": "Navy striped shirt", "colour": "navy", "pattern": "striped"}),
    ("t_shirt", {"label": "Old grey tee", "colour": "grey", "mess_ok": True}),
    ("trousers", {"label": "Charcoal trousers", "colour": "charcoal", "formality": 5}),
    ("jeans", {"label": "Blue jeans", "colour": "blue", "formality": 2}),
    ("kurta", {"label": "Cream festive kurta", "colour": "beige", "occasions": ("festive",)}),
    ("pyjama", {"label": "Kurta pyjama", "colour": "white", "occasions": ("festive",)}),
    ("vest", {"label": "", "colour": "black", "private": True}),
    ("vest", {"label": "", "colour": "black", "private": True}),  # its identical copy
    ("underpants", {"label": "", "colour": "grey", "private": True}),
    ("sock", {"label": "Black sock", "colour": "black", "features": {"side": "left"}}),
    ("sock", {"label": "Black sock", "colour": "black", "features": {"side": "right"}}),
    ("sock", {"label": "Grey sock", "colour": "grey"}),
    ("sock", {"label": "Grey sock", "colour": "grey"}),
    ("dress_shoe", {"label": "Brown shoe", "colour": "brown", "features": {"side": "left"}}),
    ("dress_shoe", {"label": "Brown shoe", "colour": "brown", "features": {"side": "right"}}),
    ("sneaker", {"label": "White sneaker", "colour": "white", "weather": ("rain_ok",)}),
    ("sneaker", {"label": "White sneaker", "colour": "white", "weather": ("rain_ok",)}),
    ("belt", {"label": "Black belt", "colour": "black"}),
    ("watch", {"label": "Steel watch", "colour": "grey", "features": {"strap": "metal"}}),
    ("jacket", {"label": "Rain jacket", "colour": "navy", "weather": ("rain_ok",)}),
    ("blazer", {"label": "Charcoal blazer", "colour": "charcoal", "delicate": True}),
    ("shorts", {"label": "Gym shorts", "colour": "black", "mess_ok": True}),
)
_HOME = {"footwear": _SHOES, "accessories": _TRAY, "base": _DRAWER}
PILOT: tuple[Piece, ...] = tuple(
    piece(pid, t, **fields) for pid, (t, fields) in zip(_ids("wi", len(_SPEC)), _SPEC, strict=True)
)
PILOT = tuple(p.model_copy(update={"place": _HOME.get(p.category, _RACK)}) for p in PILOT)
_P = [p.id for p in PILOT]
PAIRS: tuple[Pair, ...] = tuple(
    Pair.model_validate({"id": pid, "pieces": pieces})
    for pid, pieces in zip(
        _ids("wp", 4),
        [(_P[11], _P[12]), (_P[13], _P[14]), (_P[15], _P[16]), (_P[17], _P[18])],
        strict=True,
    )
)


async def seeded_store(
    docs: MemoryDocs | None = None, now: FixedClock | None = None
) -> tuple[MemoryWardrobeStore, FixedClock]:
    """The in-memory store with the pilot set registered (Ready, in their places), its pairs,
    places and sets in the index, at 16 Nov 2026 09:00 IST unless given."""
    from jarvis.wardrobe.model import PieceSet, SetPart
    from jarvis.wardrobe.ports import Commit

    clock = now or FixedClock(ist(2026, 11, 16, 9, 0))
    store = memory_store(docs or MemoryDocs(), clock)

    async def fn(view: Any, tx: DocTx) -> Commit:
        events = tuple(ev(p.id, "registered", clock(), place=p.place) for p in PILOT)
        return Commit(events=events, records=PILOT)

    await store.transact(UID, fn)
    kurta_set = PieceSet(
        id="ws_00000001",
        label="Festive kurta set",
        parts=(SetPart(piece=_P[6], alone=True), SetPart(piece=_P[7], alone=False)),
    )
    path = f"{PREFIX}wardrobe/{UID}"
    doc = await store.docs.get(path) or {}
    view = store._view_of(UID, doc)  # noqa: SLF001 - the fakes set up the index's other records
    fresh = view.model_copy(
        update={
            "pairs": {p.id: p for p in PAIRS},
            "places": {p.id: p for p in PLACES},
            "sets": {kurta_set.id: kurta_set},
        }
    )
    await store.docs.write([Set(path, fresh.to_json())])
    return store, clock


__all__ = [
    "IST",
    "PAIRS",
    "PILOT",
    "PLACES",
    "UID",
    "FixedClock",
    "MemoryWardrobeStore",
    "RecordingObserver",
    "RecordingWriter",
    "ev",
    "fold",
    "ist",
    "memory_store",
    "piece",
    "seeded_store",
    "wardrobe_context",
]
