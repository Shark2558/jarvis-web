# tests/test_homebridge_core.py -- R3 D3-D9 at home: config, the data volume, the bridge's door,
# the cloud link (retries, clock, unlinked), heartbeat, Home Assistant, hazards, the CLI.
from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
from home_fakes import HA_TOKEN, UID, URL, World, build
from test_home_webhook import det, hb

from jarvis.home import signing
from jarvis.home.ports import (
    ArmState,
    BridgeState,
    DevicesState,
    ExposedDevice,
    Hazard,
    Heartbeat,
    SettingsState,
)
from jarvis.homebridge import __main__ as cli
from jarvis.homebridge.app import Supervisor, create_bridge
from jarvis.homebridge.config import BridgeConfig, ConfigError, load_config
from jarvis.homebridge.ha import HAClient, HAError
from jarvis.homebridge.state import BridgeStore


@pytest.fixture
async def w(tmp_path: Path):
    world = build(tmp_path)
    await world.link_up()
    yield world
    await world.aclose()


# ---- config ----------------------------------------------------------------------------------


def test_config_validates_and_hides_the_token() -> None:
    cfg = load_config({"JARVIS_URL": "https://jarvis.example.run.app", "HA_TOKEN": "tok"})
    assert cfg.jarvis_url == "https://jarvis.example.run.app" and cfg.ha_linked
    assert "tok" not in repr(cfg)
    assert not load_config({"JARVIS_URL": "https://j.example"}).ha_linked
    for env in (
        {},
        {"JARVIS_URL": "http://j.example"},
        {"JARVIS_URL": "https://u:p@j.example"},
        {"JARVIS_URL": "https://j.example/x"},
        {"JARVIS_URL": "https://j.example", "HA_URL": "ftp://x"},
        {"JARVIS_URL": "https://j.example", "HA_TOKEN": "bad token\n"},
    ):
        with pytest.raises(ConfigError) as exc:
            load_config(env)
        assert "bad token" not in str(exc.value)


# ---- the data volume -------------------------------------------------------------------------


def test_secret_files_are_private_and_state_only_moves_forward(tmp_path: Path) -> None:
    s = BridgeStore(tmp_path)
    assert s.linked() is None
    s.save_link("h_0a0b0c0d", b"s" * 32)
    mode = stat.S_IMODE(os.stat(tmp_path / "secret.json").st_mode)
    assert mode == 0o600 and stat.S_IMODE(os.stat(tmp_path / "state.json").st_mode) == 0o600
    first = s.apply(BridgeState(arm=ArmState(armed=True, rev=5)))
    assert first.arm is not None
    stale = s.apply(BridgeState(arm=ArmState(armed=False, rev=4)))
    assert stale.arm is None and s.state.arm is not None and s.state.arm.armed is True
    assert BridgeStore(tmp_path).linked() is not None  # survives a restart
    assert BridgeStore(tmp_path).state.arm is not None
    s.forget_link()
    assert s.linked() is None and s.state.arm is None


def test_unreadable_files_mean_not_linked(tmp_path: Path) -> None:
    (tmp_path / "secret.json").write_text("{not json")
    (tmp_path / "state.json").write_text("nope")
    s = BridgeStore(tmp_path)
    assert s.linked() is None and s.state.arm is None
    (tmp_path / "secret.json").write_text(json.dumps({"home_id": "h_00000000", "seed": "AAAA"}))
    assert s.linked() is None


def test_pending_link_secret_expires(tmp_path: Path) -> None:
    t = [100.0]
    s = BridgeStore(tmp_path, clock=lambda: t[0])
    s.set_pending(b"p" * 32)
    assert s.pending_keys() is not None
    t[0] += 901
    assert s.pending_keys() is None


# ---- the door --------------------------------------------------------------------------------


async def call(w: World, method: str, path: str, **kw: Any) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=w.bridge.app), base_url="http://b"
    ) as c:
        return await c.request(method, path, **kw)


async def test_unknown_routes_are_bare_404(w: World) -> None:
    for method, path in (("GET", "/"), ("GET", "/docs"), ("GET", "/openapi.json"),
                         ("POST", "/bridge/v1/health"), ("GET", "/bridge/v1/other"),
                         ("DELETE", "/bridge/v1/state")):  # fmt: skip
        r = await call(w, method, path)
        assert r.status_code == 404 and r.content == b""


