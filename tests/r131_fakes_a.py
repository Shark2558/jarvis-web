# tests/r131_fakes_a.py -- R13.1 Part A's fakes (imported bare: `from r131_fakes_a import ...`; CI
# runs plain pytest from the repository root, which is not on sys.path). Every clock is FIXED
# (`r131_fakes.NOW`, 17 Nov 2026 09:00 IST, unless a test moves it). Nothing here calls Google.
#
#   a_world(...) -> AWorld   R13's real styling part, store and gateway (`r13_fakes_c.world`) at
#                            NOW, with I0's second watch and the photos on the kurta (front, back)
#                            and the striped shirt (front, detail), each photo's plain `view` on
#                            disk as R13's catalog writes it; the photo vault as the catalog's
#                            `photos` service; Part A's part built through `tryon.part.build`;
#                            optionally C's `seeme` service (a FakeSeeMe)
#   AWorld.app() / .client() the routes of `api/tryon.py` on a bare app, signed in as the owner,
#                            the gateway, his conversations in memory; and R13's own
#                            `GET /v1/wardrobe` (`api/wardrobe.py`) over a `CatalogDesk`: the
#                            world's store with R13's real `Views` (OPS-05's "the same pieces
#                            and rev")
#   FakeSeeMe                C's `seeme` service as A sees it (`ports.SeeMeErase`): records calls
#   seeme_docs(docs)         one of each of C's documents for him (photo, YES, a picture, a
#                            garment photo, the month's spend) and their paths
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r13_fakes import PREFIX, ev
from r13_fakes_c import BROWN_BELT, SHOES, SNEAKERS, N, World, world
from r131_fakes import IST, NOW, PHOTOS, RING, UID, VIEW_OF, WATCH2, FakePhotoVault, T

from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import DocTx, Set
from jarvis.wardrobe.catalog.views import Views
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import Commit, Committed, WardrobeContext, WardrobePart
from jarvis.wardrobe.states import EventKind

LAUNDRY: EventKind = "deposited"  # into the basket: In laundry


@dataclass
class FakeSeeMe:
    """C's `seeme` service as OPS-05 sees it: `erase(uid)` deletes C's documents for him (never
    the spend) and records the call; `fail` raises instead."""

    docs: Any
    calls: list[str] = field(default_factory=list)
    fail: bool = False

    async def erase(self, uid: str) -> int:
        self.calls.append(uid)
        if self.fail:
            raise RuntimeError("C's erase broke")
        paths = [p for p in seeme_paths(uid) if not p.startswith(f"{PREFIX}tryon_spend/")]
        found = [p for p in paths if await self.docs.get(p) is not None]
        from jarvis.storage.docs import Delete

        await self.docs.write([Delete(p) for p in found])
        return len(found)


class _NoTagging:
    async def estimate_inr(self) -> float | None:
        return None  # no AI tagging in these fakes: the settings show no estimate


@dataclass(frozen=True)
class CatalogDesk:
    """R13 catalog's desk as `GET /v1/wardrobe` reads it (`routes_common.desk_of`): the store
    and R13's real `Views`, nothing else."""

    store: Any
    views: Views
    tagging: _NoTagging = field(default_factory=_NoTagging)


@dataclass(frozen=True)
class _CatalogStore:
    desk: CatalogDesk  # the catalog part's `store` service carries its desk (R13's routes)


def seeme_paths(uid: str = UID) -> tuple[str, ...]:
    return (
        f"{PREFIX}tryon_picture/{uid}_tp_0123456789ab",
        f"{PREFIX}tryon_garment/{uid}_tg_0123456789ab",
        f"{PREFIX}tryon_person/{uid}",
        f"{PREFIX}tryon_consent/{uid}",
        f"{PREFIX}tryon_spend/{uid}_2026-11",
    )


async def seeme_docs(docs: Any, uid: str = UID) -> tuple[str, ...]:
    """One of each of C's documents (sealed blobs stand-ins, a plain owner), and their paths."""
    paths = seeme_paths(uid)
    await docs.write([Set(p, {"owner": uid, "blob": "sealed", "updated_at": NOW.isoformat()})
                      for p in paths])  # fmt: skip
    return paths


