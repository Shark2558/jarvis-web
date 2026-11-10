# tests/test_r51_int_limits.py -- R5.1 integrated fixes int-sec M2 / M3: GET /v1/health is
# rate-limited per owner (30/min) and the briefing reads the 15 s cached Vitals board; PUT/DELETE
# /v1/vitals/keys are rate-limited per owner (10/min); the manual-record cap is counted inside the
# create transaction.
from __future__ import annotations

from types import SimpleNamespace

from fastapi import Depends, FastAPI
from health_fakes import UID, Clock, fixed
from httpx import ASGITransport, AsyncClient

from jarvis.api.selfcheck_wiring import LiveVitals
from jarvis.health.api import GET_PER_MINUTE, health_router
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.storage.docs import MemoryDocs


def _app() -> FastAPI:
    s = HealthService(
        [fixed("a", "Redis", "ok")], HealthStore(MemoryDocs(), prefix="jarvis_"), clock=Clock()
    )
    a = FastAPI()
    a.include_router(health_router(s, user=lambda: UID, dependencies=[Depends(lambda: None)]))
    return a


async def test_get_health_is_limited_to_thirty_a_minute_per_owner() -> None:
    assert GET_PER_MINUTE == 30
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        codes = [(await c.get("/v1/health")).status_code for _ in range(GET_PER_MINUTE + 2)]
    assert codes[:GET_PER_MINUTE] == [200] * GET_PER_MINUTE
    assert codes[GET_PER_MINUTE:] == [429, 429]


async def test_get_health_does_not_spend_the_run_budget() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        for _ in range(GET_PER_MINUTE):
            await c.get("/v1/health")
        assert (await c.post("/v1/health/run")).status_code == 200


async def test_the_429_carries_retry_after() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        for _ in range(GET_PER_MINUTE):
            await c.get("/v1/health")
        r = await c.get("/v1/health")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


async def test_live_vitals_reads_the_cached_board_never_the_raw_one() -> None:
    calls: dict[str, int] = {"board": 0, "cached": 0}

    class Svc:
        async def board(self, uid: str) -> str:
            calls["board"] += 1
            return "raw"

        async def board_cached(self, uid: str) -> str:
            calls["cached"] += 1
            return "cached"

    app = SimpleNamespace(state=SimpleNamespace(vitals=Svc()))
    got = await LiveVitals(app).board(UID)  # type: ignore[arg-type]
    assert got == "cached" and calls == {"board": 0, "cached": 1}


# ---- PUT /v1/vitals/keys: the cap is counted inside the create transaction (int-sec M3) --------
async def test_parallel_creates_never_exceed_the_cap() -> None:
    import asyncio

    from vitals_fakes import UID as VUID
    from vitals_fakes import key

    from jarvis.storage.docs import MemoryDocs, Query
    from jarvis.vitals.models import MAX_MANUAL
    from jarvis.vitals.store import VitalsFull, VitalsStore

    class Slow(MemoryDocs):
        async def query(self, q: Query):  # type: ignore[no-untyped-def]
            got = await super().query(q)
            await asyncio.sleep(0)  # every parallel create has read the same (short) list
            return got

    store = VitalsStore(Slow())
    results = await asyncio.gather(
        *(store.put(VUID, key(f"k{i:03d}"), create=True) for i in range(MAX_MANUAL + 20)),
        return_exceptions=True,
    )
    assert sum(1 for r in results if r is None) == MAX_MANUAL
    assert sum(1 for r in results if isinstance(r, VitalsFull)) == 20
    assert len(await store.list_manual(VUID)) == MAX_MANUAL


async def test_a_delete_frees_a_slot_and_a_replace_of_a_known_id_is_never_full() -> None:
    from vitals_fakes import UID as VUID
    from vitals_fakes import key

    from jarvis.storage.docs import MemoryDocs
    from jarvis.vitals.models import MAX_MANUAL
    from jarvis.vitals.store import VitalsFull, VitalsStore

    store = VitalsStore(MemoryDocs())
    for i in range(MAX_MANUAL):
        await store.put(VUID, key(f"k{i:03d}"), create=True)
    await store.put(VUID, key("k000", label="renamed"))  # replace: not a new record
    try:
        await store.put(VUID, key("extra"), create=True)
        raise AssertionError("expected VitalsFull")
    except VitalsFull:
        pass
    assert await store.delete(VUID, "k001") is True
    await store.put(VUID, key("extra"), create=True)
    assert len(await store.list_manual(VUID)) == MAX_MANUAL


async def test_records_that_pre_date_the_index_still_count() -> None:
    from vitals_fakes import UID as VUID
    from vitals_fakes import key

    from jarvis.storage.docs import MemoryDocs, Set
    from jarvis.vitals.models import MAX_MANUAL
    from jarvis.vitals.store import VitalsFull, VitalsStore

    docs = MemoryDocs()
    store = VitalsStore(docs)
    for i in range(MAX_MANUAL):
        p = key(f"k{i:03d}")
        await docs.write(
            [
                Set(
                    f"jarvis_vitals_providers/{store._name(VUID, p.id)}",
                    {**p.fields(), "user_id": VUID},
                )
            ]
        )  # noqa: SLF001
    try:
        await store.put(VUID, key("extra"), create=True)
        raise AssertionError("expected VitalsFull")
    except VitalsFull:
        pass


# ---- PUT / DELETE are rate-limited per owner (10/min) -------------------------------------------
async def test_put_and_delete_keys_are_limited_to_ten_a_minute() -> None:
    from vitals_fakes import UID as VUID
    from vitals_fakes import Rig

    from jarvis.api.auth import require_auth
    from jarvis.api.identity import current_user
    from jarvis.vitals import api as vapi

    assert vapi.WRITE_PER_MINUTE == 10
    rig = Rig()
    app = FastAPI()
    app.include_router(vapi.router)
    app.state.vitals = rig.svc
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: VUID
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = {"label": "K", "kind": "key"}
        puts = [
            (await c.put("/v1/vitals/keys", json={"id": f"k{i}", **body})).status_code
            for i in range(12)
        ]
        assert puts[:10] == [200] * 10 and puts[10:] == [429, 429]
        # PUT and DELETE draw from the same per-owner budget
        assert (await c.delete("/v1/vitals/keys/k1")).status_code == 429
        # reading the board is a separate budget
        assert (await c.get("/v1/vitals")).status_code == 200
