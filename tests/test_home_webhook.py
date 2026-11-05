# tests/test_home_webhook.py -- R3 D5: POST /home/webhook. Signature first, parsing second, bare
# answers, replay-proof, rate limited, signed replies. Plus heartbeat and hazard handling.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from home_fakes import UID, World, build

from jarvis.home import signing
from jarvis.home.ports import WEBHOOK_PATH, ExposedDevice


@pytest.fixture
async def w(tmp_path: Path):
    world = build(tmp_path)
    await world.link_up()
    yield world
    await world.aclose()


def hb(i: str = "hb-1", **over: Any) -> dict[str, Any]:
    base = {
        "id": i,
        "type": "heartbeat",
        "at": 1.0,
        "bridge_version": "0.1.0",
        "state_rev": 0,
        "parts": {"ha": True, "frigate": True, "cameras": [{"id": "gate", "online": True}]},
    }
    return {**base, **over}


def det(i: str = "ev-1", **over: Any) -> dict[str, Any]:
    base = {
        "id": i,
        "type": "detection",
        "camera": "gate",
        "zones": ["gate"],
        "label": "person",
        "start": 1.0,
        "score": 0.9,
    }
    return {**base, **over}


async def post(
    w: World,
    payload: Any,
    *,
    direction: str = "up",
    now_shift: float = 0.0,
    home_id: str | None = None,
    path: str = WEBHOOK_PATH,
    sign_body: bytes | None = None,
    nonce: str | None = None,
    raw: bytes | None = None,
) -> httpx.Response:
    rec = await w.store.load(UID)
    assert rec is not None
    body = raw if raw is not None else json.dumps(payload).encode()
    header = signing.sign(
        rec.keys(),
        direction,  # type: ignore[arg-type]
        home_id=home_id or rec.home_id,
        method="POST",
        target=path,
        body=sign_body if sign_body is not None else body,
        now=w.clock() + now_shift,
        nonce=nonce,
    )
    return await w.cloud.post(WEBHOOK_PATH, content=body, headers={signing.HEADER: header})


def bare(r: httpx.Response) -> bool:
    return r.content == b"" and signing.HEADER.lower() not in r.headers


async def audit_untouched(w: World) -> bool:
    return not [p for p in w.docs._data if "audit" in p]  # noqa: SLF001


async def test_good_heartbeat_is_answered_and_signed_down(w: World) -> None:
    r = await post(w, hb())
    assert r.status_code == 200 and "state" in r.json()
    rec = await w.store.load(UID)
    assert rec is not None
    # the reply is bound to a nonce we did not keep; verify shape and direction instead
    signed = signing.parse(r.headers[signing.HEADER])
    assert signed.home_id == rec.home_id
    status = await w.store.status(UID)
    assert status is not None and status.state == "online" and status.parts["frigate"] is True


async def test_no_header_wrong_key_reflected_key_are_bare_401(w: World) -> None:
    assert bare(await w.cloud.post(WEBHOOK_PATH, json=hb()))
    r = await post(w, hb("hb-2"), direction="down")  # the down-key used upward
    assert r.status_code == 401 and bare(r)
    rec = await w.store.load(UID)
    assert rec is not None
    other = signing.derive_keys(b"z" * 32)
    header = signing.sign(
        other, "up", home_id=rec.home_id, method="POST", target=WEBHOOK_PATH,
        body=b"{}", now=w.clock(),
    )  # fmt: skip
    r = await w.cloud.post(WEBHOOK_PATH, content=b"{}", headers={signing.HEADER: header})
    assert r.status_code == 401 and bare(r)


async def test_signature_over_another_body_path_or_home_is_refused(w: World) -> None:
    r = await post(w, hb("hb-3"), sign_body=b"{}")
    assert r.status_code == 401
    r = await post(w, hb("hb-4"), path="/home/link")
    assert r.status_code == 401
    r = await post(w, hb("hb-5"), home_id="h_00000000")
    assert r.status_code == 401 and bare(r)


@pytest.mark.parametrize("shift", [61, -61, 3600])
async def test_time_window(w: World, shift: float) -> None:
    assert (await post(w, hb(), now_shift=shift)).status_code == 401
    assert (await post(w, hb("hb-ok"), now_shift=59)).status_code == 200


async def test_replayed_nonce_refused_even_with_a_new_event(w: World) -> None:
    assert (await post(w, hb("a"), nonce="A" * 22)).status_code == 200
    assert (await post(w, hb("b"), nonce="A" * 22)).status_code == 401


