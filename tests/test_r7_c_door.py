# tests/test_r7_c_door.py -- R7 Part C, D6 (docs/plans/r7-mobile.md): the phone's signed door.
# Checked in this order before any parsing: the route (404) -> no query string at all (401) -> the
# body cap -> the header's shape -> the device is linked -> |now - t| <= 120 s -> the nonce unseen
# for 10 minutes -> the signature -> 30 requests a minute per phone. Every failure is a bare 401
# (or 404), logged by the check's name only and never audited. Every shared vector verifies; the
# door reaches no /v1 route, never sets or reads a cookie, and unlink closes it at once.
from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from r7_fakes import load_vectors, phone_key, sign_request
from r7_fakes_c import (
    CSRF,
    HELLO,
    ORIGIN,
    audit_entries,
    browser,
    door,
    http_routes,
    linked_phone,
    owner_uid,
    phone_app,
    phone_service,
)

from jarvis.config import Settings
from jarvis.mobile.ports import MobilePart, PhoneReply, PhoneRequest
from jarvis.phone.door import NonceStore, PerPhoneRate
from jarvis.phone.store import Phone

V = load_vectors()


@pytest.fixture
async def app(settings: Settings) -> Any:
    async with phone_app(settings) as a:
        yield a


class Seen:
    """D's two door handlers, faked: what reached them."""

    def __init__(self) -> None:
        self.got: list[PhoneRequest] = []

    async def __call__(self, req: PhoneRequest) -> PhoneReply:
        self.got.append(req)
        return PhoneReply(200, {"ok": True})


def body_part(app: Any, seen: Seen, **services: Any) -> None:
    app.state.r7_parts["body"] = MobilePart(
        "body", services={"door": {"health": seen, "sos": seen}, **services}
    )


async def seed_vector_phone(app: Any) -> None:
    """The vectors' phone, linked to the owner (its public key only)."""
    phone = Phone(
        id=V["device_id"],
        model="phone",
        public_key=V["public_key_x962_hex"],
        package=V["package"],
        fingerprint=V["signing_fingerprint_hex"],
        linked_at=V["server_time_for_cases"] - 60,
        app_version="7.0.0",
    )
    await phone_service(app).store.put_phone(owner_uid(), phone)


async def raw(app: Any, path: str, body: bytes, header: str | None, **extra: str) -> Any:
    headers = {"X-Jarvis-Phone": header} if header is not None else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        return await c.post(path, content=body, headers={**headers, **extra})


# ---- the shared vectors ------------------------------------------------------------------------
async def test_every_shared_vector_gets_the_answer_it_says(app: Any) -> None:
    seen = Seen()
    body_part(app, seen)
    app.state.phone_clock.t = float(V["server_time_for_cases"])
    await seed_vector_phone(app)
    for case in V["cases"]:
        r = await raw(app, case["path"], case["body"].encode(), case["header"])
        if case["door"] == "accept":
            assert r.status_code not in (401, 404), (case["name"], r.status_code)
        else:
            assert r.status_code == 401 and r.content == b"", case["name"]
    routes = sorted(req.route for req in seen.got)
    assert routes == ["health", "sos", "sos"]  # D's routes got exactly the good cases
    assert all(req.device_id == V["device_id"] and req.uid == owner_uid() for req in seen.got)
    health = next(c for c in V["cases"] if c["name"] == "health")
    assert seen.got[0].body == health["body"].encode()  # exactly the signed bytes


async def test_a_replayed_vector_is_refused(app: Any) -> None:
    body_part(app, Seen())
    app.state.phone_clock.t = float(V["server_time_for_cases"])
    await seed_vector_phone(app)
    case = next(c for c in V["cases"] if c["name"] == "sos")
    first = await raw(app, case["path"], case["body"].encode(), case["header"])
    again = await raw(app, case["path"], case["body"].encode(), case["header"])
    assert first.status_code == 200 and again.status_code == 401


