# evals/r7/phone.py
"""R7 eval, Part C (`phone`, BUILT): the phone link and its security (docs/plans/r7-mobile.md
D4-D6, D21; "Tests and evals per part", row C). Every case runs the real app (Google sign-in faked,
the real show lock and app lock inside the session middleware, software passkeys;
tests/r7_fakes_c.py):

    link_code        10 minutes, once, void after 5 wrong tries
    link_proof       with a passkey in force no code without a phone_link proof bound to the offer;
                     with none, an old sign-in is refused and a fresh one is enough
    link_shape       another package, a key off the curve, a short fingerprint: refused
    fourth_phone     a fourth phone is refused
    vectors          every shared vector gets the door's answer it names
    bare_401         a wrong key, a changed body, a stale time, a replayed nonce, an unlinked phone,
                     a query string: a bare 401; an unknown route a bare 404; no audit line
    no_v1_no_cookie  a good signature opens no /v1 route; the door sets no cookie
    asset_links      linked phones only, the one package and relation; gone after unlink
    unlink           the door closes at once
    end_all          "Sign out everywhere": the older cookie dies at once here, within 3 s elsewhere
    lock_idle        the app's session answers 423 device_locked after 5 minutes away
    never_locked     D21's list still answers while locked, other routes are 423
    unlock_bound     another session's device_unlock proof is refused; its own opens only it
    polls            with the Home panel polling and the /auth/me recheck, the lock still comes
    lock_waits       a passkey made only on the laptop never locks the phone
    device_lock      signing out and in again in the app, and a plain tab with the device cookie,
                     start locked; the laptop never is; a forged or foreign cookie is ignored
    recovery         never locked out: the laptop passkey switches the lock off, a fresh sign-in
                     unlinks the phone and disarms it
    skew             the clock window is exact (120 s in, 121 s out)
    body_cap         the link body is cut at its cap
    phone_rate       a phone's 31st request in a minute is refused with a bare 429
    end_all keeps    "Sign out everywhere" keeps the pressing browser's app mark

Negative controls (each must make EVERY case it names fail, so this part cannot pass whatever
it is given): the nonce store off, the signature check off, the lock exempting every route,
background polls counted as activity, the device cookie not checked / any cookie accepted / a mark
that starts the clock, the clock skew not checked, the link body cap off, the 3-phone cap off, the
code reusable, wrong tries never voiding, a point off the curve accepted, the unlock not bound to
the session, the per-phone rate off.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from r7_fakes import load_vectors, phone_key, sign_request  # noqa: E402
from r7_fakes_c import (  # noqa: E402
    CSRF,
    HELLO,
    ORIGIN,
    add_passkey,
    audit_entries,
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

from jarvis.config import LLMBackend, SessionBackend, Settings  # noqa: E402
from jarvis.mobile.ports import PACKAGE, MobilePart, PhoneReply, PhoneRequest  # noqa: E402
from jarvis.phone.applock import DEVICE_KEY  # noqa: E402
from jarvis.phone.store import Phone  # noqa: E402

PART = "phone"
BUILT = True
IDLE = 5 * 60
Case = Callable[[], Awaitable[list[str]]]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )


def _check(failures: list[str], ok: bool, what: str) -> None:
    if not ok:
        failures.append(what)


async def _status(c: AsyncClient) -> int:
    return (await c.get("/v1/phone")).status_code


# ---- linking ----------------------------------------------------------------------------------
async def link_code_rules() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as c:
            code = await link_code(c)
        _check(f, (await link(app, code))[0].status_code == 200, "a fresh code links")
        _check(f, (await link(app, code))[0].status_code == 403, "the code works once")
        async with browser(app) as c:
            code = await link_code(c)
        app.state.phone_clock.advance(601)
        _check(f, (await link(app, code))[0].status_code == 403, "the code lasts 10 minutes")
        async with browser(app) as c:
            code = await link_code(c)
        wrong = "22222222" if code != "22222222" else "33333333"
        for _ in range(5):
            await link(app, wrong)
        _check(f, (await link(app, code))[0].status_code == 403, "5 wrong tries void the code")
    return f


async def link_proof() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app, fresh=False) as c:
            r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
            _check(f, r.status_code == 403, "an old sign-in with no passkey shows no code")
        async with browser(app) as c:
            auth = await add_passkey(c)
            r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
            target = r.json().get("target", "")
            _check(f, "code" not in r.json() and target.startswith("pl_"), "no code without proof")
            other = await proof(c, auth, "phone_link", "pl_000000000000")
            r = await c.post(
                "/v1/phone/link-code", json={"id": target, "proof": other}, headers=CSRF
            )
            _check(f, r.status_code == 403, "a proof for another offer is refused")
            good = await proof(c, auth, "phone_link", target)
            r = await c.post(
                "/v1/phone/link-code", json={"id": target, "proof": good}, headers=CSRF
            )
            _check(f, "code" in r.json(), "its own proof shows the code")
    return f


async def link_shape() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as c:
            code = await link_code(c)
        for over, what in (
            ({"package": "com.example.other"}, "another package"),
            ({"public_key": "04" + "00" * 64}, "a key off the curve"),
            ({"fingerprint": "ab" * 31}, "a short fingerprint"),
        ):
            r, _ = await link(app, code, **over)
            _check(f, r.status_code == 422, f"{what} is refused")
        _check(f, (await link(app, code))[0].status_code == 200, "a malformed request is no try")
    return f


async def fourth_phone() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as c:
            for _ in range(3):
                await linked_phone(app, c)
            code = await link_code(c)
        r, _ = await link(app, code)
        _check(f, r.status_code == 409, "a fourth phone is refused")
    return f


# ---- the door -------------------------------------------------------------------------------
class _Seen:
    def __init__(self) -> None:
        self.got: list[str] = []

    async def __call__(self, req: PhoneRequest) -> PhoneReply:
        self.got.append(req.route)
        return PhoneReply(200, {"ok": True})


async def _post(app: Any, path: str, body: bytes, header: str | None) -> Any:
    headers = {"X-Jarvis-Phone": header} if header else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        return await c.post(path, content=body, headers=headers)


async def vectors() -> list[str]:
    f: list[str] = []
    v = load_vectors()
    async with phone_app(_settings()) as app:
        seen = _Seen()
        app.state.r7_parts["body"] = MobilePart(
            "body", services={"door": {"health": seen, "sos": seen}}
        )
        app.state.phone_clock.t = float(v["server_time_for_cases"])
        await phone_service(app).store.put_phone(
            owner_uid(),
            Phone(
                id=v["device_id"],
                model="phone",
                public_key=v["public_key_x962_hex"],
                package=PACKAGE,
                fingerprint=v["signing_fingerprint_hex"],
                linked_at=float(v["server_time_for_cases"]) - 60,
            ),
        )
        for case in v["cases"]:
            r = await _post(app, case["path"], case["body"].encode(), case["header"])
            accepted = r.status_code not in (401, 404)
            _check(f, accepted is (case["door"] == "accept"), f"vector {case['name']}")
    return f


async def bare_401() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as c:
            device, key = await linked_phone(app, c)
        before = len(audit_entries(app))
        now = app.state.phone_clock()
        nonce = "cd" * 16
        _check(f, (await door(app, key, device, "hello", HELLO, nonce=nonce)).status_code == 200,
               "a good hello passes")  # fmt: skip
        tries = {
            "a replayed nonce": await door(app, key, device, "hello", HELLO, nonce=nonce),
            "a wrong key": await door(app, phone_key(), device, "hello", HELLO),
            "a stale time": await door(app, key, device, "hello", HELLO, t=now - 121),
            "a query string": await door(
                app, key, device, "hello", HELLO, url="/phone/v1/hello?x=1"
            ),
            "an unknown phone": await door(app, key, "ph_000000000000", "hello", HELLO),
        }
        headers, body = sign_request(key, device, "POST", "/phone/v1/hello", HELLO, t=int(now))
        tries["a changed body"] = await _post(
            app, "/phone/v1/hello", body + b" ", headers["X-Jarvis-Phone"]
        )
        for what, r in tries.items():
            _check(f, r.status_code == 401 and r.content == b"", f"{what}: a bare 401")
        r = await _post(app, "/phone/v1/vault", body, headers["X-Jarvis-Phone"])
        _check(f, r.status_code == 404 and r.content == b"", "an unknown route: a bare 404")
        _check(f, len(audit_entries(app)) == before, "no audit line for any refusal")
    return f


async def no_v1_no_cookie() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as c:
            device, key = await linked_phone(app, c)
        headers, body = sign_request(key, device, "POST", "/phone/v1/hello", HELLO)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
            for method, path in (("POST", "/v1/chat"), ("GET", "/v1/vault"), ("GET", "/v1/phone")):
                r = await anon.request(method, path, content=body, headers={**headers, **CSRF})
                _check(f, r.status_code == 401, f"{path} is not opened by a signature")
        r = await door(app, key, device, "hello", HELLO)
        _check(f, r.status_code == 200 and "set-cookie" not in r.headers, "the door sets no cookie")
    return f


async def asset_links() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
            _check(f, (await anon.get("/.well-known/assetlinks.json")).json() == [], "none linked")
        async with browser(app) as c:
            device, _ = await linked_phone(app, c)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
            st = (await anon.get("/.well-known/assetlinks.json")).json()
        ok = (
            len(st) == 1
            and st[0]["relation"] == ["delegate_permission/common.handle_all_urls"]
            and st[0]["target"]["package_name"] == PACKAGE
            and len(st[0]["target"]["sha256_cert_fingerprints"]) == 1
        )
        _check(f, ok, "the one package, the one relation, the linked phone's fingerprint")
        async with browser(app) as c:
            await c.post(f"/v1/phone/{device}/unlink", headers=CSRF)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
            _check(
                f,
                (await anon.get("/.well-known/assetlinks.json")).json() == [],
                "gone after unlink",
            )
    return f


async def unlink() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as c:
            device, key = await linked_phone(app, c)
            _check(f, (await door(app, key, device, "hello", HELLO)).status_code == 200, "linked")
            await c.post(f"/v1/phone/{device}/unlink", headers=CSRF)
        _check(f, (await door(app, key, device, "hello", HELLO)).status_code == 401, "door closed")
    return f


async def end_all() -> list[str]:
    from jarvis.buildbook.lock import DocShowLock
    from jarvis.storage.docs import MemoryDocs

    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app, from_app=True) as phone, browser(app) as laptop:
            await laptop.post("/v1/session/end-all", headers=CSRF)
            _check(f, (await phone.get("/auth/me")).status_code == 401, "the older cookie dies")
            _check(f, (await laptop.get("/auth/me")).status_code == 200, "this browser stays")
        async with browser(app, from_app=True) as phone2:
            await _armed(app, phone2)
            await phone2.post("/v1/session/end-all", headers=CSRF)
            state = (await phone2.get("/v1/session/lock")).json()
            _check(f, state.get("app") is True, "end-all keeps the pressing browser's app mark")

    class Tick:
        t = 0.0

        def __call__(self) -> float:
            return self.t

    tick, docs = Tick(), MemoryDocs()
    here, there = DocShowLock(docs, clock=tick), DocShowLock(docs, clock=tick)
    await there.valid_after("u_1")
    await here.end_sessions("u_1", before=10.0)
    tick.t = 3.01
    _check(f, await there.valid_after("u_1") == 10.0, "another instance within 3 seconds")
    return f


# ---- the app lock ---------------------------------------------------------------------------
async def _armed(app: Any, c: AsyncClient) -> Any:
    auth = await add_passkey(c, label="Phone")
    await c.get("/v1/session/lock")
    return auth


async def lock_idle() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app, from_app=True) as c:
            await _armed(app, c)
            app.state.phone_clock.advance(IDLE - 1)
            _check(f, await _status(c) == 200, "not yet")
            app.state.phone_clock.advance(2)
            r = await c.get("/v1/phone")
            ok = r.status_code == 423 and r.json().get("error") == "device_locked"
            _check(f, ok, "423 device_locked after 5 minutes away")
    return f


async def never_locked() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app, from_app=True) as c:
            await _armed(app, c)
            app.state.phone_clock.advance(IDLE + 1)
            for method, path in (("GET", "/"), ("GET", "/auth/me"), ("GET", "/console/config"),
                                 ("GET", "/static/console.js"), ("GET", "/v1/sos"),
                                 ("GET", "/.well-known/assetlinks.json")):  # fmt: skip
                r = await c.request(method, path)
                _check(f, r.status_code != 423, f"{method} {path} answers while locked")
            r = await c.post("/v1/session/unlock", json={}, headers=CSRF)
            _check(f, r.status_code == 200, "the unlock route answers while locked")
            for method, path in (("GET", "/v1/vault"), ("POST", "/v1/chat"),
                                 ("GET", "/v1/sessions"), ("GET", "/v1/permissions"),
                                 ("POST", "/v1/session/here")):  # fmt: skip
                r = await c.request(method, path, headers=CSRF)
                _check(f, r.status_code == 423, f"{method} {path} is locked")
    return f


async def unlock_bound() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app, from_app=True) as a, browser(app, from_app=True) as b:
            auth = await _armed(app, a)
            app.state.phone_clock.advance(IDLE + 1)
            t_b = (await b.post("/v1/session/unlock", json={}, headers=CSRF)).json()["target"]
            t_a = (await a.post("/v1/session/unlock", json={}, headers=CSRF)).json()["target"]
            stolen = await proof(b, auth, "device_unlock", t_b)
            r = await a.post("/v1/session/unlock", json={"proof": stolen}, headers=CSRF)
            _check(f, r.status_code == 403, "another session's proof is refused")
            own = await proof(a, auth, "device_unlock", t_a)
            r = await a.post("/v1/session/unlock", json={"proof": own}, headers=CSRF)
            _check(f, r.status_code == 200 and await _status(a) == 200, "its own proof opens it")
            _check(f, await _status(b) == 423, "and only it")
    return f


async def polls() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app, from_app=True) as c:
            await _armed(app, c)
            for _ in range(10):
                app.state.phone_clock.advance(30)
                await c.get("/auth/me")
                await c.get("/v1/home")
            app.state.phone_clock.advance(1)
            _check(f, await _status(c) == 423, "background polls never keep it open")
    return f


async def lock_waits() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as laptop:
            await add_passkey(laptop)
        async with browser(app, from_app=True) as c:
            app.state.phone_clock.advance(30 * 60)
            _check(f, await _status(c) == 200, "a laptop-only passkey never locks the phone")
    return f


async def device_lock() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app, from_app=True) as phone:
            await _armed(app, phone)
            value = phone.cookies.get(DEVICE_KEY) or ""
            app.state.phone_clock.advance(IDLE + 1)
            await phone.post("/auth/logout", headers=CSRF)  # the cover's "Sign out instead"
            await sign_in_again(app, phone)  # one tap
            _check(f, await _status(phone) == 423, "sign out and in again in the app is locked")
        tab = await jar_with(app, value)  # Chrome on the same phone: the same jar
        async with tab:
            await sign_in_again(app, tab)
            _check(f, await _status(tab) == 423, "a plain tab with the device cookie is locked")
        async with browser(app) as laptop:
            app.state.phone_clock.advance(IDLE + 60)
            _check(f, await _status(laptop) == 200, "the laptop without it is never locked")
        uid, _, mac = value.partition(".")
        for bad in (f"{uid}.{'0' * len(mac)}", f"u_other.{mac}", uid, ""):
            fake = await jar_with(app, bad)
            async with fake:
                await sign_in_again(app, fake)
                _check(f, await _status(fake) == 200, "a forged or foreign cookie is ignored")
    return f


async def recovery() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app, from_app=True) as phone:
            phone_auth = await _armed(app, phone)
            async with browser(app) as laptop:
                laptop_auth = await add_passkey(laptop, held=phone_auth, label="Laptop")
                r = await laptop.put("/v1/session/lock", json={"on": False}, headers=CSRF)
                target = r.json().get("target", "")
                body = {
                    "on": False,
                    "proof": await proof(laptop, laptop_auth, "device_unlock", target),
                }
                r = await laptop.put("/v1/session/lock", json=body, headers=CSRF)
                _check(f, r.status_code == 200, "the laptop passkey switches the lock off")
            app.state.phone_clock.advance(IDLE + 60)
            phone_service(app).lock.forget(owner_uid())
            _check(f, await _status(phone) == 200, "the phone is open again")
    async with phone_app(_settings()) as app:
        async with browser(app, from_app=True) as phone:
            auth = await _armed(app, phone)
            device, _ = await linked_phone(app, phone, auth)
            async with browser(app) as laptop:
                await laptop.post(f"/v1/phone/{device}/unlink", headers=CSRF)
            app.state.phone_clock.advance(IDLE + 60)
            _check(f, await _status(phone) == 200, "a fresh sign-in unlinks and disarms")
    return f


async def skew() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as c:
            device, key = await linked_phone(app, c)
        now = int(app.state.phone_clock())
        for offset, want in ((120, 200), (-120, 200), (121, 401), (-121, 401)):
            r = await door(app, key, device, "hello", HELLO, t=now - offset)
            _check(f, r.status_code == want, f"{offset} s of skew answers {want}")
    return f


async def body_cap() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
            r = await anon.post("/phone/link", content=b"x" * 8192)
            _check(f, r.status_code == 413, "the link body is cut at 4 KB")
    return f


async def phone_rate() -> list[str]:
    f: list[str] = []
    async with phone_app(_settings()) as app:
        async with browser(app) as c:
            device, key = await linked_phone(app, c)
        codes = [(await door(app, key, device, "hello", HELLO)).status_code for _ in range(31)]
        _check(f, codes[:30] == [200] * 30 and codes[30] == 429, "the 31st request a minute")
    return f


CASES: dict[str, Case] = {
    "link_code": link_code_rules,
    "link_proof": link_proof,
    "link_shape": link_shape,
    "fourth_phone": fourth_phone,
    "vectors": vectors,
    "bare_401": bare_401,
    "no_v1_no_cookie": no_v1_no_cookie,
    "asset_links": asset_links,
    "unlink": unlink,
    "end_all": end_all,
    "lock_idle": lock_idle,
    "never_locked": never_locked,
    "unlock_bound": unlock_bound,
    "polls": polls,
    "lock_waits": lock_waits,
    "device_lock": device_lock,
    "recovery": recovery,
    "skew": skew,
    "body_cap": body_cap,
    "phone_rate": phone_rate,
}


async def _run(names: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    quiet = logging.getLogger("jarvis")
    level = quiet.level
    quiet.setLevel(logging.ERROR)
    out = []
    try:
        for name, case in CASES.items():
            if names is not None and name not in names:
                continue
            try:
                failures = await case()
            except Exception as exc:  # noqa: BLE001 - a case that raises has failed, by kind
                failures = [f"raised {type(exc).__name__}"]
            out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    finally:
        quiet.setLevel(level)
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run()


@contextmanager
def _nonce_off() -> Iterator[None]:
    with (
        mock.patch("jarvis.phone.door.NonceStore.seen", lambda self, key, now: False),
        mock.patch("jarvis.phone.door.NonceStore.add", lambda self, key, now: True),
    ):
        yield


def _no_cap_on_the_link() -> Any:
    return mock.patch("jarvis.api.phone.LINK_MAX", 10**9)


def _skew_ignored() -> Any:
    # `abs` shadowed inside the door module: |now - t| is always 0
    return mock.patch("jarvis.phone.door.abs", lambda value: 0, create=True)


@contextmanager
def _no_phone_cap() -> Iterator[None]:
    from jarvis.phone.store import PhoneStore

    real = PhoneStore.link

    async def uncapped(self: Any, code_hash: Any, make: Any, now: Any, *, max_phones: int) -> Any:
        return await real(self, code_hash, make, now, max_phones=99)

    with mock.patch.object(PhoneStore, "link", uncapped):
        yield


@contextmanager
def _code_reusable() -> Iterator[None]:
    from jarvis.phone.store import PhoneStore
    from jarvis.storage.docs import Set

    real = PhoneStore.link

    async def reuse(self: Any, code_hash: Any, make: Any, now: Any, *, max_phones: int) -> Any:
        before = {u: await self.docs.get(self._code_path(u)) for u in self.owners}
        out = await real(self, code_hash, make, now, max_phones=max_phones)
        if out.result == "linked":  # the code is not spent
            await self.docs.write([Set(self._code_path(u), d) for u, d in before.items() if d])
        return out

    with mock.patch.object(PhoneStore, "link", reuse):
        yield


@contextmanager
def _mark_starts_the_clock() -> Iterator[None]:
    from jarvis.phone.applock import AppLock

    real = AppLock.mark_app

    async def touching(self: Any, session: Any, uid: str) -> str:
        fresh = not session.get("r7_app")
        out = await real(self, session, uid)
        if fresh:
            self.touch(session, self._clock())
        return out

    with mock.patch.object(AppLock, "mark_app", touching):
        yield


def _unlock_unbound() -> Any:
    return mock.patch("jarvis.api.phone.ensure_session_id", lambda session: "ss_" + "A" * 24)


def _rate_off() -> Any:
    return mock.patch("jarvis.phone.door.PerPhoneRate.allow", lambda self, key, now: True)


def _off_the_curve_accepted() -> Any:
    return mock.patch("jarvis.phone.service.ec", mock.MagicMock())


CONTROLS: dict[str, tuple[Callable[[], Any], tuple[str, ...]]] = {
    "the nonce store off": (_nonce_off, ("bare_401",)),
    "the signature check off": (
        lambda: mock.patch("jarvis.phone.door.verify", lambda phone, sig, string: True),
        ("vectors", "bare_401"),
    ),
    "the lock exempting every route": (
        lambda: mock.patch("jarvis.phone.applock.exempt", lambda method, path: True),
        ("lock_idle", "never_locked", "polls"),
    ),
    "background polls counted as activity": (
        lambda: mock.patch(
            "jarvis.phone.applock.counts_as_activity", lambda method, path, headers: True
        ),
        ("polls",),
    ),
    "the device cookie never checked": (
        lambda: mock.patch(
            "jarvis.phone.applock.AppLock.device_ok", lambda self, scope, uid: False
        ),
        ("device_lock",),
    ),
    "any device cookie accepted": (
        lambda: mock.patch("jarvis.phone.applock.device_valid", lambda secret, value, uid: True),
        ("device_lock",),
    ),
    "a mark that starts the idle clock": (_mark_starts_the_clock, ("device_lock",)),
    "the clock skew not checked": (_skew_ignored, ("skew", "bare_401")),
    "the link body cap off": (_no_cap_on_the_link, ("body_cap",)),
    "the 3-phone cap off": (_no_phone_cap, ("fourth_phone",)),
    "the code reusable": (_code_reusable, ("link_code",)),
    "wrong tries never voiding": (
        lambda: mock.patch("jarvis.phone.store.MAX_TRIES", 10**9),
        ("link_code",),
    ),
    "a point off the curve accepted": (_off_the_curve_accepted, ("link_shape",)),
    "the unlock not bound to the session": (_unlock_unbound, ("unlock_bound",)),
    "the per-phone rate off": (_rate_off, ("phone_rate",)),
}


async def control() -> dict[str, Any]:
    """Each control re-runs the cases it names; EVERY one of them must fail under it."""
    failed: list[str] = []
    every = True
    for what, (make, names) in CONTROLS.items():
        with make():
            got = await _run(names)
        broke = {r["id"] for r in got if not r["passed"]}
        failed.extend(f"{what} -> {i}" for i in sorted(broke))
        every = every and {f"{PART}:{n}" for n in names} <= broke
    return {"name": "phone: " + "; ".join(CONTROLS), "suite_failed": every, "failed_cases": failed}
