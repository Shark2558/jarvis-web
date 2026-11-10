# tests/test_r6_fix_cookies.py -- R6 integrated review SEC-4: the cookies after a guest show.
# (a) At a guest open the presenting browser's session becomes a show-only marker (no owner e-mail
#     key), accepted only by the show routes, `/v1/book/show/lock` and `/v1/book/resume`.
# (b) Resume and the emergency unlock record `sessions_valid_after = now` for the owners (read with
#     the lock, cached <= 3 s); the middleware clears any owner cookie issued before it, so a cookie
#     copied during the show and a sign-in minted under the lock are refused after Resume; the
#     resuming browser is re-stamped and keeps working.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from book_app_fakes import (
    CSRF,
    ORIGIN,
    SECOND_OWNER,
    book,
    book_app,
    open_book,
    owner_uid,
    proof,
    register_passkey,
    sign_in,
)
from book_show_fakes import FlakyDocs
from httpx import ASGITransport, AsyncClient
from passkey_fakes import SoftAuthenticator

from jarvis.api import auth
from jarvis.buildbook.lock import DocShowLock
from jarvis.config import Settings

ME = "/auth/me"


@asynccontextmanager
async def copy_of(app: Any, c: AsyncClient) -> AsyncIterator[AsyncClient]:
    """Another device holding the cookie the guest copied out of the presenting browser."""
    jar = httpx.Cookies()
    for cookie in c.cookies.jar:
        jar.set(cookie.name, cookie.value or "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN, cookies=jar) as d:
        yield d


async def _guest_show(c: AsyncClient) -> tuple[SoftAuthenticator, dict[str, Any], str]:
    auth_ = await register_passkey(c)
    opened = await open_book(c, auth_, "guest")
    lock = (await c.get("/v1/book/show/lock")).json()
    return auth_, opened, lock["id"]


async def _resume(c: AsyncClient, auth_: SoftAuthenticator, lock_id: str) -> httpx.Response:
    body = {"proof": await proof(c, auth_, "book_resume", lock_id)}
    return await c.post("/v1/book/resume", json=body, headers=CSRF)


# ---- (a) the presenting browser holds a show-only marker -------------------------------------
async def test_a_guest_open_leaves_only_a_show_marker_in_the_presenting_browser(
    settings: Settings,
) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            _, opened, lock_id = await _guest_show(c)
            token = opened["token"]
            # the show routes, the lock route and Resume accept the marker
            assert (await c.get("/v1/book/show/script", headers=book(token))).status_code == 200
            assert (await c.post("/v1/book/show/beat", headers=book(token))).status_code == 200
            assert (await c.get("/v1/book/show/lock")).json()["id"] == lock_id
            assert (await c.get(ME)).status_code == 423  # held by the lock
            # with the lock gone WITHOUT a Resume (nothing recorded), the marker is still no owner
            await app.state.book_lock.lift(owner_uid(), lock_id)
            assert (await c.get(ME)).status_code == 401
            assert (await c.get("/v1/book")).status_code == 401
            assert (await c.post("/v1/book/close", headers=book(token))).status_code == 200


async def test_the_marker_asks_for_no_ceremony_but_its_resume(settings: Settings) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            _, _, lock_id = await _guest_show(c)
            for purpose, target in (("book_open", "owner"), ("add", None), ("book_open", "guest")):
                body: dict[str, Any] = {"purpose": purpose}
                if target is not None:
                    body["target"] = target
                r = await c.post("/v1/passkeys/challenge", json=body, headers=CSRF)
                assert r.status_code == 401, purpose
            body = {"purpose": "book_resume", "target": lock_id}
            r = await c.post("/v1/passkeys/challenge", json=body, headers=CSRF)
            assert r.status_code == 200
            await app.state.book_lock.lift(owner_uid(), lock_id)
            r = await c.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
            assert r.status_code == 401  # the marker never opens the book


# ---- (b) after Resume, every cookie issued before it is refused ---------------------------------
async def test_a_cookie_copied_during_the_show_is_refused_after_resume(settings: Settings) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            auth_, _, lock_id = await _guest_show(c)
            async with copy_of(app, c) as copied:
                assert (await copied.get(ME)).status_code == 423
                r = await _resume(c, auth_, lock_id)
                assert r.status_code == 200 and r.json() == {"resumed": True}
                assert (await c.get(ME)).status_code == 200  # the resuming browser: re-stamped
                assert (await copied.get(ME)).status_code == 401
                assert (await copied.get("/v1/book/show/lock")).status_code == 401


async def test_a_sign_in_minted_under_the_lock_is_refused_after_resume(
    settings: Settings,
) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            auth_, _, lock_id = await _guest_show(c)
            async with sign_in(app, fresh=False) as minted, sign_in(app, SECOND_OWNER) as other:
                assert (await minted.get(ME)).status_code == 423
                assert (await other.get(ME)).status_code == 423
                assert (await _resume(c, auth_, lock_id)).status_code == 200
                assert (await minted.get(ME)).status_code == 401
                assert (await other.get(ME)).status_code == 401  # the lock held him too
            async with sign_in(app, fresh=False) as later:  # a sign-in after Resume is fine
                assert (await later.get(ME)).status_code == 200


async def test_the_owner_resuming_from_his_phone_keeps_his_phone(settings: Settings) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as phone, sign_in(app) as laptop:
            auth_, _, lock_id = await _guest_show(laptop)
            assert (await phone.get(ME)).status_code == 423
            assert (await _resume(phone, auth_, lock_id)).status_code == 200
            assert (await phone.get(ME)).status_code == 200
            assert (await phone.get("/v1/book")).status_code == 200
            # the presenting laptop: nothing of the owner's is left in its cookie
            assert (await laptop.get(ME)).status_code == 401
            assert (await laptop.get("/v1/book/show/lock")).status_code == 401


async def test_the_emergency_unlock_ends_every_cookie_too(settings: Settings) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            await _guest_show(c)
            async with copy_of(app, c) as copied:
                report = await app.state.book_service.emergency_unlock(
                    owner_uid(),
                    "lost my passkey",
                    now=datetime.now(UTC),
                    signed_out_before=auth.cookie_now(),
                )
                assert report.lifted is True
                assert (await copied.get(ME)).status_code == 401
                assert (await c.get(ME)).status_code == 401


# ---- the store: read with the lock (one document), cached <= 3 s, written at the lift ------------
async def test_sessions_valid_after_is_read_with_the_lock_and_cached() -> None:
    docs, t = FlakyDocs(), {"now": 100.0}  # MemoryDocs counts its reads
    here = DocShowLock(docs, owners=("u_a", "u_b"), clock=lambda: t["now"])
    there = DocShowLock(docs, owners=("u_a", "u_b"), clock=lambda: t["now"])
    assert await there.valid_after("u_b") is None and await there.get("u_b") is None
    state = await here.set("u_a", "bk_0123456789abcdef", now=datetime(2026, 11, 10, tzinfo=UTC))
    other = await here.set("u_b", "bk_fedcba9876543210", now=datetime(2026, 11, 10, tzinfo=UTC))
    assert await here.lift("u_a", state.id, signed_out_before=1_234.5) is True
    assert await here.valid_after("u_a") == 1_234.5 and await here.get("u_a") is None
    reads = docs.reads
    t["now"] += 2.9
    assert await there.valid_after("u_b") is None and docs.reads == reads  # cached <= 3 s
    t["now"] += 0.2
    assert await there.valid_after("u_b") == 1_234.5  # every owner the lock held
    assert await there.get("u_b") == other  # his own lock is kept, read in the same document
    assert docs.reads == reads + 1


class Stepped:
    """A monotonic clock that moves on as it is read: each read takes the next tick (the last one
    holds)."""

    def __init__(self, *ticks: float) -> None:
        self.ticks = list(ticks)

    def __call__(self) -> float:
        return self.ticks.pop(0) if len(self.ticks) > 1 else self.ticks[0]


async def test_the_mark_and_the_lock_come_from_one_read(settings: Settings) -> None:
    """Security re-review #5: the middleware read the mark and the lock as two cache lookups. With
    the 3 s entry expiring between them, a cookie from before a Resume met a stale "no mark", then a
    fresh "no lock", and passed as an owner session for that one request."""
    async for app in book_app(settings):
        async with sign_in(app) as copied:  # issued before the Resume below
            uid, docs = owner_uid(), app.state.book_docs
            here = DocShowLock(
                docs, owners=(uid, owner_uid(SECOND_OWNER)), clock=Stepped(100.0, 102.9, 103.1)
            )
            state = await here.set(
                uid, "bk_0123456789abcdef", now=datetime.now(UTC)
            )  # cached at 100
            there = DocShowLock(docs, owners=(uid, owner_uid(SECOND_OWNER)))
            assert await there.lift(uid, state.id, signed_out_before=auth.cookie_now())  # elsewhere
            app.state.book_lock = here  # this instance: its entry is fresh at 102.9, stale at 103.1
            assert (await copied.get(ME)).status_code in (401, 423)  # never 200
            assert (await copied.get(ME)).status_code == 401  # and once read again: signed out
