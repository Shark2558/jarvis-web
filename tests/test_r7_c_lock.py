# tests/test_r7_c_lock.py -- R7 Part C, D21 (docs/plans/r7-mobile.md): the app lock and "Sign out
# everywhere". The installed app's session (marked by the page when it opened at /?source=app; a
# mark only ever switches the lock ON) locks after 5 minutes with no request the owner made: a
# write with the CSRF header or the page's "I'm here" call counts; background polls and the
# /auth/me recheck never do. Locked, every route answers 423 device_locked except D21's
# never-locked list, until a device_unlock passkey check bound to THAT session. The lock stays OFF
# until a passkey has been registered from the app (his only passkey may be Windows Hello on the
# laptop: it must never lock him out). Sign out everywhere ends every older cookie within 3 s.
from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from passkey_fakes import SoftAuthenticator
from r7_fakes_c import (
    CSRF,
    ORIGIN,
    add_passkey,
    audit_entries,
    browser,
    http_routes,
    owner_uid,
    phone_app,
    phone_service,
    proof,
)

from jarvis.buildbook.lock import AFTER, DocShowLock
from jarvis.config import Settings
from jarvis.mobile.ports import never_locked
from jarvis.phone import applock
from jarvis.storage.docs import MemoryDocs, Set

IDLE = 5 * 60


@pytest.fixture
async def app(settings: Settings) -> Any:
    async with phone_app(settings) as a:
        yield a


async def armed_phone(app: Any, c: AsyncClient) -> SoftAuthenticator:
    """The owner's first passkey, made in the app's own session: the lock is now on there."""
    auth = await add_passkey(c, label="Phone")
    state = (await c.get("/v1/session/lock")).json()
    assert state["app"] is True and state["armed"] is True, state
    return auth


async def locked(c: AsyncClient) -> bool:
    r = await c.get("/v1/phone")
    if r.status_code == 423:
        assert r.json()["error"] == "device_locked"
        return True
    assert r.status_code == 200, r.text
    return False


async def unlock(c: AsyncClient, auth: SoftAuthenticator) -> Any:
    r = await c.post("/v1/session/unlock", json={}, headers=CSRF)
    assert r.status_code == 200 and r.json()["unlocked"] is False, r.text
    target = r.json()["target"]
    body = {"proof": await proof(c, auth, "device_unlock", target)}
    return await c.post("/v1/session/unlock", json=body, headers=CSRF)


# ---- OFF until a passkey was registered from the app -------------------------------------------
async def test_a_passkey_made_only_on_the_laptop_never_locks_the_phone(app: Any) -> None:
    async with browser(app) as laptop:
        await add_passkey(laptop)  # Windows Hello, say: it lives only on the laptop
    async with browser(app, from_app=True) as phone:
        state = (await phone.get("/v1/session/lock")).json()
        assert state == {**state, "app": True, "on": True, "armed": False, "waiting": True}
        app.state.phone_clock.advance(10 * 60)
        assert not await locked(phone)


