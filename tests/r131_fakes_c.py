# tests/r131_fakes_c.py -- R13.1 Part C's fakes (imported bare: `from r131_fakes_c import ...`).
# Every clock is FIXED (`r131_fakes.NOW`, 17 Nov 2026 09:00 IST); nothing here reaches Google.
#
#   YieldingDocs                  MemoryDocs whose reads yield to the loop, as a network read does,
#                                 so a read-then-write race is real (the cap's eval control)
#   FakeBilling(limit, used)      `billing.spend.ensure_spend_allowed`'s view: budgets, meter, fx;
#                                 `recorded` keeps each `record(uid, label, usd)`
#   OffMode / OnMode              `offline.mode.BrainMode.load` answering "none" / "ai"
#   FRONT, MORE_CROPS             made-up front crops for the trousers, the jeans and the blazer
#   seeme_world(...)              R13's styling part on the seeded pilot (r13_fakes_c.world) at
#                                 NOW, his photos with their views in R13's `wardrobe_photo`
#                                 documents, I0's photo vault over the crops, and a context for
#                                 Part C: `state("r13_parts")`, `billing`, `brain_mode`, `tryon`
#   ready_world(...)              seeme_world + Part C built, his photo kept, his YES given and a
#                                 new navy shirt's photo kept: (world, service, garment)
#   ask(garment, pieces, ...)     a `PictureIn` for the press (confirm_cost, the ₹ shown, an id)
#   gemini(script) / fake1(steps) a provider and how many requests reached it: C's adapter on
#                                 recorded answers, I0's one-garment fake (it chains inside itself)
#   StrictTryOn                   I0's ScriptedTryOn refusing, before it answers, what the real
#                                 adapter refuses before sending (`tryon_gemini._check`: fixed
#                                 words, 1-3 garments, JPEG or PNG): the default everywhere here
#   add_front(sw, piece, photo)   gives one of his pieces a front crop (R13's view record, a crop)
#   SlowProvider(p)               p, a little slow (a real call takes seconds): presses overlap
#   grab_logs()                   every log record's text while it is open
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from r13_fakes_c import World, world
from r131_fake_gemini import FakeGoogle, FakeTokens, picture_answer, project_of
from r131_fake_tryon import ScriptedTryOn
from r131_fakes import CROPS, IST, NOW, PHOTOS, UID, VIEW_OF, FakePhotoVault, T, jpeg

from jarvis.billing.fx import Rate
from jarvis.billing.meter import MonthUsage, UsageMeter
from jarvis.config import Settings
from jarvis.llm.tryon import TryOnAsk, TryOnResult
from jarvis.storage.docs import MemoryDocs, Set
from jarvis.wardrobe.ports import WardrobeContext, WardrobePart

RATE = 95.24


class StrictTryOn(ScriptedTryOn):
    """I0's scripted provider, checked as the real adapter checks a request before it leaves
    (`tryon_gemini._check`), so a word Part C can't send fails here too (review C-1, finding 1:
    the plain fake let "grey T-shirt" through, the adapter refused it)."""

    async def make(self, ask: TryOnAsk) -> TryOnResult:
        from jarvis.llm.tryon_gemini import _check

        _check(ask)  # TryOnNotBilled, exactly as the adapter raises it
        return await super().make(ask)


class YieldingDocs(MemoryDocs):
    """A read gives the loop away first (a real store's read is a network round trip)."""

    async def get(self, path: str) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        return await super().get(path)


@dataclass
class FakeFx:
    inr_per_usd: float = RATE

    async def rate(self) -> Rate:
        return Rate(self.inr_per_usd, "2026-11-17", "default")

    def peek(self) -> Rate:
        return Rate(self.inr_per_usd, "2026-11-17", "default")


@dataclass
class FakeBudgets:
    limit: int | None = None
    broken: bool = False

    async def get(self, uid: str) -> int | None:
        if self.broken:
            raise RuntimeError("budgets down")
        return self.limit