async def test_forged_messages_do_not_burn_a_real_nonce(w: World) -> None:
    rec = await w.store.load(UID)
    assert rec is not None
    bad = signing.sign(
        signing.derive_keys(b"q" * 32), "up", home_id=rec.home_id, method="POST",
        target=WEBHOOK_PATH, body=b"{}", now=w.clock(), nonce="B" * 22,
    )  # fmt: skip
    await w.cloud.post(WEBHOOK_PATH, content=b"{}", headers={signing.HEADER: bad})
    assert (await post(w, hb("real"), nonce="B" * 22)).status_code == 200


async def test_malformed_header_and_oversize(w: World) -> None:
    for h in ("", "v1;h=x", "v2;" + "a" * 100, "v1;h=h_00000000;t=1;n=x;s=y" + "z" * 400):
        r = await w.cloud.post(WEBHOOK_PATH, json=hb(), headers={signing.HEADER: h})
        assert r.status_code == 401 and bare(r)
    r = await post(w, None, raw=b"x" * (128 * 1024 + 1))
    assert r.status_code == 413
    r = await post(w, None, raw=b"{" + b" " * 20000 + b"}")  # signed, over 16 KB, not an event
    assert r.status_code in (413, 422)


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "x1", "type": "bogus"},
        det("x2", extra="field"),
        det("x3", label="unicorn"),
        det("x4", camera="a/b"),
        det("x5", zones=["../x"]),
        det("x6", face={"person": "Anjali", "score": 0.95}),  # a name, not an id
        [1, 2],
    ],
)
async def test_signed_but_invalid_events_are_4xx_and_do_nothing(w: World, payload: Any) -> None:
    r = await post(w, payload)
    assert r.status_code == 422 and bare(r)
    assert not [p for p in w.docs._data if p.startswith("jarvis_home_claims")]  # noqa: SLF001


