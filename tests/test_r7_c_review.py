# tests/test_r7_c_review.py -- R7 Part C after the three fresh-context reviews (security H1, M1, M2;
# code M1-M3; python M1-M5). The app lock follows the DEVICE, not the session: the first time a
# session is marked as the app's, a signed r7_dev cookie (HttpOnly, about 400 days, bound to the
# owner) is set; any later session of that owner that carries it is the app's too and, with the
# lock armed, starts LOCKED (signing out and in again opens nothing). The owner is never locked
# out: from another signed-in device he can switch the phone's lock off (laptop passkey) or unlink
# the phone (a fresh sign-in is enough), which disarms it. The door reads no body before the cheap
# checks; "last seen" is best-effort; the nonce lives longer than the clock skew allows a replay.
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest import mock

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from httpx import ASGITransport, AsyncClient
from r7_fakes import phone_key
from r7_fakes_c import (
    CSRF,
    HELLO,
    ORIGIN,
    OWNER,
    SECOND,
    T_START,
    add_passkey,
    browser,
    door,
    jar_with,
    link,
    link_code,
    linked_phone,
    owner_uid,
    phone_app,
    phone_service,
    proof,
    sign_in_again,
)

from jarvis.config import Settings
from jarvis.mobile import contract
from jarvis.mobile.ports import MobilePart, PhoneReply, PhoneRequest
from jarvis.permissions.errors import PasskeyDataUnreadable
from jarvis.phone import applock
from jarvis.phone.door import DoorGate, NonceStore
from jarvis.phone.handlers import Hello, canonical

IDLE = 5 * 60
DEV = applock.DEVICE_KEY


@pytest.fixture
async def app(settings: Settings) -> Any:
    async with phone_app(settings) as a:
        yield a


async def armed_phone(c: AsyncClient) -> Any:
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


def device_cookie(c: AsyncClient) -> str:
    value = c.cookies.get(DEV)
    assert value, "no r7_dev cookie in this browser"
    return value