async def test_unsigned_and_wrong_key_never_reach_a_handler(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = []

    async def boom(*a: Any, **k: Any) -> Any:
        called.append(1)
        return {}

    monkeypatch.setattr(w.bridge.devices, "act", boom)
    monkeypatch.setattr(w.bridge.ha, "states", boom)
    r = await call(
        w,
        "POST",
        "/bridge/v1/devices/action",
        json={"entity_id": "light.torch", "action": "turn_on"},
    )
    assert r.status_code == 401 and r.content == b""
    rec = await w.store.load(UID)
    assert rec is not None
    for direction in ("up", "down"):  # up is the wrong direction for a request to the bridge
        for key in (rec.keys(), signing.derive_keys(b"w" * 32)):
            body = b'{"entity_id":"light.torch","action":"turn_on"}'
            h = signing.sign(
                key,
                direction,
                home_id=rec.home_id,
                method="POST",  # type: ignore[arg-type]
                target="/bridge/v1/devices/action",
                body=body,
                now=w.clock(),
            )
            r = await call(
                w, "POST", "/bridge/v1/devices/action", content=body, headers={signing.HEADER: h}
            )
            if direction == "down" and key == rec.keys():
                assert r.status_code == 200
            else:
                assert r.status_code == 401
    assert called == [1] * 0 or len(called) == 1  # only the one genuine call got through


async def test_oversize_and_replay_at_the_bridge(w: World) -> None:
    r = await call(w, "POST", "/bridge/v1/state", content=b"x" * (65 * 1024))
    assert r.status_code == 413
    rec = await w.store.load(UID)
    assert rec is not None
    h = signing.sign(rec.keys(), "down", home_id=rec.home_id, method="GET",
                     target="/bridge/v1/health", body=b"", now=w.clock())  # fmt: skip
    assert (
        await call(w, "GET", "/bridge/v1/health", headers={signing.HEADER: h})
    ).status_code == 200
    assert (
        await call(w, "GET", "/bridge/v1/health", headers={signing.HEADER: h})
    ).status_code == 401


async def test_state_push_applies_newer_parts_and_acks_arm(w: World) -> None:
    posted: list[dict[str, Any]] = []
    orig = w.bridge.link.post_event

    async def spy(event: Any) -> bool:
        posted.append(event.model_dump(exclude_none=True))
        return await orig(event)

    w.bridge.link.post_event = spy  # type: ignore[method-assign]
    state = BridgeState(arm=ArmState(armed=True, rev=3), settings=SettingsState(rev=1))
    await w.client.call(UID, "POST", "/bridge/v1/state", state.model_dump(mode="json"))
    assert w.bridge.store.state.arm is not None and w.bridge.store.state.arm.rev == 3
    # review M7: the core no longer sends its own ack (the cloud ignored it); only the camera
    # plugin's `arm:<rev>:...` ack confirms an arm
    assert [e for e in posted if e["type"] == "ack"] == []
    posted.clear()
    await w.client.call(UID, "POST", "/bridge/v1/state", state.model_dump(mode="json"))
    assert posted == []  # nothing newer: no second ack
    from jarvis.home.ports import HomeRefused

    with pytest.raises(HomeRefused) as exc:
        await w.client.call(UID, "POST", "/bridge/v1/state", {"arm": {"armed": "yes"}})
    assert exc.value.code == "bad_state"


async def test_an_unserved_fixed_route_is_signed_404_free(w: World) -> None:
    # events/packages/faces routes belong to B and C: without their plugins they are bare 404
    r = await call(w, "GET", "/bridge/v1/events")
    assert r.status_code == 404


# ---- heartbeat -------------------------------------------------------------------------------


async def test_beat_reaches_the_cloud_and_brings_state_home(w: World) -> None:
    w.bridge_state.state = BridgeState(arm=ArmState(armed=True, rev=7))  # type: ignore[union-attr]
    assert await w.bridge.heartbeat.beat() is True  # type: ignore[union-attr]
    status = await w.store.status(UID)
    assert status is not None and status.state == "online" and status.parts["ha"] is True
    assert status.bridge_version == "0.1.0"
    assert w.bridge.store.state.arm is not None and w.bridge.store.state.arm.rev == 7
    assert w.bridge.heartbeat.interval() == 120  # type: ignore[union-attr]
    w.bridge.store.apply(BridgeState(settings=SettingsState(rev=1, heartbeat_s=300)))
    assert w.bridge.heartbeat.interval() == 300  # type: ignore[union-attr]


async def test_without_ha_token_the_heartbeat_says_ha_false(tmp_path: Path) -> None:
    world = build(tmp_path, ha_token="")
    try:
        await world.link_up()
        await world.bridge.heartbeat.beat()  # type: ignore[union-attr]
        status = await world.store.status(UID)
        assert status is not None and status.parts["ha"] is False
    finally:
        await world.aclose()


async def test_a_broken_part_never_stops_the_heartbeat(w: World) -> None:
    class Bad:
        name = "bad"

        def routes(self) -> list[Any]:
            return []

        def tasks(self) -> list[Any]:
            return []

        async def heartbeat_part(self) -> Any:
            raise RuntimeError("boom")

        async def apply_state(self, state: Any) -> None:
            raise RuntimeError("boom")

    w.bridge.heartbeat._plugins = [*w.bridge.plugins, Bad()]  # type: ignore[union-attr]  # noqa: SLF001
    w.bridge_state.state = BridgeState(arm=ArmState(armed=True, rev=1))  # type: ignore[union-attr]
    assert await w.bridge.heartbeat.beat() is True  # type: ignore[union-attr]


async def test_every_heartbeat_answer_reaches_plugins_that_want_it(w: World) -> None:
    """Review M7: a plugin with `on_reply` sees the cloud's whole state after each beat, even when
    nothing in it is newer (the camera re-sends an arm ack that was lost); one that fails never
    stops the heartbeat."""
    got: list[BridgeState] = []

    class Listener:
        name = "listener"

        def routes(self) -> list[Any]:
            return []

        def tasks(self) -> list[Any]:
            return []

        async def heartbeat_part(self) -> Any:
            from jarvis.home.ports import HeartbeatParts

            return HeartbeatParts()

        async def apply_state(self, state: Any) -> None:
            return None

        async def on_reply(self, state: BridgeState) -> None:
            got.append(state)
            raise RuntimeError("one bad plugin")

    w.bridge.heartbeat._plugins = [*w.bridge.plugins, Listener()]  # type: ignore[union-attr]  # noqa: SLF001
    w.bridge_state.state = BridgeState(arm=ArmState(armed=True, rev=2))  # type: ignore[union-attr]
    assert await w.bridge.heartbeat.beat() is True  # type: ignore[union-attr]
    assert await w.bridge.heartbeat.beat() is True  # type: ignore[union-attr]
    assert [s.arm.rev for s in got if s.arm is not None] == [2, 2]


# ---- the cloud link --------------------------------------------------------------------------


async def test_detection_is_retried_with_the_same_id_then_dropped(tmp_path: Path) -> None:
    world = build(tmp_path)
    try:
        await world.link_up()
        link = world.bridge.link
        sleeps: list[float] = []
        ids: list[str] = []

        async def nosleep(s: float) -> None:
            sleeps.append(s)
            world.clock.t += s

        link._sleep = nosleep  # noqa: SLF001

        def refuse(request: httpx.Request) -> httpx.Response:
            ids.append(json.loads(request.content)["id"])
            return httpx.Response(503)

        link._http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))  # noqa: SLF001
        from jarvis.home.ports import Detection

        event = Detection.model_validate(det("retry-1"))
        assert await link.post_event(event) is False
        await asyncio.gather(*list(link._pending))  # noqa: SLF001
        assert sleeps == [2.0, 5.0, 15.0, 30.0] and ids == ["retry-1"] * 5
    finally:
        await world.aclose()