async def test_an_ordinary_browser_is_never_locked(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(app, phone)
    async with browser(app) as tab:  # Chrome on the same phone, not the app
        app.state.phone_clock.advance(30 * 60)
        assert not await locked(tab)
        assert (await tab.get("/v1/session/lock")).json()["app"] is False


async def test_the_app_locks_after_five_minutes_away(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(app, phone)
        app.state.phone_clock.advance(IDLE - 1)
        assert not await locked(phone)  # a GET does not count: the clock keeps running
        app.state.phone_clock.advance(2)
        assert await locked(phone)
        r = await phone.post("/v1/chat", json={"message": "hi"}, headers=CSRF)
        assert r.status_code == 423 and r.json()["error"] == "device_locked"
        assert r.headers["cache-control"] == "no-store"
        # a write while locked does not count either: it stays locked
        assert await locked(phone)


async def test_background_polls_and_the_auth_recheck_are_not_activity(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(app, phone)
        for _ in range(10):  # the Home panel's poll and the recheck on every return, for 5 min
            app.state.phone_clock.advance(30)
            assert (await phone.get("/auth/me")).status_code == 200
            if app.state.phone_clock() - 1_794_565_800.0 < IDLE:
                assert (await phone.get("/v1/home")).status_code != 423
        app.state.phone_clock.advance(1)
        assert await locked(phone)
        assert (await phone.get("/auth/me")).status_code == 200  # never locked


async def test_a_write_or_the_im_here_call_counts(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(app, phone)
        app.state.phone_clock.advance(4 * 60)
        assert (await phone.post("/v1/session/here", headers=CSRF)).json() == {"ok": True}
        app.state.phone_clock.advance(4 * 60)
        assert not await locked(phone)
        r = await phone.post("/v1/phone/link-code", json={}, headers=CSRF)
        assert r.json()["needs"] == "passkey"  # a write (it asks for the passkey), and it counted
        app.state.phone_clock.advance(4 * 60)
        assert not await locked(phone)
        app.state.phone_clock.advance(IDLE + 1)
        assert await locked(phone)


def test_what_counts_as_activity() -> None:
    hdr = [(b"x-requested-with", b"JARVIS")]
    assert applock.counts_as_activity("POST", "/v1/chat", hdr)
    assert applock.counts_as_activity("POST", "/v1/session/here", hdr)
    assert not applock.counts_as_activity("POST", "/v1/chat", [])
    assert not applock.counts_as_activity("GET", "/v1/home", hdr)
    assert not applock.counts_as_activity("HEAD", "/v1/home", hdr)
    assert not applock.counts_as_activity("POST", "/v1/book/show/beat", hdr)  # a heartbeat
    assert not applock.counts_as_activity("POST", "/v1/brief/seen", hdr)


# ---- what still answers while locked ------------------------------------------------------------
async def test_every_never_locked_route_works_and_nothing_else_does(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(app, phone)
        app.state.phone_clock.advance(IDLE + 1)
        assert await locked(phone)
        for method, path in [
            ("GET", "/"),
            ("GET", "/static/console.js"),
            ("GET", "/console/config"),
            ("GET", "/auth/me"),
            ("GET", "/manifest.webmanifest"),
            ("GET", "/.well-known/assetlinks.json"),
            ("GET", "/v1/sos"),
            ("POST", "/app/share/in"),
        ]:
            r = await phone.request(method, path, headers=CSRF)
            assert r.status_code != 423, (method, path, r.status_code)
        r = await phone.post(
            "/v1/passkeys/challenge", json={"purpose": "device_unlock"}, headers=CSRF
        )
        assert r.status_code != 423
        r = await phone.post("/v1/session/unlock", json={}, headers=CSRF)
        assert r.status_code == 200 and r.json()["unlocked"] is False  # it wants the passkey
        open_ = []
        tried = 0
        for path, methods in http_routes(app):
            for method in sorted(methods - {"HEAD"}):
                if never_locked(method, path):
                    continue
                url = path.replace("{", "x").replace("}", "")  # a made-up value for each part
                r = await phone.request(method, url, headers=CSRF)
                tried += 1
                if r.status_code != 423:
                    open_.append((method, path, r.status_code))
        assert open_ == [] and tried > 200


async def test_the_unlock_is_bound_to_this_session(app: Any) -> None:
    async with browser(app, from_app=True) as phone, browser(app, from_app=True) as other:
        auth = await armed_phone(app, phone)
        app.state.phone_clock.advance(IDLE + 1)
        assert await locked(phone) and await locked(other)
        # a proof made for the other session's lock is refused here
        r = await other.post("/v1/session/unlock", json={}, headers=CSRF)
        other_target = r.json()["target"]
        r = await phone.post("/v1/session/unlock", json={}, headers=CSRF)
        mine = r.json()["target"]
        assert mine != other_target and mine.startswith("ss_") and len(mine) == 27
        stolen = await proof(other, auth, "device_unlock", other_target)
        r = await phone.post("/v1/session/unlock", json={"proof": stolen}, headers=CSRF)
        assert r.status_code == 403 and await locked(phone)
        # and its own proof opens only this session
        r = await unlock(phone, auth)
        assert r.status_code == 200 and r.json() == {"unlocked": True}
        assert not await locked(phone) and await locked(other)
        assert any(e.tool == "device_unlock" for e in audit_entries(app))


async def test_the_unlock_route_is_cookie_only_and_rate_limited(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        r = await anon.post("/v1/session/unlock", json={}, headers=CSRF)
        assert r.status_code == 401
        r = await anon.post(
            "/v1/session/unlock", json={}, headers={**CSRF, "Authorization": "Bearer cli-token"}
        )
        assert r.status_code == 403 and r.json()["error"] == "console_only"
    async with browser(app, from_app=True) as phone:
        await armed_phone(app, phone)
        app.state.phone_clock.advance(IDLE + 1)
        codes = [
            (await phone.post("/v1/session/unlock", json={}, headers=CSRF)).status_code
            for _ in range(6)
        ]
        assert codes[:5] == [200] * 5 and codes[5] == 429


async def test_the_page_can_only_switch_the_app_mark_on(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(app, phone)
        for body in ({"on": False}, {"app": False}):
            await phone.post("/v1/session/app", json=body, headers=CSRF)
            assert (await phone.get("/v1/session/lock")).json()["app"] is True
        app.state.phone_clock.advance(IDLE + 1)
        r = await phone.post("/v1/session/app", headers=CSRF)
        assert r.status_code == 423  # marking again never unlocks


async def test_switching_the_lock_off_takes_the_passkey_on_takes_nothing(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        auth = await armed_phone(app, phone)
        r = await phone.put("/v1/session/lock", json={"on": False}, headers=CSRF)
        assert r.status_code == 200 and r.json()["needs"] == "passkey" and r.json()["on"] is True
        target = r.json()["target"]
        body = {"on": False, "proof": await proof(phone, auth, "device_unlock", target)}
        r = await phone.put("/v1/session/lock", json=body, headers=CSRF)
        assert r.status_code == 200 and r.json()["on"] is False and r.json()["armed"] is False
        app.state.phone_clock.advance(IDLE + 60)
        assert not await locked(phone)
        r = await phone.put("/v1/session/lock", json={"on": True}, headers=CSRF)
        assert r.status_code == 200 and r.json()["armed"] is True
        app.state.phone_clock.advance(IDLE + 1)
        assert await locked(phone)


async def test_removing_the_phones_passkey_switches_the_lock_off(app: Any) -> None:
    async with browser(app) as laptop:
        laptop_key = await add_passkey(laptop)
    async with browser(app, from_app=True) as phone:
        phone_key = await add_passkey(phone, held=laptop_key, label="Phone")
        assert (await phone.get("/v1/session/lock")).json()["armed"] is True
        perms = app.state.permissions
        (mine,) = [k for k in await perms.passkeys.owned(owner_uid()) if k.label == "Phone"]
        await perms.passkeys.remove(owner_uid(), mine.id)
        phone_service(app).lock.forget(owner_uid())
        app.state.phone_clock.advance(IDLE + 60)
        assert not await locked(phone)
        del phone_key


async def test_a_lock_that_cannot_be_read_never_opens(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(app, phone)
        store = phone_service(app).store

        async def broken(uid: str) -> Any:
            raise RuntimeError("store down")

        store.owner = broken
        phone_service(app).lock.forget(owner_uid())
        r = await phone.get("/v1/phone")
        assert r.status_code == 503 and r.json()["error"] == "lock_unreadable"
    async with browser(app) as tab:  # an ordinary browser never reads the lock
        assert (await tab.get("/auth/me")).status_code == 200


# ---- sign out everywhere ------------------------------------------------------------------------
async def test_sign_out_everywhere_ends_every_older_cookie_at_once_here(app: Any) -> None:
    async with browser(app, from_app=True) as phone, browser(app) as laptop:
        assert (await phone.get("/auth/me")).status_code == 200
        r = await laptop.post("/v1/session/end-all", headers=CSRF)
        assert r.status_code == 200 and r.json()["ended"] is True
        assert (await phone.get("/auth/me")).status_code == 401
        assert (await laptop.get("/auth/me")).status_code == 200  # this browser stays signed in
        assert any(e.tool == "sessions_end_all" for e in audit_entries(app))


async def test_another_instance_sees_the_mark_within_three_seconds() -> None:
    class Tick:
        t = 100.0

        def __call__(self) -> float:
            return self.t

    docs, tick = MemoryDocs(), Tick()
    here, there = DocShowLock(docs, clock=tick), DocShowLock(docs, clock=tick)
    assert await there.valid_after("u_1") is None  # cached on "there"
    await here.end_sessions("u_1", before=5000.0)
    assert await here.valid_after("u_1") == 5000.0  # this instance at once
    tick.t += 2.9
    assert await there.valid_after("u_1") is None
    tick.t += 0.2  # 3.1 s: the other instance reads it again
    assert await there.valid_after("u_1") == 5000.0


async def test_ending_sessions_keeps_a_guest_lock_and_never_moves_the_mark_back() -> None:
    from datetime import UTC, datetime

    docs = MemoryDocs()
    lock = DocShowLock(docs)
    state = await lock.set("u_1", "bk_0123456789abcdef", now=datetime(2026, 11, 13, tzinfo=UTC))
    await lock.end_sessions("u_1", before=200.0)
    assert await lock.get("u_1") == state and await lock.valid_after("u_1") == 200.0
    await lock.end_sessions("u_1", before=100.0)
    assert await DocShowLock(docs).valid_after("u_1") == 200.0
    await docs.write([Set("jarvis_book_lock/u_2", {AFTER: 50.0})])
    await lock.end_sessions("u_2", before=60.0)
    raw = await docs.get("jarvis_book_lock/u_2")
    assert raw == {AFTER: 60.0}


async def test_sign_out_everywhere_needs_google_sign_in(settings: Settings) -> None:
    async with phone_app(settings, google=False, api_token=None) as token_app:
        async with AsyncClient(transport=ASGITransport(app=token_app), base_url=ORIGIN) as c:
            r = await c.post("/v1/session/end-all", headers=CSRF)
            assert r.status_code == 409 and r.json()["error"] == "needs_google"