@dataclass
class AWorld:
    w: World
    ctx: WardrobeContext
    parts: dict[str, WardrobePart]
    vault: FakePhotoVault
    seeme: FakeSeeMe | None = None
    sessions: InMemorySessionStore = field(default_factory=InMemorySessionStore)

    @property
    def store(self) -> Any:
        return self.w.store

    @property
    def docs(self) -> Any:
        return self.w.docs

    @property
    def clock(self) -> Any:
        return self.w.clock

    @property
    def styling(self) -> Any:
        return self.w.styling

    @property
    def part(self) -> WardrobePart:
        return self.parts["tryon"]

    @property
    def service(self) -> Any:
        return self.part.services["tryon_looks"]

    async def view(self) -> WardrobeView:
        return await self.store.view(UID)

    async def move(self, pid: str, kind: EventKind = LAUNDRY) -> Committed:
        return await self.w.move(pid, kind)

    async def plan(self, day: str = "tomorrow", occasion: str = "meeting") -> str:
        got = await self.w.call("outfit_plan", action="save", day=day, occasion=occasion)
        return str(got.result["plan"]["id"])

    async def whole(self, plan: str, *, outer: str | None = None, drop: str = "") -> dict[str, Any]:
        """A confirm's body for the plan's look as the figure shows it: every slot with an id
        (a covered one has none), `outer` swapped in, the `drop` slot removed (D7's Remove)."""
        look = await self.service.looks.for_plan(UID, plan)
        pairs = [(s.slot, outer if outer and s.slot == "outer" else s.piece)
                 for s in look.slots if s.piece and s.slot != drop]  # fmt: skip
        return {"plan": plan, "slots": [{"slot": s, "piece": p} for s, p in pairs]}

    def app(self) -> FastAPI:
        from jarvis.api.auth import require_auth
        from jarvis.api.identity import current_user
        from jarvis.api.tryon import router
        from jarvis.api.wardrobe import router as wardrobe_router

        app = FastAPI()
        app.state.settings = self.ctx.s
        app.state.r13_parts = self.parts
        app.state.gateway = self.w.gw
        app.state.store = self.sessions
        app.include_router(router)
        app.include_router(wardrobe_router)
        app.dependency_overrides[require_auth] = lambda: None
        app.dependency_overrides[current_user] = lambda: UID
        return app

    @asynccontextmanager
    async def client(self) -> AsyncIterator[AsyncClient]:
        transport = ASGITransport(app=self.app())
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _zone(uid: str) -> ZoneInfo:
    return IST


async def _photos(w: World) -> None:
    """I0's second watch, the photo ids on the kurta and the striped shirt, and each photo's
    plain document as R13's catalog keeps it (`view`, `piece`, `owner`; no blob needed here)."""

    async def fn(view: Any, tx: DocTx) -> Commit:
        recs = [view.pieces[pid].model_copy(update={"photos": ids}) for pid, ids in PHOTOS.items()]
        added = ev(WATCH2.id, "registered", w.clock(), place=WATCH2.place)
        return Commit(events=(added,), records=(*recs, WATCH2))

    await w.store.transact(UID, fn)
    owner = {ph: pid for pid, ids in PHOTOS.items() for ph in ids}
    await w.docs.write([
        Set(f"{PREFIX}wardrobe_photo/{UID}_{ph}",
            {"owner": UID, "piece": owner[ph], "view": view, "bytes": 100,
             "updated_at": NOW.isoformat()})
        for ph, view in VIEW_OF.items()
    ])  # fmt: skip


def build_tryon(ctx: WardrobeContext) -> WardrobePart:
    from jarvis.wardrobe.tryon.part import build

    return build(ctx)


async def a_world(
    *,
    keyring: Keyring | None = RING,
    s: Settings | None = None,
    seeme: bool = False,
    docs_off: bool = False,
) -> AWorld:
    """The world at NOW (17 Nov 2026 09:00 IST), Part A built over it."""
    w = await world(at=NOW, s=s)
    await _photos(w)
    vault = FakePhotoVault()
    st = w.ctx.s
    views = Views(w.clock, stale_days=st.wardrobe_stale_days, cap_inr=st.wardrobe_ai_tag_month_inr)
    desk = _CatalogStore(CatalogDesk(w.store, views))
    parts: dict[str, WardrobePart] = {
        "catalog": WardrobePart("catalog", services={"photos": vault, "store": desk}),
        "styling": w.part,
    }
    fake = FakeSeeMe(w.docs) if seeme else None
    if fake is not None:
        parts["seeme"] = WardrobePart("seeme", services={"seeme": fake})
    ctx = WardrobeContext(
        s=w.ctx.s, docs=None if docs_off else w.docs, keyring=keyring, audit=w.audit,
        now=w.clock, zone=_zone, state=lambda name: {"r13_parts": parts}.get(name),
        store=lambda: w.store,
    )  # fmt: skip
    parts["tryon"] = build_tryon(ctx)
    return AWorld(w, ctx, parts, vault, fake)


__all__ = [
    "BROWN_BELT",
    "LAUNDRY",
    "NOW",
    "SHOES",
    "SNEAKERS",
    "UID",
    "AWorld",
    "FakeSeeMe",
    "N",
    "T",
    "a_world",
    "build_tryon",
    "seeme_docs",
    "seeme_paths",
]
