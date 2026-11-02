# tests/test_challenge_sweep.py — slice 11 D7 (c): passkey challenges a browser never answered are
# swept by the scheduler tick (not Firestore TTL, which is billed): the oldest expired first, any
# owner, at most a bounded batch per tick; live challenges are never touched; a failing store never
# fails the tick.
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.scheduler_auth import TICK_PATH
from jarvis.config import SessionBackend, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.passkeys import CHALLENGE_TTL, SWEEP_BATCH, ChallengeStore
from jarvis.storage.docs import Doc, MemoryDocs, Op, Query

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


async def _make(store: ChallengeStore, cid: str, uid: str = "u1", purpose: str = "approve") -> None:
    await store.create(cid=cid, uid=uid, purpose=purpose, binding="b" * 64, challenge="c")


async def _left(docs: MemoryDocs) -> set[str]:
    return {cid for cid, _ in await docs.query(Query("jarvis_webauthn_challenges"))}


async def test_the_sweep_deletes_only_expired_challenges_of_every_owner() -> None:
    docs, clock = MemoryDocs(), Clock()
    store = ChallengeStore(docs, clock=clock)
    await _make(store, "old1", uid="u1")
    await _make(store, "old2", uid="u2")
    clock.now = T0 + CHALLENGE_TTL + timedelta(seconds=1)
    await _make(store, "fresh", uid="u3")  # created later: still live
    assert await store.sweep_expired() == 2
    assert await _left(docs) == {"fresh"}
    assert await store.sweep_expired() == 0  # nothing more to do


async def test_the_sweep_is_bounded_and_takes_the_oldest_first() -> None:
    docs, clock = MemoryDocs(), Clock()
    store = ChallengeStore(docs, clock=clock)
    for i in range(5):  # different owners: the per-owner tidy-up never runs for them
        clock.now = T0 + timedelta(seconds=i)
        await _make(store, f"c{i}", uid=f"u{i}")
    clock.now = T0 + timedelta(hours=1)
    assert await store.sweep_expired(limit=2) == 2
    assert await _left(docs) == {"c2", "c3", "c4"}
    assert await store.sweep_expired(limit=2) == 2
    assert await store.sweep_expired(limit=2) == 1
    assert await _left(docs) == set()
    assert SWEEP_BATCH >= 50


async def test_the_sweep_reads_at_most_its_batch() -> None:
    docs, clock = MemoryDocs(), Clock()
    store = ChallengeStore(docs, clock=clock)
    for i in range(30):
        await _make(store, f"c{i:02d}", uid=f"u{i}")
    clock.now = T0 + timedelta(hours=1)
    reads = docs.reads
    assert await store.sweep_expired(limit=10) == 10
    assert docs.reads - reads <= 10


class Broken(MemoryDocs):
    async def query(self, q: Query) -> list[tuple[str, Doc]]:
        raise ConnectionError("firestore unreachable")

    async def write(self, ops: Sequence[Op]) -> None:
        raise ConnectionError("firestore unreachable")


async def test_a_failing_store_never_fails_the_sweep() -> None:
    store = ChallengeStore(Broken(), clock=Clock())
    assert await store.sweep_expired() == 0


async def test_the_scheduler_tick_sweeps_challenges(settings: Settings) -> None:
    from test_scheduler_auth import KEY, SA, FakeJWKS, token, verifier

    s = settings.model_copy(
        update={
            "brief_scheduler_sa": SA,
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "session_backend": SessionBackend.FIRESTORE,  # the tick needs persistent storage
        }
    )
    app = create_app(
        s,
        provider=MockProvider(),
        store=InMemorySessionStore(),
        scheduler_verifier=verifier(FakeJWKS(KEY)),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            ran: list[bool] = []

            async def spy() -> int:
                ran.append(True)
                return 3

            app.state.permissions.sweep_challenges = spy
            r = await c.post(TICK_PATH, headers={"Authorization": f"Bearer {token()}"})
            assert r.status_code == 200 and ran == [True]


async def test_the_service_sweep_delegates_and_never_raises() -> None:
    from jarvis.permissions.passkeys import PasskeyStore
    from jarvis.permissions.service import PermissionsService
    from jarvis.permissions.store import PermissionsStore

    docs, clock = MemoryDocs(), Clock()
    challenges = ChallengeStore(docs, clock=clock)
    svc = PermissionsService(
        store=PermissionsStore(docs),
        passkeys=PasskeyStore(docs),
        challenges=challenges,
        rp=None,
        can_reauth=False,
    )
    await _make(challenges, "old")
    clock.now = T0 + timedelta(hours=1)
    assert await svc.sweep_challenges() == 1
    broken = PermissionsService(
        store=PermissionsStore(docs),
        passkeys=PasskeyStore(docs),
        challenges=ChallengeStore(Broken(), clock=clock),
        rp=None,
        can_reauth=False,
    )
    assert await broken.sweep_challenges() == 0