@dataclass
class FakeBilling:
    """The parts of `billing.service.Billing` See it on me reads (fx, budgets, meter, record)."""

    limit: int | None = None
    used_inr: float = 0.0
    rate: float = RATE
    broken: bool = False
    clock: Callable[[], datetime] = lambda: NOW
    recorded: list[tuple[str, str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.fx = FakeFx(self.rate)
        self.budgets = FakeBudgets(self.limit, self.broken)
        self.meter = _Meter(self.used_inr)

    async def record(self, uid: str, brain_id: str, cost_usd: float) -> float:
        self.recorded.append((uid, brain_id, cost_usd))
        return round(cost_usd * self.fx.inr_per_usd, 6)


class _Meter(UsageMeter):
    def __init__(self, used_inr: float) -> None:
        super().__init__(MemoryDocs())
        self._used = used_inr

    async def get(self, uid: str, month: str) -> MonthUsage:
        return MonthUsage(month=month, inr_total=self._used)


class OffMode:
    async def load(self, uid: str) -> str:
        return "none"


class OnMode:
    async def load(self, uid: str) -> str:
        return "ai"


FRONT = {T.trousers: "wh_00000000c001", T.jeans: "wh_00000000c002", T.blazer: "wh_00000000d001"}
MORE_CROPS = {ph: jpeg(512, 512, 4) for ph in FRONT.values()}
VIEWS = {**VIEW_OF, **dict.fromkeys(FRONT.values(), "front")}
OWNER_OF = {ph: pid for pid, ids in PHOTOS.items() for ph in ids} | {v: k for k, v in FRONT.items()}


@dataclass
class SeeMeWorld:
    w: World
    ctx: WardrobeContext
    vault: FakePhotoVault
    state: dict[str, Any]

    @property
    def docs(self) -> Any:
        return self.ctx.docs

    async def rev(self) -> tuple[int, dict[str, Any]]:
        view = await self.w.store.view(UID)
        return view.rev, {k: v.model_dump(mode="json") for k, v in view.pieces.items()}


async def _photos(w: World, docs: MemoryDocs, prefix: str) -> None:
    for pid, ids in {**PHOTOS, **{k: (v,) for k, v in FRONT.items()}}.items():
        await w.edit(pid, photos=tuple(ids))
    rows = [
        Set(f"{prefix}wardrobe_photo/{UID}_{ph}",
            {"owner": UID, "piece": OWNER_OF[ph], "view": VIEWS[ph], "bytes": 64, "blob": "x"})
        for ph in VIEWS
    ]  # fmt: skip
    await docs.write(rows)


async def seeme_world(
    *, at: datetime = NOW, s: Settings | None = None, provider: Any = None,
    billing: Any = None, mode: Any = None, docs: MemoryDocs | None = None,
) -> SeeMeWorld:  # fmt: skip
    """R13's styling on the seeded pilot at `at`, the photos with views, and Part C's context
    (its own documents in `docs` when given: a yielding store for the race)."""
    settings = s or Settings(_env_file=None, tryon_pictures=True)  # type: ignore[call-arg]
    w = await world(at=at, s=settings)
    mine = docs if docs is not None else w.docs
    await _photos(w, mine, settings.firestore_prefix)
    vault = FakePhotoVault({**CROPS, **MORE_CROPS})
    parts = {"catalog": WardrobePart("catalog", services={"photos": vault}), "styling": w.part}
    state: dict[str, Any] = {"r13_parts": parts, "billing": billing, "brain_mode": mode}

    async def zone(uid: str) -> Any:
        return IST

    ctx = WardrobeContext(
        s=settings, docs=mine, keyring=w.ctx.keyring, audit=None, now=w.clock, zone=zone,
        state=state.get, store=lambda: w.store, tryon=lambda: state.get("provider", provider),
    )  # fmt: skip
    return SeeMeWorld(w, ctx, vault, state)


PERSON = jpeg(600, 1200, 48)
NEW_SHIRT = jpeg(600, 800, 24)


async def ready_world(
    *, provider: Any = None, billing: Any = None, mode: Any = None, at: datetime = NOW,
    s: Settings | None = None, docs: MemoryDocs | None = None, consent: bool = True,
) -> tuple[SeeMeWorld, Any, Any]:  # fmt: skip
    """Part C built on `seeme_world`, his photo kept, his YES (unless `consent=False`) and a new
    navy shirt's photo: (world, the `seeme` service, the new garment's view)."""
    from jarvis.wardrobe.seeme import consent as cmod
    from jarvis.wardrobe.seeme.part import build

    sw = await seeme_world(
        at=at, s=s, docs=docs, provider=provider or StrictTryOn(max_garments=1),
        billing=billing if billing is not None else FakeBilling(),
        mode=mode if mode is not None else OnMode(),
    )  # fmt: skip
    svc = build(sw.ctx).services["seeme"]
    await svc.save_photo(UID, PERSON)
    if consent:
        await svc.give_consent(UID, "YES", cmod.VERSION)
    garment = await svc.add_garment(UID, "shirt", "navy", NEW_SHIRT)
    return sw, svc, garment


def ask(garment: str, pieces: tuple[str, ...] = (), *, inr: float = 8.9, n: int = 1,
        confirm: bool = True) -> Any:  # fmt: skip
    from jarvis.wardrobe.tryon.http import PictureIn

    return PictureIn(garment=garment, pieces=pieces, confirm_cost=confirm, inr_shown=inr,
                     request_id=f"tq_{n:016x}")  # fmt: skip


Prov = tuple[Any, Callable[[], int]]  # a provider, and how many requests reached it


def gemini(script: list[Any] | None = None) -> Prov:
    from jarvis.llm.tryon_gemini import GeminiTryOn

    google = FakeGoogle(script or [picture_answer()])
    p = GeminiTryOn(model="gemini-3.1-flash-image", location="us", tokens=FakeTokens(),
                    project=project_of(), http=google.client())  # fmt: skip
    return p, lambda: len(google.seen)


def fake1(steps: list[Any] | None = None) -> Prov:
    p = StrictTryOn(max_garments=1, script=steps or ())
    return p, lambda: len(p.calls)


async def add_front(sw: SeeMeWorld, pid: str, photo: str) -> None:
    """One of his pieces gets a front crop: its photo id, R13's view record and the crop."""
    view = await sw.w.store.view(UID)
    await sw.w.edit(pid, photos=(*view.pieces[pid].photos, photo))
    path = f"{sw.ctx.s.firestore_prefix}wardrobe_photo/{UID}_{photo}"
    record = {"owner": UID, "piece": pid, "view": "front", "bytes": 64, "blob": "x"}
    await sw.docs.write([Set(path, record)])
    sw.vault.crops[photo] = jpeg(512, 512, 6)


class SlowProvider:
    def __init__(self, p: Any) -> None:
        self.p, self.describe, self.estimate = p, p.describe, p.estimate

    async def make(self, a: Any) -> Any:
        await asyncio.sleep(0.01)
        return await self.p.make(a)


@contextmanager
def grab_logs() -> Iterator[list[str]]:
    found: list[str] = []

    class Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            found.append(record.getMessage() + str(record.__dict__))

    grab, root = Grab(), logging.getLogger()
    root.addHandler(grab)
    try:
        yield found
    finally:
        root.removeHandler(grab)


__all__ = [
    "FRONT",
    "NEW_SHIRT",
    "PERSON",
    "ask",
    "fake1",
    "gemini",
    "grab_logs",
    "ready_world",
    "MORE_CROPS",
    "RATE",
    "FakeBilling",
    "FakeFx",
    "OffMode",
    "OnMode",
    "Prov",
    "SeeMeWorld",
    "SlowProvider",
    "StrictTryOn",
    "YieldingDocs",
    "add_front",
    "seeme_world",
]