# ---- a phone linked through the real flow ------------------------------------------------------
@pytest.fixture
async def phone(app: Any) -> tuple[str, Any]:
    async with browser(app) as c:
        return await linked_phone(app, c)


async def test_hello_answers_with_the_settings_and_records_what_the_app_may_do(
    app: Any, phone: tuple[str, Any]
) -> None:
    device, key = phone
    r = await door(app, key, device, "hello", HELLO)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["v"] == 1 and body["device_id"] == device
    assert body["settings"]["app_lock_minutes"] == 5 and body["settings"]["sos_countdown_s"] == 10
    assert body["sos"] == {"enabled": True, "contacts": []}  # Part D is not built here
    assert r.headers["cache-control"] == "no-store" and "set-cookie" not in r.headers
    async with browser(app) as c:
        (p,) = (await c.get("/v1/phone")).json()["phones"]
    assert p["can"] == HELLO["can"] and p["android"] == 36 and p["last_seen"] is not None


async def test_hello_carries_the_sos_contacts_part_d_offers(
    app: Any, phone: tuple[str, Any]
) -> None:
    async def contacts(uid: str) -> list[dict[str, str]]:
        assert uid == owner_uid()
        return [{"label": "Asha", "phone": "+910000000001"}]

    body_part(app, Seen(), sos_contacts=contacts)
    device, key = phone
    r = await door(app, key, device, "hello", HELLO)
    assert r.json()["sos"]["contacts"] == [{"label": "Asha", "phone": "+910000000001"}]


async def test_a_hello_that_is_not_the_one_json_form_is_refused_after_the_door(
    app: Any, phone: tuple[str, Any]
) -> None:
    device, key = phone
    spaced = json.dumps(HELLO).encode()  # valid JSON, but not the one byte form
    r = await door(app, key, device, "hello", spaced)
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"
    bad = {**HELLO, "can": {**HELLO["can"], "sms": True}}
    r = await door(app, key, device, "hello", bad)
    assert r.status_code == 422


@pytest.mark.parametrize(
    "url",
    ["/phone/v1/hello?x=1", "/phone/v1/hello?a", "/phone/v1/hello?=", "/phone/v1/hello?d=ph_1"],
)
async def test_any_query_string_is_a_bare_401(app: Any, phone: tuple[str, Any], url: str) -> None:
    device, key = phone
    before = len(audit_entries(app))
    r = await door(app, key, device, "hello", HELLO, url=url)
    assert r.status_code == 401 and r.content == b""
    assert len(audit_entries(app)) == before


