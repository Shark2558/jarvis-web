# tests/test_r7_c_link.py -- R7 Part C, D4 and D5 (docs/plans/r7-mobile.md): linking a phone.
# The link code: 8 characters, 10 minutes, once, void after 5 wrong tries, stored as a hash; it is
# shown only after a passkey check bound to the code's id (or, with no passkey yet, a Google
# sign-in under 5 minutes old). POST /phone/link refuses another package name, a malformed key or
# fingerprint, and a fourth phone; a link sends the urgent `phone_linked` alert and is audited
# without a key. The asset links list linked phones only: the one package, the one relation.
from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from r7_fakes import phone_key
from r7_fakes_c import (
    CSRF,
    FINGERPRINT,
    ORIGIN,
    SECOND,
    add_passkey,
    audit_entries,
    browser,
    link,
    link_code,
    linked_phone,
    owner_uid,
    phone_app,
    phone_service,
    proof,
)

from jarvis.config import Settings
from jarvis.mobile.ports import PACKAGE
from jarvis.tools.audit import args_hash

RELATION = "delegate_permission/common.handle_all_urls"


@pytest.fixture
async def app(settings: Settings) -> Any:
    async with phone_app(settings) as a:
        yield a


def _colon(hex_fp: str) -> str:
    return ":".join(hex_fp[i : i + 2] for i in range(0, 64, 2)).upper()


# ---- the code ---------------------------------------------------------------------------------
async def test_a_fresh_sign_in_shows_an_eight_character_code_stored_only_as_a_hash(
    app: Any,
) -> None:
    async with browser(app) as c:
        r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
        assert r.status_code == 200, r.text
        body = r.json()
        code = body["code"]
        assert len(code) == 8 and code.isalnum() and code.upper() == code
        assert body["expires_in_s"] == 600
        assert r.headers["cache-control"] == "no-store"
        doc = await phone_service(app).store.docs.get(f"jarvis_phone_link/{owner_uid()}")
        assert doc is not None and code not in json.dumps(doc)
        assert doc["code_hash"] == hashlib.sha256(code.encode()).hexdigest()


async def test_without_a_passkey_an_old_sign_in_is_not_enough(app: Any) -> None:
    async with browser(app, fresh=False) as c:
        r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "reauth_required"


async def test_with_a_passkey_the_code_needs_a_proof_bound_to_its_id(app: Any) -> None:
    async with browser(app) as c:
        auth = await add_passkey(c)
        r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "passkey_required"
        target = r.json()["target"]
        assert target.startswith("pl_") and len(target) == 15
        # a proof made for another offer is refused, and the code is not shown
        other = await proof(c, auth, "phone_link", "pl_000000000000")
        r = await c.post("/v1/phone/link-code", json={"id": target, "proof": other}, headers=CSRF)
        assert r.status_code == 403 and "code" not in r.json()
        # a proof of the wrong purpose too
        wrong = await proof(c, auth, "device_unlock", "ss_" + "a" * 24)
        r = await c.post("/v1/phone/link-code", json={"id": target, "proof": wrong}, headers=CSRF)
        assert r.status_code == 403 and "code" not in r.json()
        r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
        target = r.json()["target"]
        good = await proof(c, auth, "phone_link", target)
        r = await c.post("/v1/phone/link-code", json={"id": target, "proof": good}, headers=CSRF)
        assert r.status_code == 200 and len(r.json()["code"]) == 8
        # the proof is single use and the offer is spent
        r = await c.post("/v1/phone/link-code", json={"id": target, "proof": good}, headers=CSRF)
        assert r.status_code == 403, r.text


async def test_an_offer_older_than_five_minutes_is_refused(app: Any) -> None:
    async with browser(app) as c:
        auth = await add_passkey(c)
        r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
        target = r.json()["target"]
        app.state.phone_clock.advance(301)
        good = await proof(c, auth, "phone_link", target)
        r = await c.post("/v1/phone/link-code", json={"id": target, "proof": good}, headers=CSRF)
        assert r.status_code == 409 and r.json()["error"] == "offer_expired"


async def test_the_code_works_once(app: Any) -> None:
    async with browser(app) as c:
        code = await link_code(c)
    r, _ = await link(app, code)
    assert r.status_code == 200 and r.json()["device_id"].startswith("ph_")
    assert len(r.json()["device_id"]) == 15 and "set-cookie" not in r.headers
    r, _ = await link(app, code)
    assert r.status_code == 403 and r.json()["error"] == "bad_code"


