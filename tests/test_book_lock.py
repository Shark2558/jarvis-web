# tests/test_book_lock.py -- R6 D10: the guest lock. The store (`{prefix}book_lock/{uid}` =
# {id, bk, since}) is read at most once per 3 s per instance, never reads as "unlocked" when it
# can't be read (LockUnreadable), and lifts only for the current lock id. The middleware covers
# every cookie session of the owner (all browsers, sign-ins made later, the other owners too):
# allowed are the show, its routes, close, resume, the passkey challenge, the passkey reset (so a
# lost passkey can still be recovered), sign-in/out, /health, /console/config and /static; `GET /`
# -> 302 /book/show; everything else, /auth/me included -> 423 show_locked. Bearer is untouched.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from book_app_fakes import BEARER, CSRF, OWNER, SECOND_OWNER, book_app, owner_uid, sign_in
from book_show_fakes import T0, UID, FlakyDocs
from httpx import AsyncClient

from jarvis.api.book_lock import ALLOWED, ShowLockMiddleware, allowed
from jarvis.buildbook.lock import DocShowLock
from jarvis.buildbook.ports import LockUnreadable, ShowLock
from jarvis.config import Settings
from jarvis.storage.docs import Set

PATH = f"jarvis_book_lock/{UID}"


class Tick:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def docs() -> FlakyDocs:
    return FlakyDocs()


async def test_set_get_and_lift_only_for_the_current_id(docs: FlakyDocs) -> None:
    lock = DocShowLock(docs)
    assert isinstance(lock, ShowLock) and await lock.get(UID) is None
    state = await lock.set(UID, "bk_0123456789abcdef", now=T0)
    assert state.id.startswith("bl_") and len(state.id) == 15 and state.since == T0.isoformat()
    assert await lock.get(UID) == state and (await docs.get(PATH) or {})["id"] == state.id
    assert await lock.lift(UID, "bl_000000000000") is False
    assert await lock.get(UID) == state
    assert await lock.lift(UID, state.id) is True
    assert await lock.get(UID) is None and await docs.get(PATH) is None
    assert await lock.lift(UID, state.id) is False  # nothing left to lift


async def test_reads_are_cached_three_seconds_per_instance(docs: FlakyDocs) -> None:
    tick = Tick()
    here, there = DocShowLock(docs, clock=tick), DocShowLock(docs, clock=tick)
    assert await here.get(UID) is None
    reads = docs.reads
    state = await there.set(UID, "bk_0123456789abcdef", now=T0)
    tick.t += 2.9
    assert await here.get(UID) is None and docs.reads == reads  # cached
    tick.t += 0.2
    assert await here.get(UID) == state and docs.reads == reads + 1


async def test_an_unreadable_lock_is_never_unlocked(docs: FlakyDocs) -> None:
    lock = DocShowLock(docs)
    docs.fail_reads = True
    with pytest.raises(LockUnreadable):
        await lock.get(UID)
    docs.fail_reads = False
    await docs.write([Set(PATH, {"id": "nope"})])
    with pytest.raises(LockUnreadable):
        await DocShowLock(docs).get(UID)


@pytest.mark.parametrize(
    ("method", "path", "ok"),
    [
        ("GET", "/book/show", True),
        ("HEAD", "/book/show", True),
        ("GET", "/static/console.css", True),
        ("GET", "/static/vendor/three-0.187.0/three.module.min.js", True),
        ("GET", "/static/../v1/chat", False),
        ("GET", "//static/x.js", False),
        ("GET", "/v1/book/show/script", True),
        ("POST", "/v1/book/show/ask", True),
        ("POST", "/v1/book/show/x", False),
        ("POST", "/v1/book/show/ask/", False),
        ("POST", "/v1/book/close", True),
        ("GET", "/v1/book/close", False),
        ("POST", "/v1/book/resume", True),
        ("POST", "/v1/book/open", False),
        ("GET", "/v1/book", False),
        ("POST", "/v1/passkeys/challenge", True),
        ("POST", "/v1/passkeys/reset", True),
        ("POST", "/v1/passkeys/reset/cancel", False),
        ("POST", "/v1/passkeys/register/options", False),
        ("GET", "/v1/permissions", False),
        ("GET", "/auth/login", True),
        ("GET", "/auth/callback", True),
        ("POST", "/auth/logout", True),
        ("GET", "/auth/me", False),
        ("GET", "/health", True),
        ("GET", "/console/config", True),
        ("GET", "/", False),
        ("POST", "/v1/chat", False),
    ],
)
def test_the_allow_list(method: str, path: str, ok: bool) -> None:
    assert allowed(method, path) is ok
    assert len(ALLOWED) == 15


# ---- the middleware on the real app --------------------------------------------------------------
@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Any]:
    async for a in book_app(settings):
        yield a


async def _locked(app: Any, uid: str | None = None) -> str:
    state = await app.state.book_lock.set(uid or owner_uid(), "bk_0123456789abcdef", now=T0)
    return str(state.id)