# ---- security H1: the lock follows the device -------------------------------------------------
async def test_marking_the_app_session_sets_the_device_cookie(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        await sign_in_again(app, c)
        r = await c.post("/v1/session/app", headers=CSRF)
        header = next(h for h in r.headers.get_list("set-cookie") if h.startswith(f"{DEV}="))
        low = header.lower()
        assert "httponly" in low and "samesite=lax" in low and "path=/" in low
        age = int(low.split("max-age=")[1].split(";")[0])
        assert 399 * 86400 <= age <= 401 * 86400
        # signed for this owner: "<owner id>.<mac>", and nothing else
        uid, _, mac = device_cookie(c).partition(".")
        assert uid == owner_uid() and len(mac) >= 32


async def test_the_device_cookie_is_secure_where_the_session_cookie_is(settings: Settings) -> None:
    with mock.patch.object(Settings, "cookie_secure", True):
        async with phone_app(settings) as a:
            async with AsyncClient(transport=ASGITransport(app=a), base_url="https://test") as c:
                await sign_in_again(a, c)
                r = await c.post("/v1/session/app", headers=CSRF)
                header = next(
                    h for h in r.headers.get_list("set-cookie") if h.startswith(f"{DEV}=")
                )
                assert "secure" in header.lower()


async def test_scenario_a_sign_out_and_in_again_in_the_app_is_locked(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
        app.state.phone_clock.advance(IDLE + 1)
        assert await locked(phone)
        r = await phone.post("/auth/logout", headers=CSRF)  # the cover's "Sign out instead"
        assert r.status_code in (200, 204), r.text
        assert phone.cookies.get(DEV)  # signing out does not clear the device
        await sign_in_again(app, phone)  # one tap
        assert await locked(phone)  # born locked, whatever the page posts next
        r = await phone.post("/v1/session/app", headers=CSRF)
        assert r.status_code == 423 and r.json()["error"] == "device_locked"
        assert await locked(phone)


async def test_scenario_a_even_a_new_mark_never_starts_the_clock_when_armed(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
    # the device cookie was lost (site data cleared) but the lock is armed: a new mark is locked
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        await sign_in_again(app, c)
        r = await c.post("/v1/session/app", headers=CSRF)
        assert r.status_code == 200
        assert await locked(c)


async def test_scenario_b_a_plain_tab_with_the_device_cookie_is_locked(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
        value = device_cookie(phone)
    tab = await jar_with(app, value)  # Chrome on the same phone: the same cookie jar
    async with tab:
        await sign_in_again(app, tab)
        assert await locked(tab)  # the first guarded request marks it and it is born locked
        assert (await tab.get("/v1/session/lock")).status_code == 423  # still, whatever it asks


async def test_scenario_b_the_laptop_without_it_is_never_locked(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
    async with browser(app) as laptop:
        app.state.phone_clock.advance(30 * 60)
        assert not await locked(laptop)
        assert (await laptop.get("/v1/session/lock")).json()["app"] is False


async def test_a_new_session_with_the_cookie_is_the_apps_even_before_the_lock_arms(
    app: Any,
) -> None:
    async with browser(app, from_app=True) as phone:
        value = device_cookie(phone)
    tab = await jar_with(app, value)
    async with tab:
        await sign_in_again(app, tab)
        assert not await locked(tab)  # marked by the first guarded request; nothing armed yet
        assert (await tab.get("/v1/session/lock")).json()["app"] is True


async def test_a_forged_or_other_owners_cookie_is_ignored(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
        mine = device_cookie(phone)
    async with browser(app, SECOND, from_app=True) as second:
        theirs = device_cookie(second)
    uid, _, mac = mine.partition(".")
    for bad in (
        theirs,  # another owner's device, on this owner's sign-in
        f"{uid}.{'0' * len(mac)}",  # a forged mac
        f"{uid}.{mac[:-1]}{'0' if mac[-1] != '0' else '1'}",  # one character off
        f"{owner_uid(SECOND)}.{mac}",  # his id with my mac
        uid,  # no mac at all
        "",
        "x" * 5000,
        mine.upper(),
    ):
        tab = await jar_with(app, bad)
        async with tab:
            await sign_in_again(app, tab)
            app.state.phone_clock.advance(IDLE + 60)
            assert not await locked(tab), bad[:20]
            assert (await tab.get("/v1/session/lock")).json()["app"] is False


async def test_the_device_cookie_survives_sign_out_everywhere_and_session_expiry(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
        before = device_cookie(phone)
        r = await phone.post("/v1/session/end-all", headers=CSRF)
        assert r.status_code == 200
        assert device_cookie(phone) == before
        state = (await phone.get("/v1/session/lock")).json()
        assert state["app"] is True  # security M2: the pressing browser keeps its app mark
        app.state.phone_clock.advance(IDLE + 1)
        assert await locked(phone)  # and the lock still engages (code M1)
        phone.cookies.delete("session")  # the session cookie expires
        assert phone.cookies.get(DEV) == before


async def test_end_all_keeps_the_session_id_the_unlock_is_bound_to(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        auth = await armed_phone(phone)
        app.state.phone_clock.advance(IDLE + 1)
        r = await phone.post("/v1/session/unlock", json={}, headers=CSRF)
        target = r.json()["target"]
        assert target.startswith("ss_")
        r = await phone.post(
            "/v1/session/unlock",
            json={"proof": await proof(phone, auth, "device_unlock", target)},
            headers=CSRF,
        )
        assert r.json() == {"unlocked": True}
        before = (await phone.post("/v1/session/unlock", json={}, headers=CSRF)).json()
        assert before == {"unlocked": True}
        await phone.post("/v1/session/end-all", headers=CSRF)
        assert not await locked(phone)  # the "last seen" came through the restamp too


# ---- never lock the owner out -------------------------------------------------------------------
async def test_the_laptop_passkey_switches_the_phones_lock_off(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        phone_auth = await armed_phone(phone)
        async with browser(app) as laptop:
            laptop_auth = await add_passkey(laptop, held=phone_auth, label="Laptop")
            r = await laptop.put("/v1/session/lock", json={"on": False}, headers=CSRF)
            assert r.json()["needs"] == "passkey"
            target = r.json()["target"]
            body = {"on": False, "proof": await proof(laptop, laptop_auth, "device_unlock", target)}
            r = await laptop.put("/v1/session/lock", json=body, headers=CSRF)
            assert r.status_code == 200 and r.json()["armed"] is False
        app.state.phone_clock.advance(IDLE + 60)
        phone_service(app).lock.forget(owner_uid())
        assert not await locked(phone)  # the phone is open again, with no passkey of its own


async def test_a_fresh_sign_in_on_the_laptop_unlinks_the_phone_and_disarms_the_lock(
    app: Any,
) -> None:
    async with browser(app, from_app=True) as phone:
        auth = await armed_phone(phone)
        device, _ = await linked_phone(app, phone, auth)
        async with browser(app) as laptop:  # a fresh Google sign-in, nothing else
            r = await laptop.post(f"/v1/phone/{device}/unlink", headers=CSRF)
            assert r.status_code == 200
        app.state.phone_clock.advance(IDLE + 60)
        assert not await locked(phone)
        state = (await phone.get("/v1/session/lock")).json()
        assert state["armed"] is False and state["on"] is True  # it re-arms with a new passkey


async def test_the_lock_stays_off_until_a_passkey_was_registered_from_the_app(app: Any) -> None:
    async with browser(app) as laptop:
        await add_passkey(laptop)
    async with browser(app, from_app=True) as phone:
        value = device_cookie(phone)
        app.state.phone_clock.advance(30 * 60)
        assert not await locked(phone)
    tab = await jar_with(app, value)
    async with tab:
        await sign_in_again(app, tab)
        app.state.phone_clock.advance(30 * 60)
        assert not await locked(tab)


# ---- security M2 / code M1: "Sign out everywhere" keeps the pressing browser's marks ------------
async def test_end_all_keeps_app_session_and_seen(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
        app.state.phone_clock.advance(IDLE - 30)
        await phone.post("/v1/session/end-all", headers=CSRF)
        state = (await phone.get("/v1/session/lock")).json()
        assert state["app"] is True and state["armed"] is True
        app.state.phone_clock.advance(IDLE + 1)
        assert await locked(phone)


# ---- security M1: the door reads no body before the cheap checks --------------------------------
class Counting:
    """An async body that counts how many chunks the server pulled."""

    def __init__(self, chunks: int = 50, size: int = 1024) -> None:
        self.pulled, self._n, self._size = 0, chunks, size

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[bytes]:
        for _ in range(self._n):
            self.pulled += 1
            yield b"x" * self._size


async def test_the_door_reads_no_body_before_header_flood_device_and_time(app: Any) -> None:
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    now = int(app.state.phone_clock())
    good_head = contract.header_value(device, now, "ab" * 16, b"sig")
    cases = {
        "no header": {},
        "bad shape": {"X-Jarvis-Phone": "v1;nonsense"},
        "unknown device": {
            "X-Jarvis-Phone": contract.header_value("ph_000000000000", now, "ab" * 16, b"s")
        },
        "stale time": {"X-Jarvis-Phone": contract.header_value(device, now - 500, "ab" * 16, b"s")},
        "bad nonce shape": {"X-Jarvis-Phone": good_head.replace("n=" + "ab" * 16, "n=zz")},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        for what, headers in cases.items():
            body = Counting()
            r = await anon.post("/phone/v1/inbox", content=body, headers=headers)
            assert r.status_code == 401 and r.content == b"", what
            assert body.pulled == 0, f"{what}: the door read {body.pulled} chunks"
    del key


async def test_the_flood_limit_comes_before_any_body_is_read(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        for _ in range(61):
            r = await anon.post("/phone/v1/hello", content=b"", headers={"X-Jarvis-Phone": "x"})
        body = Counting()
        r = await anon.post("/phone/v1/hello", content=body, headers={"X-Jarvis-Phone": "x"})
        assert r.status_code == 401 and body.pulled == 0


async def test_a_signed_oversize_body_is_read_no_further_than_the_cap(app: Any) -> None:
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    now = int(app.state.phone_clock())
    head = contract.header_value(device, now, "cd" * 16, b"not-a-signature")
    body = Counting(chunks=2000, size=1024)  # 2 MB against the hello's cap
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        r = await anon.post("/phone/v1/hello", content=body, headers={"X-Jarvis-Phone": head})
    assert r.status_code == 401 and r.content == b""
    assert body.pulled < 200
    del key


# ---- code M2 / python M2: "last seen" is best-effort -------------------------------------------
async def test_a_failed_last_seen_write_never_refuses_the_request(app: Any) -> None:
    class Seen:
        got: list[PhoneRequest] = []

        async def __call__(self, req: PhoneRequest) -> PhoneReply:
            self.got.append(req)
            return PhoneReply(200, {"ok": True})

    seen = Seen()
    app.state.r7_parts["body"] = MobilePart(
        "body", services={"door": {"health": seen, "sos": seen}}
    )
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    svc = phone_service(app)
    real = svc.store.update_phone

    async def broken(*a: Any, **k: Any) -> bool:
        raise RuntimeError("firestore contention")

    svc.store.update_phone = broken
    r = await door(app, key, device, "sos", {"v": 1})
    assert r.status_code == 200 and len(seen.got) == 1  # the SOS went through
    assert device not in svc.handlers._touched  # not marked as written
    svc.store.update_phone = real
    r = await door(app, key, device, "sos", {"v": 1})
    assert r.status_code == 200 and device in svc.handlers._touched  # retried at once


# ---- python M5: the nonce outlives the clock skew -----------------------------------------------
def test_the_nonce_store_lives_longer_than_twice_the_skew(settings: Settings) -> None:
    for skew in (30, 120, 300):
        gate = DoorGate(phone_service_store(), skew_s=skew)
        assert gate.nonces.ttl_s >= 2 * skew + 60


def phone_service_store() -> Any:
    from jarvis.phone.store import PhoneStore
    from jarvis.storage.docs import MemoryDocs

    return PhoneStore(MemoryDocs(), prefix="t_", owners=[owner_uid()])


async def test_a_replay_at_the_far_edge_of_the_biggest_skew_is_refused(settings: Settings) -> None:
    async with phone_app(settings, phone_clock_skew_s=300) as app:
        async with browser(app) as c:
            device, key = await linked_phone(app, c)
        signed_at, nonce = int(T_START), "ee" * 16
        app.state.phone_clock.t = signed_at - 300
        r = await door(app, key, device, "hello", HELLO, t=signed_at, nonce=nonce)
        assert r.status_code == 200
        app.state.phone_clock.t = signed_at + 300  # 600 s later, still inside the window
        r = await door(app, key, device, "hello", HELLO, t=signed_at, nonce=nonce)
        assert r.status_code == 401


def test_the_nonce_store_keeps_a_nonce_for_its_whole_life() -> None:
    n = NonceStore(ttl_s=100)
    assert n.add("a", 0.0)
    assert n.seen("a", 99.9) and not n.add("a", 99.9)
    assert not n.seen("a", 100.0)


# ---- python M4: the security paths --------------------------------------------------------------
async def test_the_skew_boundary_is_exact(app: Any) -> None:
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    now = int(app.state.phone_clock())
    for offset, status in ((120, 200), (-120, 200), (121, 401), (-121, 401)):
        r = await door(app, key, device, "hello", HELLO, t=now - offset)
        assert r.status_code == status, offset


async def _raw_signed(app: Any, key: Any, device: str, mangle: Any) -> int:
    now = int(app.state.phone_clock())
    body = contract.canonical_json(HELLO)
    nonce = "ab" * 16
    string = contract.signing_string(device, now, nonce, "POST", "/phone/v1/hello", body)
    der = key.sign(string, ec.ECDSA(hashes.SHA256()))
    head = contract.header_value(device, now, nonce, mangle(der))
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        return (
            await c.post("/phone/v1/hello", content=body, headers={"X-Jarvis-Phone": head})
        ).status_code


def _raw(der: bytes) -> bytes:
    r, s = decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _high_s(der: bytes) -> bytes:
    r, s = decode_dss_signature(der)
    order = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
    return encode_dss_signature(r, order - s)


async def test_a_raw_r_s_signature_is_refused_and_der_is_the_only_form(app: Any) -> None:
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    assert await _raw_signed(app, key, device, _raw) == 401


async def test_a_high_s_der_signature_is_accepted_like_the_keystores_own(app: Any) -> None:
    # Android's Keystore does not normalise S: both halves verify; the nonce is what stops a replay
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    assert await _raw_signed(app, key, device, _high_s) == 200


async def test_a_truncated_or_empty_signature_is_a_bare_401(app: Any) -> None:
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    assert await _raw_signed(app, key, device, lambda der: der[:-3]) == 401
    assert await _raw_signed(app, key, device, lambda der: b"\x00") == 401


async def test_one_code_cannot_link_five_phones_at_once(app: Any) -> None:
    async with browser(app) as c:
        code = await link_code(c)
    results = await asyncio.gather(*(link(app, code, phone_key()) for _ in range(5)))
    statuses = sorted(r.status_code for r, _ in results)
    assert statuses == [200, 403, 403, 403, 403]
    assert len((await phone_service(app).store.owner(owner_uid())).phones) == 1


async def test_the_three_phone_cap_holds_under_a_crowd(app: Any) -> None:
    async with browser(app) as c:
        for _ in range(3):
            await linked_phone(app, c)
        code = await link_code(c)
    results = await asyncio.gather(*(link(app, code, phone_key()) for _ in range(4)))
    assert sorted(r.status_code for r, _ in results) == [409, 409, 409, 409]
    assert len((await phone_service(app).store.owner(owner_uid())).phones) == 3


async def test_the_lock_tables_are_bounded_and_eviction_never_unlocks(app: Any) -> None:
    lock = phone_service(app).lock
    sessions = []
    for i in range(applock.SESSIONS_MAX + 40):
        s: dict[str, Any] = {applock.APP_KEY: 1.0}
        lock.touch(s, 1000.0 + i)
        sessions.append(s)
    assert len(lock._seen) <= applock.SESSIONS_MAX
    # the evicted session's own cookie still carries its time: older, never newer
    assert lock.last_seen(sessions[0]) == 1000.0
    for i in range(100):
        lock._pending[f"ss_{i}"] = (OWNER, frozenset(), 0.0)
        while len(lock._pending) > 64:
            lock._pending.popitem(last=False)
    assert len(lock._pending) <= 64


async def test_the_pending_registration_table_is_bounded(app: Any) -> None:
    async with browser(app) as laptop:
        await add_passkey(laptop)
    lock = phone_service(app).lock
    for i in range(80):
        await lock._note_registration(owner_uid(), f"ss_{i:024d}", 0.0)
    assert len(lock._pending) <= 64


async def test_a_session_with_no_owner_cannot_be_marked(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        r = await c.post("/v1/session/app", headers={**CSRF, "Authorization": "Bearer cli-token"})
        assert r.status_code == 200 and r.json() == {"app": False}
        assert DEV not in c.cookies


async def test_the_lock_switch_answers_503_when_passkeys_cannot_be_read(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
        perms = app.state.permissions

        async def broken(uid: str) -> bool:
            raise PasskeyDataUnreadable("unreadable")

        perms.passkey_required = broken
        r = await phone.put("/v1/session/lock", json={"on": False}, headers=CSRF)
        assert r.status_code == 503 and r.json()["error"] == "passkeys_unreadable"


async def test_the_armed_cache_follows_the_injected_clock(app: Any) -> None:
    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
        svc = phone_service(app)
        assert await svc.lock.armed(owner_uid()) is True
        await svc.store.set_lock(owner_uid(), False)  # behind the cache's back
        assert await svc.lock.armed(owner_uid()) is True  # still cached
        app.state.phone_clock.advance(applock.ARMED_CACHE_S + 1)
        assert await svc.lock.armed(owner_uid()) is False


# ---- python L2/L3/L4/L8, code L1 -----------------------------------------------------------------
class FakeRequest:
    def __init__(self, length: str | None, chunks: list[bytes]) -> None:
        self.headers = {} if length is None else {"content-length": length}
        self.pulled = 0
        self._chunks = chunks

    async def stream(self) -> AsyncIterator[bytes]:
        for c in self._chunks:
            self.pulled += 1
            yield c


async def test_capped_reads_only_ascii_digits_and_stops_at_the_cap() -> None:
    from jarvis.api.phone import _capped

    for bad in ("²", "٣", "1.5", "-1", "", " 5", "0x10", "1e3"):
        assert await _capped(FakeRequest(bad, [b"x"]), 100) is None, bad  # type: ignore[arg-type]
    assert await _capped(FakeRequest("200", [b"x"]), 100) is None  # type: ignore[arg-type]
    assert await _capped(FakeRequest("3", [b"abc"]), 100) == b"abc"  # type: ignore[arg-type]
    chunked = FakeRequest(None, [b"x" * 60] * 50)
    assert await _capped(chunked, 100) is None  # type: ignore[arg-type]
    assert chunked.pulled == 2


async def test_a_bad_content_length_to_the_door_is_a_bare_401(app: Any) -> None:
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    now = int(app.state.phone_clock())
    head = contract.header_value(device, now, "ab" * 16, b"s")
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        r = await anon.post(
            "/phone/v1/hello",
            content=b"{}",
            headers={"X-Jarvis-Phone": head, "Content-Length": "99999999"},
        )
    assert r.status_code in (401, 413)  # (the app-wide body limit may answer first)
    del key


async def test_the_link_body_is_capped_before_it_is_parsed(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        body = Counting(chunks=500, size=1024)
        r = await anon.post("/phone/link", content=body)
        assert r.status_code == 413
        assert body.pulled < 20


def test_a_deeply_nested_body_is_just_not_the_one_json_form() -> None:
    assert canonical(b"[" * 200_000, Hello) is None
    assert canonical(b'{"a":' * 5000, Hello) is None


async def test_the_link_code_is_stored_keyed_not_as_a_plain_sha256(app: Any) -> None:
    import hashlib

    async with browser(app) as c:
        code = await link_code(c)
    store = phone_service(app).store
    doc = await store.docs.get(store._code_path(owner_uid()))
    assert doc is not None
    assert doc["code_hash"] != hashlib.sha256(code.encode()).hexdigest()
    assert len(doc["code_hash"]) == 64
    r, _ = await link(app, code)
    assert r.status_code == 200


async def test_show_locked_outranks_device_locked(app: Any) -> None:
    # the show lock sits outside the app lock: a guest's lock answers show_locked, not device_locked
    from datetime import UTC, datetime

    async with browser(app, from_app=True) as phone:
        await armed_phone(phone)
        app.state.phone_clock.advance(IDLE + 1)
        await app.state.book_lock.set(
            owner_uid(), "bk_0123456789abcdef", now=datetime(2026, 11, 13, tzinfo=UTC)
        )
        r = await phone.get("/v1/phone")
        assert r.status_code == 423 and r.json()["error"] == "show_locked", r.text
