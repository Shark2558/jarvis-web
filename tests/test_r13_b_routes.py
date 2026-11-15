# tests/test_r13_b_routes.py -- R13 Part B's routes (docs/plans/r13-wardrobe.md "The HTTP contract",
# plan review H5) on a small app around the real router: exactly the contract's two rows for
# "laundry", each reply validated by its model (`wardrobe.http.LaundryView`, `ReviewView`),
# owner-only (`require_auth`), `no-store`, 60 reads a minute per owner, 503 in plain words when
# Part B is off or left out.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.params import Depends
from httpx import ASGITransport, AsyncClient
from r13_fakes import UID, ev
from r13_fakes_b import BLAZER, JACKET, TEE, Rig, rig

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.laundry import router
from jarvis.wardrobe import http
from jarvis.wardrobe.laundry.holds import admit


@asynccontextmanager
async def client(r: Rig | None, *, on: bool = True) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    app.state.r13_parts = {"laundry": r.part} if (on and r is not None) else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def test_the_router_has_exactly_the_contracts_laundry_rows_behind_require_auth() -> None:
    planned = {(m, p) for m, p, part, *_ in http.ROUTES if part == "laundry"}
    have = {(m, r.path) for r in router.routes for m in getattr(r, "methods", ())}
    assert have == planned
    assert any(isinstance(d, Depends) and d.dependency is require_auth for d in router.dependencies)


async def test_get_laundry_answers_the_list_in_its_model() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(TEE, JACKET))
    load = (await r.desk.move(UID, "load", pieces=(JACKET,))).load
    await r.desk.send_out(UID, (BLAZER,), "Dry cleaner")
    async with client(r) as c:
        got = await c.get("/v1/laundry")
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    body = http.LaundryView.model_validate(got.json())
    assert body.basket == (TEE,) and body.ready.startswith("Laundry on")
    (l_view,) = body.loads
    assert (l_view.id, l_view.pieces, l_view.step) == (load, (JACKET,), "washing")
    (b_view,) = body.batches
    assert b_view.shop == "Dry cleaner" and b_view.pieces == (BLAZER,) and not b_view.overdue


async def test_get_review_answers_the_queue_in_its_model() -> None:
    r = await rig()
    await r.commit(admit(ev(TEE, "deposited", r.clock(), source="camera")))
    async with client(r) as c:
        got = await c.get("/v1/laundry/review")
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    body = http.ReviewView.model_validate(got.json())
    assert body.open == 1 and body.entries[0].pieces == (TEE,)
    assert body.entries[0].words == "A change JARVIS couldn't confirm: check this piece."


async def test_off_or_left_out_is_503_in_plain_words() -> None:
    async with client(None) as c:
        gone = await c.get("/v1/laundry")
    assert gone.status_code == 503 and gone.json() == {"detail": "Laundry isn't set up yet."}
    off = await rig(keyring=False)
    async with client(off) as c:
        no_key = await c.get("/v1/laundry/review")
    assert no_key.status_code == 503
    assert no_key.json() == {"detail": "Laundry is off: this server has no token key."}
    assert no_key.headers["cache-control"] == "no-store"


async def test_reads_are_limited_per_owner() -> None:
    r = await rig()
    async with client(r) as c:
        codes = [(await c.get("/v1/laundry/review")).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