async def test_the_code_lasts_ten_minutes(app: Any) -> None:
    async with browser(app) as c:
        code = await link_code(c)
    app.state.phone_clock.advance(601)
    r, _ = await link(app, code)
    assert r.status_code == 403 and r.json()["error"] == "bad_code"


async def test_a_code_typed_with_spaces_lower_case_or_look_alikes_still_links(app: Any) -> None:
    async with browser(app) as c:
        code = await link_code(c)
    typed = (code[:4] + " " + code[4:]).lower()
    r, _ = await link(app, typed)
    assert r.status_code == 200, r.text


async def test_five_wrong_tries_void_the_code(app: Any) -> None:
    async with browser(app) as c:
        code = await link_code(c)
    wrong = "22222222" if code != "22222222" else "33333333"
    for _ in range(5):
        r, _ = await link(app, wrong)
        assert r.status_code == 403 and r.json()["error"] == "bad_code"
    r, _ = await link(app, code)
    assert r.status_code == 403 and r.json()["error"] == "bad_code"
    async with browser(app) as c:
        view = (await c.get("/v1/phone")).json()
    assert view["code"] is None and view["phones"] == []


async def test_four_wrong_tries_leave_the_code_working(app: Any) -> None:
    async with browser(app) as c:
        code = await link_code(c)
    wrong = "22222222" if code != "22222222" else "33333333"
    for _ in range(4):
        await link(app, wrong)
    r, _ = await link(app, code)
    assert r.status_code == 200


# ---- what a link request must carry ------------------------------------------------------------
@pytest.mark.parametrize(
    ("over", "error"),
    [
        ({"package": "com.example.other"}, "not_this_app"),
        ({"package": PACKAGE + ".debug"}, "not_this_app"),
        ({"public_key": "04" + "00" * 64}, "bad_key"),  # not a point on P-256
        ({"public_key": "02" + "11" * 32}, "bad_key"),  # compressed: refused
        ({"public_key": "04" + "ab" * 63}, "bad_key"),  # too short
        ({"fingerprint": "ab" * 31}, "bad_fingerprint"),  # 31 bytes
        ({"fingerprint": "zz" * 32}, "bad_fingerprint"),
        ({"fingerprint": "AB:" * 31 + "AB"}, "bad_fingerprint"),
        ({"v": 2}, "input_rejected"),
        ({"model": "<script>"}, "input_rejected"),
        ({"app_version": "7"}, "input_rejected"),
        ({"extra": "x"}, "input_rejected"),
    ],
)
async def test_a_link_request_must_be_exactly_the_apps(
    app: Any, over: dict[str, Any], error: str
) -> None:
    async with browser(app) as c:
        code = await link_code(c)
    r, _ = await link(app, code, **over)
    assert r.status_code == 422 and r.json()["error"] == error, r.text
    # a malformed request is not a wrong try: the code still links
    r, _ = await link(app, code)
    assert r.status_code == 200


