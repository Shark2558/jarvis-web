# tests/test_webpush_service.py -- R3 D11: endpoint rule, VAPID, owner-bound encrypted store,
# validated subscribe, contained failures, content-free audit.
from __future__ import annotations

import base64
import json
from datetime import timedelta

import pytest
from joserfc import jwt
from joserfc.jwk import ECKey
from webpush_fakes import GOOD, NOW, Browser, PushWorld, b64, resolver

from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.webpush import endpoints
from jarvis.webpush.endpoints import BadEndpoint, check
from jarvis.webpush.service import BadSubscription, payload_for
from jarvis.webpush.store import PushFull, PushStore, PushUnavailable
from jarvis.webpush.vapid import MAX_LIFETIME, VapidKey

UID = "owner"


# ---- endpoint rule ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://fcm.googleapis.com/fcm/send/x",
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://web.push.apple.com/x",
        "https://db5p.notify.windows.com/w/?token=x",
        "https://FCM.googleapis.com/wp/x",
    ],
)
async def test_known_push_services_pass(url: str) -> None:
    assert await check(url, resolver=resolver)


@pytest.mark.parametrize(
    "url",
    [
        "http://fcm.googleapis.com/fcm/send/x",
        "https://fcm.googleapis.com:8443/fcm/send/x",
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://169.254.169.254/latest",
        "https://fcm.googleapis.com.evil.example/x",
        "https://evil.example/fcm.googleapis.com",
        "https://notify.windows.com/x",
        "https://evilnotify.windows.com.evil.example/x",
        "https://user:pw@fcm.googleapis.com/x",
        "https://fcm.googleapis.com",
        "https://fcm.googleapis.com/x#frag",
        "https://fcm.googleapis.com/x y",
        "https://fcm.googleapis.com/" + "a" * 800,
        "ftp://fcm.googleapis.com/x",
        "",
        "https://fcm.googleapis.com\\@evil.example/x",
        "https://fcm.g\u00f6ogleapis.com/x",
    ],
)
async def test_bad_endpoints_are_refused(url: str) -> None:
    with pytest.raises(BadEndpoint):
        await check(url, resolver=resolver)


async def test_a_non_string_endpoint_is_refused() -> None:
    with pytest.raises(BadEndpoint):
        await check(None, resolver=resolver)  # type: ignore[arg-type]


async def test_a_private_resolved_address_is_refused() -> None:
    async def inward(host: str) -> list[str]:
        return ["10.0.0.5"]

    with pytest.raises(BadEndpoint):
        await check(GOOD, resolver=inward)


async def test_the_allow_list_off_lets_a_stranger_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(endpoints, "ENFORCE", False)
    assert await check("https://evil.example/x", resolver=resolver)


# ---- VAPID -----------------------------------------------------------------------------------


def test_vapid_token_verifies_and_is_scoped() -> None:
    w = PushWorld()
    header = w.vapid.header("https://fcm.googleapis.com/fcm/send/x", NOW)
    assert header.startswith("vapid t=") and f", k={w.vapid.public_key}" in header
    token = header.split("t=", 1)[1].split(",", 1)[0]
    raw = base64.urlsafe_b64decode(w.vapid.public_key + "==")
    assert len(raw) == 65 and raw[0] == 4
    claims = _decode(w.vapid, token)
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "https://j.example"
    assert 0 < claims["exp"] - int(NOW.timestamp()) <= MAX_LIFETIME.total_seconds()


def _decode(vapid: VapidKey, token: str) -> dict[str, object]:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    pub = vapid._private.public_key()
    pem = pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return jwt.decode(token, ECKey.import_key(pem)).claims


def test_the_vapid_key_is_stable_for_one_root_and_differs_for_another() -> None:
    a = VapidKey.from_secret(Keyring(bytes(range(1, 33))).secret("webpush_vapid", length=48), "x")
    b = VapidKey.from_secret(Keyring(bytes(range(1, 33))).secret("webpush_vapid", length=48), "x")
    c = VapidKey.from_secret(Keyring(bytes(range(2, 34))).secret("webpush_vapid", length=48), "x")
    assert a.public_key == b.public_key != c.public_key
    assert "hidden" in repr(a)


def test_vapid_refuses_a_short_secret_and_a_non_https_endpoint() -> None:
    with pytest.raises(ValueError):
        VapidKey.from_secret(b"short", "x")
    with pytest.raises(ValueError):
        PushWorld().vapid.token("http://fcm.googleapis.com/x", NOW)


def test_the_token_expires_within_twelve_hours() -> None:
    w = PushWorld()
    claims = _decode(w.vapid, w.vapid.token(GOOD, NOW + timedelta(days=3)))
    assert claims["exp"] - int((NOW + timedelta(days=3)).timestamp()) <= 12 * 3600


# ---- subscribe and the store -----------------------------------------------------------------