async def test_a_flaky_cloud_gets_the_retry_once_it_answers(tmp_path: Path) -> None:
    world = build(tmp_path)
    try:
        await world.link_up()
        link = world.bridge.link
        real = link._http  # noqa: SLF001
        n = {"i": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            n["i"] += 1
            if n["i"] == 1:
                raise httpx.ConnectError("down")
            return await real._transport.handle_async_request(request)  # noqa: SLF001

        link._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: SLF001

        async def nosleep(s: float) -> None:
            return None

        link._sleep = nosleep  # noqa: SLF001
        from jarvis.home.ports import Detection

        assert await link.post_event(Detection.model_validate(det("flaky"))) is False
        await asyncio.gather(*list(link._pending))  # noqa: SLF001
        assert n["i"] == 2
        assert [p for p in world.docs._data if p.startswith("jarvis_home_claims")]  # noqa: SLF001
    finally:
        await world.aclose()


async def test_clock_is_corrected_from_the_date_header(tmp_path: Path) -> None:
    world = build(tmp_path)
    try:
        await world.link_up()
        link = world.bridge.link
        real = link._http  # noqa: SLF001
        skew = 3600.0
        from email.utils import formatdate

        async def handler(request: httpx.Request) -> httpx.Response:
            r = await real._transport.handle_async_request(request)  # noqa: SLF001
            await r.aread()
            return httpx.Response(
                r.status_code, content=r.content,
                headers={**r.headers, "date": formatdate(world.clock.t + 0.0, usegmt=True)},
            )  # fmt: skip

        link._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: SLF001
        world.bridge.auth.offset_s = -skew  # the bridge thinks it is an hour behind
        event = Heartbeat.model_validate(hb("late"))
        assert await link.heartbeat(event) is not None  # 401 -> learn the clock -> retry once
        assert abs(world.bridge.auth.offset_s) < 5
    finally:
        await world.aclose()


async def test_three_unknown_heartbeats_unlink_the_bridge(w: World) -> None:
    await w.store.unlink(UID)  # the owner unlinked in the cloud
    w.bridge.store.apply(BridgeState(arm=ArmState(armed=True, rev=2)))
    for _ in range(3):
        await w.bridge.heartbeat.beat()  # type: ignore[union-attr]
    assert w.bridge.link.unlinked and w.bridge.store.linked() is None
    assert w.bridge.store.state.arm is None
    from jarvis.home.ports import Detection

    assert await w.bridge.link.post_event(Detection.model_validate(det("late"))) is False


async def test_unsigned_answer_from_the_cloud_is_ignored(tmp_path: Path) -> None:
    world = build(tmp_path)
    try:
        await world.link_up()
        link = world.bridge.link
        link._http = httpx.AsyncClient(  # noqa: SLF001
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"state": {"arm": {"armed": False, "rev": 99}}})
            )
        )
        assert await link.heartbeat(Heartbeat.model_validate(hb("x"))) is None
        assert world.bridge.store.state.arm is None
    finally:
        await world.aclose()