async def test_unlocked_owner_sessions_are_untouched(app: Any) -> None:
    async with sign_in(app) as c:
        assert (await c.get("/auth/me")).json() == {"email": OWNER}


async def test_a_guest_lock_holds_every_cookie_session_of_the_owner(app: Any) -> None:
    async with sign_in(app) as presenting, sign_in(app) as older:
        lock_id = await _locked(app)
        for c in (presenting, older):
            r = await c.get("/auth/me")
            assert r.status_code == 423 and r.json()["error"] == "show_locked"
            assert r.json()["lock_id"] == lock_id and r.headers["cache-control"] == "no-store"
            home = await c.get("/", follow_redirects=False)
            assert home.status_code == 302 and home.headers["location"] == "/book/show"
            for path in ("/v1/vault", "/v1/memory", "/v1/permissions", "/v1/usage"):
                assert (await c.get(path)).status_code == 423, path
            chat = await c.post("/v1/chat", json={"message": "hi"}, headers=CSRF)
            assert chat.status_code == 423
            assert (await c.post("/v1/book/open", json={}, headers=CSRF)).status_code == 423
            assert (await c.get("/book/show")).status_code == 200
            assert (await c.get("/static/console.css")).status_code == 200
            assert (await c.get("/health")).status_code == 200
            assert (await c.get("/console/config")).status_code == 200
            assert (await c.post("/v1/book/close", headers=CSRF)).status_code != 423
        out = await presenting.post("/auth/logout", headers=CSRF)
        assert out.status_code == 200
    async with sign_in(app) as fresh:  # a NEW sign-in after log-out is locked too
        assert (await fresh.get("/auth/me")).status_code == 423


async def test_bearer_callers_are_untouched(app: Any) -> None:
    await _locked(app)
    async with AsyncClient(transport=app.transport, base_url="http://test", headers=BEARER) as cli:
        r = await cli.post("/v1/chat", json={"message": "hello"})
        assert r.status_code == 200


async def test_a_lock_on_one_owner_holds_the_other_owners_too(app: Any) -> None:
    lock_id = await _locked(app, owner_uid(SECOND_OWNER))
    async with sign_in(app) as c:
        r = await c.get("/auth/me")
        assert r.status_code == 423 and "lock_id" not in r.json()  # not his lock to lift
    async with sign_in(app, SECOND_OWNER) as c2:
        assert (await c2.get("/auth/me")).json()["lock_id"] == lock_id


async def test_an_unreadable_lock_closes_everything_but_the_allowed_routes(app: Any) -> None:
    app.state.book_docs.fail_reads = True
    async with sign_in(app) as c:
        r = await c.get("/auth/me")
        assert r.status_code == 503 and r.json()["error"] == "show_lock_unreadable"
        assert (await c.get("/book/show")).status_code == 200
        assert (await c.get("/health")).status_code == 200


async def test_the_passkey_reset_stays_reachable_and_still_wants_a_fresh_sign_in(
    app: Any,
) -> None:
    async with sign_in(app, fresh=False) as c:
        await _locked(app)
        r = await c.post("/v1/passkeys/reset", headers=CSRF)
        assert r.status_code == 403 and r.json()["reason"] == "reauth"  # reached, refused
        cancel = await c.post("/v1/passkeys/reset/cancel", json={}, headers=CSRF)
        assert cancel.status_code == 423  # would show the owner's passkeys without a proof


def test_the_middleware_is_pure_asgi() -> None:
    assert not hasattr(ShowLockMiddleware, "dispatch")


class StaleCache:
    """Another instance's lock store: its cached read still says "unlocked" (<= 3 s)."""

    def __init__(self, real: DocShowLock) -> None:
        self.real = real

    async def get(self, uid: str) -> Any:
        return None

    async def refresh(self, uid: str) -> Any:
        return await self.real.refresh(uid)


async def test_the_presenting_browser_is_held_even_through_a_stale_cache(app: Any) -> None:
    from book_app_fakes import open_book, register_passkey

    async with sign_in(app) as presenting, sign_in(app, fresh=False) as older:
        auth = await register_passkey(presenting)
        await open_book(presenting, auth, "guest")
        real = app.state.book_lock
        app.state.book_lock = StaleCache(real)
        assert (await presenting.get("/auth/me")).status_code == 423  # its session says guest
        assert (await older.get("/auth/me")).status_code == 200  # within the 3 s window only
        app.state.book_lock = real
        state = await real.get(owner_uid())
        await real.lift(owner_uid(), state.id)  # lifted elsewhere: the flag clears itself
        app.state.book_lock = StaleCache(real)
        assert (await presenting.get("/auth/me")).status_code == 200
        assert (await presenting.get("/auth/me")).status_code == 200


async def test_refresh_skips_the_cache(docs: FlakyDocs) -> None:
    here, there = DocShowLock(docs), DocShowLock(docs)
    assert await here.get(UID) is None
    state = await there.set(UID, "bk_0123456789abcdef", now=T0)
    assert await here.get(UID) is None and await here.refresh(UID) == state
    assert await here.get(UID) == state  # and the cache now knows