async def test_subscribe_stores_an_encrypted_owner_bound_device() -> None:
    w = PushWorld()
    br = Browser()
    dev = await w.service.subscribe(UID, **br.sub())
    assert (await w.store.list(UID))[0].id == dev.id
    assert dev.view() == {"id": dev.id, "name": "Chrome on Android", "added_at": dev.added_at}
    blob = json.dumps(w.docs._data)
    assert br.p256dh not in blob and "fcm.googleapis.com" not in blob and "Chrome" not in blob
    assert await w.store.list("someone-else") == []


async def test_the_same_endpoint_replaces_its_entry_and_five_is_the_cap() -> None:
    w = PushWorld()
    br = Browser()
    await w.service.subscribe(UID, **br.sub())
    await w.service.subscribe(UID, **br.sub("Renamed"))
    assert [d.name for d in await w.store.list(UID)] == ["Renamed"]
    for i in range(4):
        await w.service.subscribe(UID, **Browser(f"https://fcm.googleapis.com/fcm/send/{i}").sub())
    with pytest.raises(PushFull):
        await w.service.subscribe(UID, **Browser("https://fcm.googleapis.com/fcm/send/z").sub())


@pytest.mark.parametrize(
    "patch",
    [
        {"endpoint": "http://fcm.googleapis.com/x"},
        {"endpoint": "https://evil.example/x"},
        {"p256dh": "AAAA"},
        {"p256dh": "!!!!"},
        {"p256dh": ""},
        {"p256dh": 7},
        {"auth": "AAAA"},
        {"auth": "x" * 100},
        {"name": ""},
        {"name": 5},
    ],
)
async def test_bad_subscriptions_are_refused_and_nothing_is_stored(
    patch: dict[str, object],
) -> None:
    w = PushWorld()
    with pytest.raises(BadSubscription):
        await w.service.subscribe(UID, **{**Browser().sub(), **patch})  # type: ignore[arg-type]
    assert await w.store.list(UID) == []


async def test_a_point_off_the_curve_is_refused() -> None:
    w = PushWorld()
    bad = {**Browser().sub(), "p256dh": b64(b"\x04" + b"\x01" * 64)}
    with pytest.raises(BadSubscription):
        await w.service.subscribe(UID, **bad)  # type: ignore[arg-type]


async def test_names_are_cleaned_and_capped() -> None:
    w = PushWorld()
    dev = await w.service.subscribe(UID, **Browser().sub("  <b>Chrome</b>\n\x00" + "x" * 80))
    assert "<" not in dev.name and "\n" not in dev.name and len(dev.name) <= 40


async def test_remove_is_owner_bound() -> None:
    w = PushWorld()
    dev = await w.service.subscribe(UID, **Browser().sub())
    assert await w.service.remove("other", dev.id) is False
    assert await w.service.remove(UID, dev.id) is True
    assert await w.store.list(UID) == []


async def test_a_damaged_list_fails_closed_and_is_never_overwritten() -> None:
    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())
    path = "jarvis_webpush/owner"
    w.docs._data[path]["blob"] = "garbage"
    before = dict(w.docs._data[path])
    with pytest.raises(PushUnavailable):
        await w.store.list(UID)
    with pytest.raises(PushUnavailable):
        await w.service.subscribe(UID, **Browser("https://fcm.googleapis.com/fcm/send/q").sub())
    assert w.docs._data[path] == before
    assert await w.service.send(UID, kind="test", text="hi") == 0  # contained


async def test_a_wrong_key_cannot_open_the_list() -> None:
    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())
    other = PushStore(w.docs, Keyring(bytes(range(9, 41))))
    with pytest.raises(PushUnavailable):
        await other.list(UID)


async def test_storage_errors_become_plain_words() -> None:
    class Broken(MemoryDocs):
        async def transaction(self, fn):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom secret")

    store = PushStore(Broken(), Keyring(bytes(range(1, 33))))
    with pytest.raises(PushUnavailable) as e:
        await store.add(UID, "n", "e", "p", "a")
    assert "boom" not in str(e.value)


# ---- sending ---------------------------------------------------------------------------------


async def test_send_posts_one_encrypted_message_per_device_with_the_right_headers() -> None:
    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())
    await w.service.subscribe(
        UID, **Browser("https://updates.push.services.mozilla.com/wpush/v2/q").sub()
    )
    n = await w.service.send(UID, kind="home_intruder", text="Someone is at your gate.")
    assert n == 2 and len(w.requests) == 2
    r = w.requests[0]
    assert r.headers["content-encoding"] == "aes128gcm"
    assert r.headers["urgency"] == "high" and r.headers["ttl"] == "600"
    assert r.headers["authorization"].startswith("vapid t=")
    assert b"Someone" not in r.content and 90 < len(r.content) < 1300
    assert (await w.store.list(UID))[0].last_ok_at is not None


