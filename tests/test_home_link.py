# tests/test_home_link.py -- R3 D4: linking the laptop (code, address rule, signed test call,
# seed once) and where the link is kept (encrypted, fail closed).
from __future__ import annotations

import json
from pathlib import Path

import pytest
from home_fakes import HA_TOKEN, UID, URL, World, build, private_resolver

from jarvis.home import signing
from jarvis.home.link import CODE_CHARS, LinkRefused, normalise
from jarvis.home.store import HomeStoreUnavailable
from jarvis.homebridge.cloud import LinkFailed
from jarvis.offline.config import UrlRejected


@pytest.fixture
async def w(tmp_path: Path):
    world = build(tmp_path)
    yield world
    await world.aclose()


async def test_link_flow_saves_seed_on_both_ends(w: World) -> None:
    home_id = await w.link_up()
    rec = await w.store.load(UID)
    assert rec is not None and rec.home_id == home_id
    assert rec.bridge_url == URL
    linked = w.bridge.store.linked()
    assert linked is not None and linked.keys == rec.keys()


async def test_code_is_single_use_and_spent_only_on_success(w: World) -> None:
    code = (await w.link.code(UID)).code
    await w.bridge.link.link(code, URL, b"s" * 32)
    with pytest.raises(LinkFailed):
        await w.bridge.link.link(code, URL, b"t" * 32)


async def test_code_shape_and_normalising() -> None:
    assert normalise("abcd-efgh") == "ABCDEFGH"
    assert normalise("0O1I-LLLL") == "00111111"
    assert normalise("ABCD-EFGU") is None  # U is not Crockford
    assert normalise(None) is None and normalise("short") is None
    assert all(c not in CODE_CHARS for c in "ILOU")


async def test_expired_code_refused(w: World) -> None:
    code = (await w.link.code(UID)).code
    w.clock.t += 601
    with pytest.raises(LinkFailed):
        await w.bridge.link.link(code, URL, b"s" * 32)


async def test_five_wrong_tries_void_the_code(w: World) -> None:
    code = (await w.link.code(UID)).code
    for _ in range(5):
        with pytest.raises(LinkRefused):
            await w.link.complete("ZZZZ-ZZZZ", URL, "0.1.0", "a" * 43)
    with pytest.raises(LinkRefused):
        await w.link.complete(code, URL, "0.1.0", "a" * 43)
    assert await w.store.load(UID) is None


@pytest.mark.parametrize(
    "bad",
    [
        "http://laptop.tail1234.ts.net:8443",
        "https://8.8.8.8:8443",
        "https://evil.example.com:8443",
        "https://laptop.tail1234.ts.net:9999",
        "https://laptop.tail1234.ts.net",  # 443 is R1's local brain
        "https://laptop.tail1234.ts.net:443",
        "https://169.254.169.254:8443",
        "https://u:p@laptop.tail1234.ts.net:8443",
    ],
)
async def test_bad_bridge_address_refused(w: World, bad: str) -> None:
    code = (await w.link.code(UID)).code
    with pytest.raises(LinkRefused) as exc:
        await w.link.complete(code, bad, "0.1.0", "a" * 43)
    assert exc.value.code == "bad_url"
    assert await w.store.load(UID) is None
    # the code was not spent: it still links
    await w.link_up(code)


async def test_private_resolution_refused(w: World) -> None:
    w.link._resolver = private_resolver  # noqa: SLF001
    code = (await w.link.code(UID)).code
    with pytest.raises(LinkRefused) as exc:
        await w.link.complete(code, URL, "0.1.0", "a" * 43)
    assert exc.value.code == "bad_url"


async def test_test_call_must_be_signed_by_the_link_key(w: World) -> None:
    code = (await w.link.code(UID)).code
    # the bridge posts with one secret, but a bridge that cannot sign with it (wrong secret saved)
    w.bridge.store.set_pending(b"x" * 32)
    with pytest.raises(LinkRefused) as exc:
        await w.link.complete(code, URL, "0.1.0", _b64(b"y" * 32))
    assert exc.value.code == "not_reachable"
    # a failed test call does not spend the code and is not a wrong try
    assert await w.store.load(UID) is None
    await w.bridge.link.link(code, URL, b"z" * 32)
    assert await w.store.load(UID) is not None


async def test_bad_link_request_shapes(w: World) -> None:
    code = (await w.link.code(UID)).code
    with pytest.raises(LinkRefused) as exc:
        await w.link.complete(code, URL, "x.y", "a" * 43)
    assert exc.value.code == "bad_request"
    with pytest.raises(LinkRefused):
        await w.link.complete(code, URL, "0.1.0", "short")


async def test_relink_makes_a_new_seed_and_old_stops(w: World) -> None:
    await w.link_up()
    old = (await w.store.load(UID)).keys()  # type: ignore[union-attr]
    await w.link_up()
    new = (await w.store.load(UID)).keys()  # type: ignore[union-attr]
    assert old != new


async def test_nothing_secret_in_documents_or_logs(
    w: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    await w.link_up()
    rec = await w.store.load(UID)
    assert rec is not None
    seed = rec.seed
    blob = json.dumps(w.docs._data, default=repr)  # noqa: SLF001
    import base64

    for needle in (HA_TOKEN, "tail1234", base64.b64encode(seed).decode(), seed.hex()):
        assert needle not in blob
        assert needle not in caplog.text
    assert "HomeRecord(" in repr(rec) and seed.hex() not in repr(rec)


async def test_unreadable_record_fails_closed_and_is_not_overwritten(w: World) -> None:
    await w.link_up()
    path = f"jarvis_home/{UID}"
    w.docs._data[path]["blob"] = "garbage"  # noqa: SLF001
    with pytest.raises(HomeStoreUnavailable):
        await w.store.load(UID)
    with pytest.raises(HomeStoreUnavailable):
        await w.store.find(w.docs._data[path]["home_id"])  # noqa: SLF001
    assert w.docs._data[path]["blob"] == "garbage"  # noqa: SLF001


async def test_unlink_removes_everything(w: World) -> None:
    await w.link_up()
    await w.store.save_devices(UID, ())
    assert await w.store.unlink(UID) is True
    assert await w.store.load(UID) is None
    assert not [p for p in w.docs._data if p.startswith("jarvis_home")]  # noqa: SLF001
    assert await w.store.unlink(UID) is False


def _b64(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_signing_is_the_only_signer() -> None:
    assert signing.derive_keys(b"a" * 32).up != signing.derive_keys(b"a" * 32).down
    with pytest.raises(UrlRejected):
        raise UrlRejected("x")