async def test_nothing_is_parsed_before_the_signature(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jarvis.home.webhook as mod

    def boom(raw: bytes) -> None:
        raise AssertionError("parsed an unsigned body")

    monkeypatch.setattr(mod, "parse_event", boom)
    r = await w.cloud.post(
        WEBHOOK_PATH,
        json=det(),
        headers={signing.HEADER: "v1;h=h_00000000;t=1;n=" + "A" * 22 + ";s=" + "B" * 43},
    )
    assert r.status_code == 401 and await audit_untouched(w)


async def test_replayed_event_id_is_a_noop_200(w: World) -> None:
    class Seen:
        handles = frozenset({"detection"})
        n = 0

        async def handle(self, uid: str, event: Any) -> None:
            Seen.n += 1

    w.webhook._handlers = (*w.webhook._handlers, Seen())  # noqa: SLF001
    assert (await post(w, det("same"))).status_code == 200
    assert (await post(w, det("same"))).status_code == 200  # a bridge retry: new nonce, same id
    assert Seen.n == 1


async def test_failed_handler_gives_the_claim_back(w: World) -> None:
    class Flaky:
        handles = frozenset({"detection"})
        fail = True

        async def handle(self, uid: str, event: Any) -> None:
            if Flaky.fail:
                raise RuntimeError("secret detail")

    w.webhook._handlers = (*w.webhook._handlers, Flaky())  # noqa: SLF001
    assert (await post(w, det("retry-me"))).status_code == 503
    Flaky.fail = False
    assert (await post(w, det("retry-me"))).status_code == 200


async def test_flood_past_the_limit_is_429(tmp_path: Path) -> None:
    world = build(tmp_path, per_minute=10)
    try:
        await world.link_up()
        codes = [(await post(world, hb(f"h{i}"))).status_code for i in range(14)]
        assert codes[:10] == [200] * 10 and 429 in codes[10:]
    finally:
        await world.aclose()


async def test_404_when_home_is_off(w: World) -> None:
    w.app.state.home_webhook = None
    r = await post(w, hb("off"))
    assert r.status_code == 404


async def test_snapshot_bytes_never_reach_documents_or_logs(
    w: World, caplog: pytest.LogCaptureFixture
) -> None:
    import base64

    jpeg = b"\xff\xd8\xff" + b"SNAPSHOT-NEEDLE" * 8
    got: list[Any] = []

    class Take:
        handles = frozenset({"detection"})

        async def handle(self, uid: str, event: Any) -> None:
            got.append(event.snapshot_bytes())

    w.webhook._handlers = (*w.webhook._handlers, Take())  # noqa: SLF001
    caplog.set_level("DEBUG")
    r = await post(w, det("snap", snapshot=base64.b64encode(jpeg).decode()))
    assert r.status_code == 200 and got == [jpeg]
    assert "SNAPSHOT-NEEDLE" not in json.dumps(w.docs._data, default=repr)  # noqa: SLF001
    assert (
        "SNAPSHOT-NEEDLE" not in caplog.text and base64.b64encode(jpeg).decode() not in caplog.text
    )


async def test_heartbeat_goes_offline_then_back_with_one_alert(w: World) -> None:
    w.arm.armed = True
    await post(w, hb("h1"))
    w.clock.t += 800
    out = await w.watchdog.run()
    assert out["offline"] == 1 and w.notes.kinds() == ["home_offline"]
    text = w.notes.sent[0][2]
    assert "stopped answering" in text and len(text) < 300
    w.clock.t += 300
    await w.watchdog.run()
    assert w.notes.kinds() == ["home_offline"]  # once per outage
    await post(w, hb("h2"))
    assert w.notes.kinds() == ["home_offline", "home_online"]


async def test_disarmed_outage_is_silent_but_state_changes(w: World) -> None:
    await post(w, hb("h1"))
    w.clock.t += 800
    await w.watchdog.run()
    assert w.notes.sent == []
    status = await w.store.status(UID)
    assert status is not None and status.state == "offline"
    await post(w, hb("h2"))
    assert w.notes.sent == []  # no alert had gone out, so no "back"


async def test_instance_restart_does_not_fake_an_outage(w: World) -> None:
    w.arm.armed = True
    await post(w, hb("h1"))
    w.clock.t += 200  # heartbeat not written again (in-process only)
    await post(w, hb("h2"))
    w.store._seen.clear()  # noqa: SLF001 - a new instance: only Firestore's value is left
    w.store._written.clear()  # noqa: SLF001
    w.clock.t += 400
    await w.watchdog.run()
    assert w.notes.sent == []  # stored value is at most 5 minutes stale, far below 12


async def test_watchdog_sweeps_claims_and_codes(w: World) -> None:
    await post(w, det("old-event"))
    await w.link.code(UID)
    w.clock.t += 49 * 3600
    out = await w.watchdog.run()
    assert out["swept"] >= 2
    assert not [p for p in w.docs._data if p.startswith("jarvis_home_claims")]  # noqa: SLF001


async def test_hazard_rings_only_for_an_exposed_sensor(w: World) -> None:
    ev = {
        "id": "hz1", "type": "hazard", "entity": "binary_sensor.kitchen_smoke",
        "device_class": "smoke", "state": "on", "at": 1.0,
    }  # fmt: skip
    await post(w, ev)
    assert w.notes.sent == []  # not exposed
    w.bridge_state = w.bridge_state
    w.ha_states[4]["attributes"]["device_class"] = "smoke"
    await w.devices.expose(
        UID,
        [{"entity_id": "binary_sensor.kitchen_smoke", "label": "Kitchen", "class": "read"}],
    )
    await post(w, {**ev, "id": "hz2"})
    assert w.notes.kinds() == ["home_hazard"] and "Smoke" in w.notes.sent[0][2]
    assert "Kitchen" in w.notes.sent[0][2]
    await post(w, {**ev, "id": "hz3", "state": "off"})
    await post(w, {**ev, "id": "hz4", "device_class": "gas"})  # class differs from exposed
    assert w.notes.kinds() == ["home_hazard"]


def test_exposed_device_model_refuses_never_exposed() -> None:
    with pytest.raises(ValueError):
        ExposedDevice(entity_id="script.go", tier="read")


async def _forge(w: World, home_id: str) -> httpx.Response:
    rec = await w.store.load(UID)
    assert rec is not None
    body = b"{}"
    header = signing.sign(
        rec.keys(), "up", home_id=home_id, method="POST", target=WEBHOOK_PATH,
        body=body, now=w.clock(),
    )  # fmt: skip
    return await w.cloud.post(WEBHOOK_PATH, content=body, headers={signing.HEADER: header})


def _count_queries(world: World) -> dict[str, int]:
    reads = {"n": 0}
    orig = world.store._d.query  # noqa: SLF001

    async def counting(q: Any) -> Any:
        reads["n"] += 1
        return await orig(q)

    world.store._d.query = counting  # noqa: SLF001
    return reads


async def test_forged_home_ids_are_cut_off_by_a_client_bucket_before_any_read(
    tmp_path: Path,
) -> None:
    """Review H1: a stranger cannot make one Firestore read per forged request."""
    world = build(tmp_path)
    try:
        await world.link_up()
        reads = _count_queries(world)
        codes = [(await _forge(world, f"h_{i:08x}")).status_code for i in range(200)]
        assert 429 in codes
        assert reads["n"] <= 120
        assert codes.count(401) <= 120
    finally:
        await world.aclose()


async def test_an_unknown_home_id_is_remembered_so_it_costs_one_read(tmp_path: Path) -> None:
    world = build(tmp_path)
    try:
        await world.link_up()
        reads = _count_queries(world)
        for _ in range(10):
            assert (await _forge(world, "h_deadbeef")).status_code == 401
        assert reads["n"] == 1
    finally:
        await world.aclose()


async def test_the_negative_cache_is_bounded_and_a_new_link_clears_it(tmp_path: Path) -> None:
    world = build(tmp_path)
    try:
        for i in range(2000):
            assert await world.store.find(f"h_{i:08x}") is None
        assert len(world.store._unknown) <= 512  # noqa: SLF001
        await world.link_up()
        rec = await world.store.load(UID)
        assert rec is not None
        assert await world.store.find(rec.home_id) is not None
    finally:
        await world.aclose()


# ---- integrated review S2 / H5 ------------------------------------------------------------------


async def test_handler_store_unavailable_gives_claim_back(w: World) -> None:
    """S2: a hazard whose handler hits a store blip answers 503 and gives its id back, so the
    bridge's retry (same id) still rings."""
    from jarvis.home.store import HomeStoreUnavailable

    w.ha_states[4]["attributes"]["device_class"] = "smoke"
    await w.devices.expose(
        UID,
        [{"entity_id": "binary_sensor.kitchen_smoke", "label": "Kitchen", "class": "read"}],
    )
    real = w.store.load_devices
    calls = {"n": 0}

    async def flaky(uid: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise HomeStoreUnavailable("blip")
        return await real(uid)

    w.store.load_devices = flaky  # type: ignore[method-assign]
    ev = {
        "id": "hz-blip", "type": "hazard", "entity": "binary_sensor.kitchen_smoke",
        "device_class": "smoke", "state": "on", "at": 1.0,
    }  # fmt: skip
    first = await post(w, ev)
    assert first.status_code == 503 and bare(first)
    assert (await post(w, ev)).status_code == 200
    assert w.notes.kinds() == ["home_hazard"]


async def test_a_claim_that_cannot_be_made_is_503_and_nothing_is_given_back(w: World) -> None:
    from jarvis.home.store import HomeStoreUnavailable

    async def down(uid: str, event_id: str) -> bool:
        raise HomeStoreUnavailable("down")

    released: list[str] = []

    async def release(uid: str, event_id: str) -> None:
        released.append(event_id)

    w.store.claim = down  # type: ignore[method-assign]
    w.store.release = release  # type: ignore[method-assign]
    assert (await post(w, det("no-claim"))).status_code == 503
    assert released == []  # nothing was claimed, so nothing is given back


class _Unheard:
    """A notifier whose every alert reached no channel."""

    def __init__(self) -> None:
        self.kinds: list[str] = []

    async def notify(self, uid: str, signal: Any, message: str, **_: Any) -> Any:
        from jarvis.notify.ports import Delivery

        self.kinds.append(signal.kind)
        return Delivery(action="ring", reason="urgent", telegram=False, push=0)


async def test_an_offline_alert_that_reached_nobody_is_not_counted_and_is_tried_again(
    w: World,
) -> None:
    """H5: the watchdog marks the outage alerted only when Telegram or a browser took it."""
    unheard = _Unheard()
    w.offline._notifier = unheard  # noqa: SLF001
    w.arm.armed = True
    await post(w, hb("h1"))
    w.clock.t += 800
    await w.watchdog.run()
    status = await w.store.status(UID)
    assert status is not None and status.state == "offline" and status.outage_alerted is False
    w.clock.t += 300
    await w.watchdog.run()
    assert unheard.kinds == ["home_offline", "home_offline"]  # tried again: nobody had it
    w.offline._notifier = w.notes  # noqa: SLF001
    w.clock.t += 300
    await w.watchdog.run()
    status = await w.store.status(UID)
    assert status is not None and status.outage_alerted is True
    w.clock.t += 300
    await w.watchdog.run()
    assert w.notes.kinds() == ["home_offline"]  # once delivered: once per outage