async def test_each_bad_request_is_a_bare_401_and_no_audit_line(
    app: Any, phone: tuple[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    device, key = phone
    clock = app.state.phone_clock
    before = len(audit_entries(app))
    caplog.set_level(logging.INFO)
    cases = {
        "a wrong key": await door(app, phone_key(), device, "hello", HELLO),
        "a stale time": await door(app, key, device, "hello", HELLO, t=clock() - 121),
        "a time ahead": await door(app, key, device, "hello", HELLO, t=clock() + 121),
        "an unknown phone": await door(app, key, "ph_000000000000", "hello", HELLO),
    }
    headers, body = sign_request(key, device, "POST", "/phone/v1/hello", HELLO, t=int(clock()))
    cases["a changed body"] = await raw(
        app, "/phone/v1/hello", body + b" ", headers["X-Jarvis-Phone"]
    )
    cases["another route"] = await raw(app, "/phone/v1/sos", body, headers["X-Jarvis-Phone"])
    cases["no header"] = await raw(app, "/phone/v1/hello", body, None)
    cases["a bad header"] = await raw(app, "/phone/v1/hello", body, "v1;d=ph_1;t=1")
    cases["a cookie"] = await door(app, key, device, "hello", HELLO, headers={"Cookie": "a=b"})
    for name, r in cases.items():
        assert r.status_code == 401 and r.content == b"", name
        assert "set-cookie" not in r.headers, name
    assert len(audit_entries(app)) == before
    refusals = [r for r in caplog.records if r.getMessage() == "phone door refused"]
    assert {getattr(r, "check", "") for r in refusals} >= {
        "signature",
        "time",
        "device",
        "header",
        "cookie",
    }
    pub = key.public_key().public_numbers()
    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert format(pub.x, "x") not in text and device not in text


async def test_a_replayed_nonce_is_refused_and_a_new_one_passes(
    app: Any, phone: tuple[str, Any]
) -> None:
    device, key = phone
    nonce = "ab" * 16
    assert (await door(app, key, device, "hello", HELLO, nonce=nonce)).status_code == 200
    assert (await door(app, key, device, "hello", HELLO, nonce=nonce)).status_code == 401
    app.state.phone_clock.advance(100)  # still inside the window: the nonce is still seen
    assert (await door(app, key, device, "hello", HELLO, nonce=nonce)).status_code == 401
    assert (await door(app, key, device, "hello", HELLO)).status_code == 200


async def test_unknown_routes_and_methods_are_a_bare_404(app: Any, phone: tuple[str, Any]) -> None:
    device, key = phone
    headers, body = sign_request(key, device, "POST", "/phone/v1/hello", HELLO)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        for path in ("/phone/v1/vault", "/phone/v1/chat", "/phone/v2/hello", "/phone/v1/HELLO"):
            r = await c.post(path, content=body, headers=headers)
            assert r.status_code == 404, path
        r = await c.get("/phone/v1/hello", headers=headers)
        assert r.status_code in (404, 405)


async def test_the_door_reaches_no_v1_route(app: Any, phone: tuple[str, Any]) -> None:
    """A good signature is no credential anywhere else."""
    device, key = phone
    headers, body = sign_request(key, device, "POST", "/phone/v1/hello", HELLO)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        for method, path in (
            ("POST", "/v1/chat"),
            ("GET", "/v1/phone"),
            ("GET", "/v1/vault"),
            ("POST", "/v1/session/unlock"),
            ("POST", "/v1/session/end-all"),
        ):
            r = await c.request(method, path, content=body, headers={**headers, **CSRF})
            assert r.status_code == 401, path
    door_routes = {p for p, _ in http_routes(app) if p.startswith("/phone")}
    assert door_routes == {"/phone/link", "/phone/v1/{route}"}


async def test_unlink_closes_the_door_at_once(app: Any, phone: tuple[str, Any]) -> None:
    device, key = phone
    assert (await door(app, key, device, "hello", HELLO)).status_code == 200
    async with browser(app) as c:
        assert (await c.post(f"/v1/phone/{device}/unlink", headers=CSRF)).status_code == 200
    assert (await door(app, key, device, "hello", HELLO)).status_code == 401


async def test_thirty_requests_a_minute_per_phone(app: Any, phone: tuple[str, Any]) -> None:
    device, key = phone
    for _ in range(30):
        assert (await door(app, key, device, "hello", HELLO)).status_code == 200
    assert (await door(app, key, device, "hello", HELLO)).status_code == 401
    app.state.phone_clock.advance(61)
    assert (await door(app, key, device, "hello", HELLO)).status_code == 200


async def test_a_body_over_its_route_cap_is_refused_before_it_is_read(
    app: Any, phone: tuple[str, Any]
) -> None:
    device, key = phone
    big = {**HELLO, "model": "x" * 17000}
    r = await door(app, key, device, "hello", big)
    assert r.status_code == 401 and r.content == b""


async def test_a_store_that_cannot_be_read_admits_nothing(app: Any, phone: tuple[str, Any]) -> None:
    device, key = phone

    async def broken(device_id: str) -> Any:
        raise RuntimeError("store down")

    phone_service(app).store.find = broken
    r = await door(app, key, device, "hello", HELLO)
    assert r.status_code == 503 and r.content == b""


async def test_without_mobile_the_door_is_not_there(settings: Settings) -> None:
    async with phone_app(settings, mobile_enabled=False) as off:
        r = await raw(off, "/phone/v1/hello", b"{}", "x")
        assert r.status_code == 404


# ---- the inbox (D16) ---------------------------------------------------------------------------
class FakeVault:
    def __init__(self, status: str = "added", code: str = "") -> None:
        self.got: list[tuple[str, bytes, str]] = []
        self.status, self.code = status, code

    async def intake(
        self, uid: str, data: bytes, *, source: str, drive_id: str | None = None
    ) -> Any:
        from jarvis.vault.ports import IntakeResult

        self.got.append((uid, data, source))
        if self.status == "added":
            return IntakeResult(status="added", item_id="vi_0001")
        return IntakeResult(status="skipped", code=self.code, message="Plain words.")


PDF = b"%PDF-1.4\n% a tiny test file, not a document\n%%EOF\n"


def inbox_body(data: bytes = PDF, **over: Any) -> bytes:
    import hashlib

    from jarvis.mobile import contract

    head: dict[str, Any] = {
        "v": 1,
        "name": "licence.pdf",
        "mime": "application/pdf",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    head.update(over)
    return contract.canonical_json(head) + b"\n" + data


async def test_the_inbox_hands_the_file_to_the_vault_as_a_digilocker_proposal(
    app: Any, phone: tuple[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    vault = FakeVault()
    app.state.vault = vault
    device, key = phone
    r = await door(app, key, device, "inbox", inbox_body(name="secret-name-1.pdf"))
    assert r.status_code == 200 and r.json() == {"status": "added"}
    assert vault.got == [(owner_uid(), PDF, "digilocker")]
    assert "secret-name-1" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        inbox_body(sha256="0" * 64),
        inbox_body(bytes=len(PDF) + 1),
        inbox_body(mime="application/zip"),
        inbox_body(v=2),
        b'{"v": 1}\n' + PDF,
        PDF,  # no first line
        inbox_body(b""),
    ],
)
async def test_an_inbox_file_that_is_not_what_its_first_line_says_is_refused(
    app: Any, phone: tuple[str, Any], body: bytes
) -> None:
    vault = FakeVault()
    app.state.vault = vault
    device, key = phone
    r = await door(app, key, device, "inbox", body)
    assert r.status_code == 422 and vault.got == []


async def test_the_inbox_says_when_to_try_again(app: Any, phone: tuple[str, Any]) -> None:
    device, key = phone
    app.state.vault = None
    r = await door(app, key, device, "inbox", inbox_body())
    assert r.status_code == 503 and r.json()["error"] == "vault_off"
    app.state.vault = FakeVault("skipped", "vault_full")
    r = await door(app, key, device, "inbox", inbox_body())
    assert r.status_code == 503 and r.json()["status"] == "skipped"
    app.state.vault = FakeVault("skipped", "unsupported")
    r = await door(app, key, device, "inbox", inbox_body())
    assert r.status_code == 422 and r.json() == {"status": "skipped", "code": "unsupported"}


# ---- the bounded stores ------------------------------------------------------------------------
def test_the_nonce_store_is_bounded_and_forgets_after_ten_minutes() -> None:
    store = NonceStore(max_entries=3, ttl_s=600)
    assert store.add("a", 0) and store.add("b", 1) and store.add("c", 2)
    assert store.seen("a", 3) and not store.seen("d", 3)
    assert not store.add("d", 3)  # full of live nonces: refused, never evicted early
    assert not store.seen("a", 601) and store.add("d", 601)  # "a" expired and was dropped
    assert len(store) <= 3


def test_the_rate_is_per_phone_and_bounded() -> None:
    rate = PerPhoneRate(per_minute=2, max_phones=2)
    assert rate.allow("p1", 0) and rate.allow("p1", 1) and not rate.allow("p1", 2)
    assert rate.allow("p2", 2)
    assert rate.allow("p3", 3)  # a third phone pushes out the stalest; never a refusal
    assert len(rate) <= 2
    assert rate.allow("p1", 61)