async def test_silent_is_low_urgency_and_other_kinds_live_a_day() -> None:
    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())
    await w.service.send(UID, kind="home_online", text="Your home laptop is back.", silent=True)
    assert w.requests[0].headers["urgency"] == "low" and w.requests[0].headers["ttl"] == "86400"


async def test_the_browser_can_read_what_was_sent() -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    w = PushWorld()
    br = Browser()
    await w.service.subscribe(UID, **br.sub())
    await w.service.send(UID, kind="home_package", text="A package was left at the Gate, 14:05.")
    body = w.requests[0].content
    salt, as_pub, sealed = body[:16], body[21:86], body[86:]
    ua_pub = base64.urlsafe_b64decode(br.p256dh + "==")
    auth = base64.urlsafe_b64decode(br.auth + "==")
    from jarvis.webpush.ece import public_key

    shared = br.private.exchange(ec.ECDH(), public_key(as_pub))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + ua_pub + as_pub).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    got = json.loads(AESGCM(cek).decrypt(nonce, sealed, None)[:-1])
    assert got == {
        "kind": "home_package",
        "text": "A package was left at the Gate, 14:05.",
        "url": "/#home",
    }


def test_the_payload_is_small_template_only_and_never_a_picture() -> None:
    raw = payload_for("approval_waiting", "x" * 5000)
    assert len(raw) <= 1024 and set(json.loads(raw)) == {"kind", "text", "url"}
    assert json.loads(raw)["url"] == "/"
    big = payload_for("home_intruder", "\u0d15" * 5000)
    assert len(big) <= 1024
    assert "\n" not in json.loads(payload_for("test", "a\n\nb"))["text"]


async def test_gone_devices_are_removed_and_others_still_get_it() -> None:
    w = PushWorld({"/fcm/send/gone": 410, "/fcm/send/ok": 201})
    await w.service.subscribe(UID, **Browser("https://fcm.googleapis.com/fcm/send/gone").sub("a"))
    await w.service.subscribe(UID, **Browser("https://fcm.googleapis.com/fcm/send/ok").sub("b"))
    assert await w.service.send(UID, kind="test", text="t") == 1
    assert [d.name for d in await w.store.list(UID)] == ["b"]


async def test_a_404_also_removes_and_a_500_keeps_the_device() -> None:
    w = PushWorld({"/fcm/send/nf": 404, "/fcm/send/err": 500})
    await w.service.subscribe(UID, **Browser("https://fcm.googleapis.com/fcm/send/nf").sub("a"))
    await w.service.subscribe(UID, **Browser("https://fcm.googleapis.com/fcm/send/err").sub("b"))
    assert await w.service.send(UID, kind="test", text="t") == 0
    assert [d.name for d in await w.store.list(UID)] == ["b"]


async def test_a_network_error_is_contained() -> None:
    import httpx

    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to secret-host")

    w.service._http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    assert await w.service.send(UID, kind="test", text="t") == 0


async def test_no_devices_means_no_request_and_no_audit_line() -> None:
    w = PushWorld()
    assert await w.service.send(UID, kind="test", text="t") == 0
    assert w.requests == [] and w.audit._entries == []


async def test_a_redirect_is_not_followed() -> None:
    import httpx

    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())
    seen: list[str] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    w.service._http = httpx.AsyncClient(
        transport=httpx.MockTransport(redirect), follow_redirects=False
    )
    assert await w.service.send(UID, kind="test", text="t") == 0
    assert len(seen) == 1


async def test_the_audit_line_has_counts_and_never_content() -> None:
    w = PushWorld({"/fcm/send/bad": 500})
    await w.service.subscribe(UID, **Browser().sub())
    await w.service.subscribe(UID, **Browser("https://fcm.googleapis.com/fcm/send/bad").sub("b"))
    await w.service.send(UID, kind="home_intruder", text="Someone is at your gate SECRETWORD.")
    [e] = [x for x in w.audit._entries if x.tool == "webpush_send"]
    assert e.agent == "alerts" and e.outcome == "sent"
    assert w.audit.args[-1] == {"kind": "home_intruder", "sent": 1, "failed": 1}
    assert "SECRETWORD" not in repr(w.audit.args) + repr(w.audit._entries)
    assert "fcm" not in repr(w.audit.args)


async def test_a_failing_audit_does_not_break_the_push() -> None:
    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())

    async def broken(**kw: object) -> None:
        raise RuntimeError("audit down")

    w.service._audit.append = broken  # type: ignore[method-assign]
    assert await w.service.send(UID, kind="test", text="t") == 1


async def test_a_stored_endpoint_is_checked_again_at_send_time() -> None:
    w = PushWorld()
    br = Browser()
    await w.service.subscribe(UID, **br.sub())

    async def inward(host: str) -> list[str]:
        return ["192.168.1.1"]

    w.service._resolver = inward
    assert await w.service.send(UID, kind="test", text="t") == 0 and w.requests == []
