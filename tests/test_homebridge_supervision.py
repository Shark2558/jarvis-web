# tests/test_homebridge_supervision.py -- integrated review M10 / M12 / hygiene: the bridge's
# plugin factories, task supervision and shutdown, and what each plugin may read from bridge.env.
from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.home.ports import BridgeState, HeartbeatParts
from jarvis.homebridge import __main__ as cli
from jarvis.homebridge.app import Supervisor, create_bridge
from jarvis.homebridge.config import BridgeConfig
from jarvis.homebridge.plugins import PLUGIN_ENV_KEYS, BridgeContext, FatalTaskError

URL = "https://jarvis.example.run.app"


class Fake:
    """A plugin with long-running tasks and an `aclose` (the protocol's optional close hook)."""

    name = "fake"

    def __init__(self, ctx: BridgeContext) -> None:
        self.ctx = ctx
        self.crashes = 0
        self.returns = 0
        self.fatal = 0
        self.cancelled = False
        self.closed = False

    def routes(self) -> Sequence[Any]:
        return ()

    def tasks(self) -> Sequence[Any]:
        return (self._crashes_once, self._returns, self._fatal, self._forever)

    async def _crashes_once(self) -> None:
        self.crashes += 1
        if self.crashes == 1:
            raise RuntimeError("first run fails")
        await asyncio.Event().wait()

    async def _returns(self) -> None:
        self.returns += 1
        if self.returns > 1:
            await asyncio.Event().wait()

    async def _fatal(self) -> None:
        self.fatal += 1
        raise FatalTaskError("can never work")

    async def _forever(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def heartbeat_part(self) -> HeartbeatParts:
        return HeartbeatParts()

    async def apply_state(self, state: BridgeState) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


def _cfg(tmp: Path) -> BridgeConfig:
    return BridgeConfig(jarvis_url=URL, data_dir=tmp)


def _boom(ctx: BridgeContext) -> Any:
    raise RuntimeError("the camera part could not start")


async def test_a_factory_that_raises_is_skipped_logged_and_reported_in_the_heartbeat(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    bridge = create_bridge(_cfg(tmp_path), (_boom, Fake))
    assert [p.name for p in bridge.plugins] == ["core", "fake"]
    assert any(
        getattr(r, "part", None) == "_boom" and getattr(r, "error", None) == "RuntimeError"
        for r in caplog.records
    )
    assert bridge.broken == ("_boom",)
    assert bridge.heartbeat is not None
    parts = await bridge.heartbeat.parts()
    assert parts.mqtt is False  # a part did not start: the cloud must not trust the camera


async def test_the_bridge_lifespan_supervises_every_task_and_closes_plugins(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """M12: the real lifespan with a fake plugin: every task started (heartbeat, core devices,
    the plugin's four), a crashed or returned task started again, a fatal one never, and on the
    way out the pending tasks are cancelled and `aclose` runs."""
    caplog.set_level(logging.WARNING)
    bridge = create_bridge(_cfg(tmp_path), (Fake,))
    bridge.supervisor = Supervisor(delay_s=0.01)
    fake: Fake = bridge.plugins[1]  # type: ignore[assignment]
    async with bridge.app.router.lifespan_context(bridge.app):
        assert len(bridge.supervisor._tasks) == 2 + 4  # noqa: SLF001
        for _ in range(100):
            if fake.crashes >= 2 and fake.returns >= 2:
                break
            await asyncio.sleep(0.01)
        assert fake.crashes == 2 and fake.returns == 2 and fake.fatal == 1
    assert fake.cancelled and fake.closed
    assert "a bridge task ended" in caplog.text and "can't run" in caplog.text


async def test_the_real_camera_and_faces_plugins_run_under_the_lifespan_and_close(
    tmp_path: Path,
) -> None:
    """M12: the registry's two plugins (on fakes: no broker, no Frigate) start their tasks under
    the bridge's lifespan (heartbeat, core devices, camera MQTT, faces deletes and sweeps) and are
    closed on the way out (MQTT stopped, Frigate's clients closed)."""
    from frigate_fakes import FrigateFake, fake_connect
    from test_homebridge_faces import FakeLib

    from jarvis.homebridge.camera import CameraPlugin
    from jarvis.homebridge.faces import FacesPlugin

    closed: list[str] = []

    class Lib(FakeLib):
        async def aclose(self) -> None:
            closed.append("faces")

    frigate = FrigateFake().client()

    def camera(ctx: BridgeContext) -> CameraPlugin:
        return CameraPlugin(ctx, frigate=frigate, connect=fake_connect([OSError("down")], []))

    def faces(ctx: BridgeContext) -> FacesPlugin:
        return FacesPlugin(ctx, Lib())

    env = {"MQTT_USER": "bridge", "MQTT_PASSWORD": "pw", "FACES_ATTEMPTS_DIR": str(tmp_path)}
    bridge = create_bridge(_cfg(tmp_path / "data"), (camera, faces), env=env)
    assert [p.name for p in bridge.plugins] == ["core", "camera", "faces"] and bridge.broken == ()
    cam: CameraPlugin = bridge.plugins[1]  # type: ignore[assignment]
    async with bridge.app.router.lifespan_context(bridge.app):
        assert len(bridge.supervisor._tasks) == 2 + 1 + 2  # noqa: SLF001
        await asyncio.sleep(0.05)
        parts = await bridge.heartbeat.parts()  # type: ignore[union-attr]
        assert parts.mqtt is False and parts.frigate is True  # the broker is "down"
    assert closed == ["faces"] and frigate._client.is_closed  # noqa: SLF001
    assert cam.mqtt._stopped  # noqa: SLF001


def test_plugins_get_only_their_own_settings_never_the_home_assistant_token(
    tmp_path: Path,
) -> None:
    env = {
        "HA_TOKEN": "ha-secret-token",
        "JARVIS_URL": URL,
        "MQTT_USER": "bridge",
        "MQTT_PASSWORD": "pw",
        "FRIGATE_URL": "http://frigate:5000",
        "FACES_BIND": "0.0.0.0",
        "PATH": "/usr/bin",
    }
    bridge = create_bridge(_cfg(tmp_path), (Fake,), env=env)
    seen = dict(bridge.plugins[1].ctx.env)  # type: ignore[attr-defined]
    assert "HA_TOKEN" not in seen and "PATH" not in seen and "JARVIS_URL" not in seen
    assert seen == {k: v for k, v in env.items() if k in PLUGIN_ENV_KEYS}
    assert {"MQTT_USER", "MQTT_PASSWORD", "FRIGATE_URL", "FACES_BIND"} <= PLUGIN_ENV_KEYS


def test_a_plugin_registry_that_cannot_be_imported_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "jarvis.homebridge.registry", None)
    caplog.set_level(logging.ERROR)
    assert tuple(cli._registry()) == ()  # noqa: SLF001
    assert "camera and faces are OFF" in caplog.text