async def test_a_body_that_is_not_json_or_too_large_is_refused(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        assert (await c.post("/phone/link", content=b"not json")).status_code == 422
        r = await c.post("/phone/link", content=b"{" + b" " * 5000 + b"}")
        assert r.status_code == 413


async def test_a_fourth_phone_is_refused(app: Any) -> None:
    async with browser(app) as c:
        for _ in range(3):
            await linked_phone(app, c)
        code = await link_code(c)
    r, _ = await link(app, code)
    assert r.status_code == 409 and r.json()["error"] == "too_many_phones"
    async with browser(app) as c:
        assert len((await c.get("/v1/phone")).json()["phones"]) == 3


async def test_the_same_key_is_not_linked_twice(app: Any) -> None:
    async with browser(app) as c:
        _, key = await linked_phone(app, c)
        code = await link_code(c)
    r, _ = await link(app, code, key)
    assert r.status_code == 409 and r.json()["error"] == "already_linked"


async def test_a_link_rings_everywhere_and_is_audited_without_a_key(app: Any) -> None:
    async with browser(app) as c:
        device, key = await linked_phone(app, c)
    (uid, signal, message) = app.state.notify.sent[-1]
    assert uid == owner_uid() and signal.kind == "phone_linked"
    assert message.startswith("A phone was linked to JARVIS at ")
    assert message.endswith("If this wasn't you, unlink it in Integrations.")
    entries = [e for e in audit_entries(app) if e.tool == "phone_link"]
    assert len(entries) == 1
    assert entries[0].args_hash == args_hash({"device": device, "model": "phone"})
    flat = json.dumps([e.model_dump(mode="json") for e in audit_entries(app)])
    pub = key.public_key().public_numbers()
    assert format(pub.x, "x") not in flat and FINGERPRINT not in flat


async def test_the_card_lists_the_phone_and_unlink_removes_it_with_an_info_alert(app: Any) -> None:
    async with browser(app) as c:
        device, _ = await linked_phone(app, c)
        view = (await c.get("/v1/phone")).json()
        assert view["part"] == "phone" and view["max"] == 3
        (phone,) = view["phones"]
        assert phone["id"] == device and phone["model"] == "phone"
        assert "public_key" not in phone and "fingerprint" not in phone
        r = await c.post(f"/v1/phone/{device}/unlink", headers=CSRF)
        assert r.status_code == 200 and r.json() == {"unlinked": True}
        assert (await c.get("/v1/phone")).json()["phones"] == []
        r = await c.post(f"/v1/phone/{device}/unlink", headers=CSRF)
        assert r.status_code == 404
        r = await c.post("/v1/phone/ph_xyz/unlink", headers=CSRF)
        assert r.status_code == 404
    assert app.state.notify.sent[-1][1].kind == "phone_unlinked"


async def test_the_console_routes_are_owner_only_and_writes_need_the_header(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        assert (await c.get("/v1/phone")).status_code == 401
        assert (await c.post("/v1/phone/link-code", json={}, headers=CSRF)).status_code == 401
    async with browser(app) as c:
        assert (await c.post("/v1/phone/link-code", json={})).status_code == 403  # no CSRF header


async def test_each_owner_links_his_own_phones(app: Any) -> None:
    async with browser(app) as c:
        mine, _ = await linked_phone(app, c)
    async with browser(app, SECOND) as c:
        assert (await c.get("/v1/phone")).json()["phones"] == []
        assert (await c.post(f"/v1/phone/{mine}/unlink", headers=CSRF)).status_code == 404


# ---- the asset links (D4) ----------------------------------------------------------------------
async def test_asset_links_list_linked_phones_only(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        r = await anon.get("/.well-known/assetlinks.json")
        assert r.status_code == 200 and r.json() == []
        assert r.headers["content-type"].startswith("application/json")
        assert r.headers["cache-control"] == "public, max-age=60"
        assert "set-cookie" not in r.headers
    async with browser(app) as c:
        device, _ = await linked_phone(app, c)
        await linked_phone(app, c)  # a second phone with the same signing key: one fingerprint
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        statements = (await anon.get("/.well-known/assetlinks.json")).json()
    assert statements == [
        {
            "relation": [RELATION],
            "target": {
                "namespace": "android_app",
                "package_name": PACKAGE,
                "sha256_cert_fingerprints": [_colon(FINGERPRINT)],
            },
        }
    ]
    async with browser(app) as c:
        phones = (await c.get("/v1/phone")).json()["phones"]
        for p in phones:
            await c.post(f"/v1/phone/{p['id']}/unlink", headers=CSRF)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        assert (await anon.get("/.well-known/assetlinks.json")).json() == []


async def test_two_signing_keys_give_two_fingerprints_in_one_statement(app: Any) -> None:
    other = "cd" * 32
    async with browser(app) as c:
        await linked_phone(app, c)
        code = await link_code(c)
    r, _ = await link(app, code, fingerprint=other.upper())  # upper case hex is read as lower
    assert r.status_code == 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        (st,) = (await anon.get("/.well-known/assetlinks.json")).json()
    assert st["relation"] == [RELATION] and st["target"]["package_name"] == PACKAGE
    assert sorted(st["target"]["sha256_cert_fingerprints"]) == sorted(
        [_colon(FINGERPRINT), _colon(other)]
    )


async def test_with_mobile_switched_off_nothing_of_the_phone_answers(settings: Settings) -> None:
    async with phone_app(settings, mobile_enabled=False) as off:
        async with AsyncClient(transport=ASGITransport(app=off), base_url=ORIGIN) as anon:
            assert (await anon.get("/.well-known/assetlinks.json")).status_code == 404
            assert (await anon.post("/phone/link", content=b"{}")).status_code == 404
        async with browser(off) as c:
            r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
            assert r.status_code == 404 and r.json()["error"] == "mobile_off"


def test_the_fakes_make_keys_in_the_test() -> None:
    assert phone_key() is not phone_key()