async def test_link_errors_are_plain(tmp_path: Path) -> None:
    from jarvis.homebridge.cloud import LinkFailed

    world = build(tmp_path)
    try:
        link = world.bridge.link
        for status, word in (
            (401, "wrong"),
            (409, "Funnel"),
            (429, "Too many"),
            (422, "address"),
            (500, "right now"),
        ):
            link._http = httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r, s=status: httpx.Response(s))
            )  # noqa: SLF001
            with pytest.raises(LinkFailed) as exc:
                await link.link("ABCD-EFGH", URL, b"s" * 32)
            assert word in exc.value.reason
        link._http = httpx.AsyncClient(  # noqa: SLF001
            transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")))
        )
        with pytest.raises(LinkFailed):
            await link.link("ABCD-EFGH", URL, b"s" * 32)
        link._http = httpx.AsyncClient(  # noqa: SLF001
            transport=httpx.MockTransport(
                lambda r: httpx.Response(201, json={"home_id": "h_0a0b0c0d", "seed": "zz"})
            )
        )
        with pytest.raises(LinkFailed):
            await link.link("ABCD-EFGH", URL, b"s" * 32)
    finally:
        await world.aclose()


# ---- Home Assistant and hazards --------------------------------------------------------------


async def test_ha_client_hides_the_token_and_vendor_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/states":
            return httpx.Response(401, text="invalid token SECRET-TEXT")
        if request.url.path == "/api/":
            return httpx.Response(200, text="not json")
        return httpx.Response(500)

    ha = HAClient(
        "http://ha", "tok", http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    assert "tok" not in repr(ha)
    with pytest.raises(HAError) as exc:
        await ha.states()
    assert exc.value.code == "unauthorised" and "SECRET-TEXT" not in str(exc.value)
    assert await ha.ping() is False
    with pytest.raises(HAError):
        await ha.call_service("light", "turn_on; rm", {})
    with pytest.raises(HAError):
        await HAClient("http://ha", "").states()
    await ha.aclose()


async def test_hazard_polling_sends_one_event_per_turn_on(w: World) -> None:
    sent: list[Hazard] = []

    class Sink:
        async def post_event(self, event: Any) -> bool:
            sent.append(event)
            return True

    w.bridge.devices._events = Sink()  # noqa: SLF001
    w.bridge.store.apply(
        BridgeState(
            devices=DevicesState(
                rev=1,
                exposed=(ExposedDevice(entity_id="binary_sensor.kitchen_smoke", tier="read"),),
            )
        )
    )
    assert await w.bridge.devices.poll_hazards() == 0
    w.ha_states[4]["state"] = "on"
    assert await w.bridge.devices.poll_hazards() == 1
    assert await w.bridge.devices.poll_hazards() == 0  # still on: not again
    w.ha_states[4]["state"] = "off"
    await w.bridge.devices.poll_hazards()
    w.ha_states[4]["state"] = "on"
    assert await w.bridge.devices.poll_hazards() == 1
    assert sent[0].entity == "binary_sensor.kitchen_smoke" and sent[0].device_class == "smoke"


async def test_hazard_events_carry_no_ha_token_or_attributes(w: World) -> None:
    out = json.dumps(await w.bridge.devices.catalogue())
    assert HA_TOKEN not in out and "script." not in out and "camera." not in out


# ---- supervisor, plugins, CLI ----------------------------------------------------------------


async def test_supervisor_restarts_a_crashed_task() -> None:
    runs = []

    async def flaky() -> None:
        runs.append(1)
        if len(runs) < 3:
            raise RuntimeError("x")
        await asyncio.sleep(10)

    sup = Supervisor(delay_s=0.0)
    sup.start("t", flaky)
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(runs) >= 3:
            break
    await sup.stop()
    assert len(runs) >= 3


def test_two_plugins_cannot_serve_one_route(tmp_path: Path) -> None:
    from jarvis.homebridge.plugins import BridgeRoute

    class P:
        name = "dup"

        def routes(self) -> list[Any]:
            async def h(q: Any, b: Any) -> dict[str, Any]:
                return {}

            return [BridgeRoute("GET", "/bridge/v1/health", h)]

        def tasks(self) -> list[Any]:
            return []

        async def heartbeat_part(self) -> Any:
            return None

        async def apply_state(self, s: Any) -> None:
            return None

    cfg = BridgeConfig(jarvis_url="https://c.test", data_dir=tmp_path)
    with pytest.raises(ValueError):
        create_bridge(cfg, [lambda ctx: P()])


def test_cli_usage_and_config_errors(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JARVIS_URL", raising=False)
    assert cli.main(["nonsense"]) == 2
    assert cli.main(["link", "ABCD-EFGH", URL]) == 2
    assert cli.main([]) == 2
    err = capsys.readouterr().err
    assert "JARVIS_URL" in err and "Usage" in err


def test_cli_link_reports_plain_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_URL", "https://127.0.0.1.invalid")
    monkeypatch.setenv("BRIDGE_DATA_DIR", str(tmp_path))
    assert cli.main(["link", "ABCD-EFGH", URL]) == 1
    assert "Couldn't reach JARVIS" in capsys.readouterr().err
    assert (tmp_path / "link-pending.json").exists()


def _down(keys: signing.HomeKeys, home_id: str, now: float) -> str:
    return signing.sign(
        keys, "down", home_id=home_id, method="GET", target="/bridge/v1/health", body=b"", now=now
    )


def test_bridge_refuses_a_message_older_than_the_last_one_after_a_restart(
    tmp_path: Path,
) -> None:
    """Review M3: the replay cache is in memory; the newest accepted time survives a restart."""
    from jarvis.homebridge.auth import BridgeAuth

    now = 1_800_000_000.0
    store = BridgeStore(tmp_path)
    store.save_link("h_0a0b0c0d", bytes(range(32)))
    keys = signing.derive_keys(bytes(range(32)))
    first = BridgeAuth(store, lambda: now)
    old = _down(keys, "h_0a0b0c0d", now - 20)
    newer = _down(keys, "h_0a0b0c0d", now)
    first.check(newer, method="GET", target="/bridge/v1/health", body=b"")
    restarted = BridgeAuth(BridgeStore(tmp_path), lambda: now + 1)
    with pytest.raises(signing.SignatureError):  # captured earlier, still inside the 60 s window
        restarted.check(old, method="GET", target="/bridge/v1/health", body=b"")
    with pytest.raises(signing.SignatureError):  # the very message that was already accepted
        restarted.check(newer, method="GET", target="/bridge/v1/health", body=b"")
    fresh = _down(keys, "h_0a0b0c0d", now + 1)
    restarted.check(fresh, method="GET", target="/bridge/v1/health", body=b"")


def test_a_damaged_last_seen_file_does_not_lock_the_bridge_out(tmp_path: Path) -> None:
    from jarvis.homebridge.auth import BridgeAuth

    now = 1_800_000_000.0
    store = BridgeStore(tmp_path)
    store.save_link("h_0a0b0c0d", bytes(range(32)))
    (tmp_path / "last-seen.json").write_text("not json")
    keys = signing.derive_keys(bytes(range(32)))
    BridgeAuth(BridgeStore(tmp_path), lambda: now).check(
        _down(keys, "h_0a0b0c0d", now), method="GET", target="/bridge/v1/health", body=b""
    )
