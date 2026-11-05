# src/jarvis/homebridge/mqtt.py
"""Frigate's MQTT events into the bridge (R3 D7). Mosquitto is on the compose network only.

`MqttEvents.run()` keeps one subscription alive: it connects, subscribes to the three Frigate
topics the camera feature needs and hands every message (topic, payload) to one handler. A
connection that fails is retried with a growing pause (1 s up to 60 s); a session that subscribed
starts the pause again at 1 s (integrated review M6); a handler that fails never stops the loop.
`connected` is True only while a subscribed session runs: the camera's heartbeat part reports it,
so the cloud knows when burglar alerts can't arrive. `aiomqtt` is imported only when a real
connection is made (it is in the bridge image, hash-locked in bridge-requirements.txt, not in the
cloud's), so tests give `connect` a fake. If it is missing the loop stops for good with an error
line (`FatalTaskError`), never silent retries (review C1).

Bridge-kit module: standard library only (+ aiomqtt at run time).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any

from jarvis.homebridge.plugins import FatalTaskError

log = logging.getLogger(__name__)
NO_LIBRARY = (
    "The MQTT library is missing from the bridge image, so camera alerts can't work. "
    "Download the home kit again and run setup-wsl.sh up."
)

TOPICS = (
    "frigate/events",
    "frigate/tracked_object_update",
    "frigate/+/classification/doorstep",
)
MAX_PAYLOAD = 64 * 1024
Handler = Callable[[str, bytes], Awaitable[None]]
Connect = Callable[[], AbstractAsyncContextManager[Any]]


class MqttCredentialsMissing(RuntimeError):
    """MQTT_USER or MQTT_PASSWORD is empty: the bridge never listens to an open broker."""


@dataclass(frozen=True)
class MqttConfig:
    host: str = "mosquitto"
    port: int = 1883
    user: str = ""
    password: str = field(default="", repr=False)  # never in a log line or a traceback

    @property
    def has_credentials(self) -> bool:
        return bool(self.user.strip()) and bool(self.password.strip())

    @classmethod
    def from_env(cls, env: dict[str, str] | Any) -> MqttConfig:
        port_text = str(env.get("MQTT_PORT", "1883"))
        port = int(port_text) if port_text.isdigit() and 0 < int(port_text) < 65536 else 1883
        return cls(
            host=str(env.get("MQTT_HOST", "mosquitto")) or "mosquitto",
            port=port,
            user=str(env.get("MQTT_USER", "")),
            password=str(env.get("MQTT_PASSWORD", "")),
        )


def real_connect(cfg: MqttConfig) -> Connect:
    def make() -> AbstractAsyncContextManager[Any]:
        if not cfg.has_credentials:  # refuse anonymous: the run loop reports it and retries
            raise MqttCredentialsMissing("MQTT_USER and MQTT_PASSWORD must both be set")
        import aiomqtt  # the bridge image only

        client: AbstractAsyncContextManager[Any] = aiomqtt.Client(
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.user,
            password=cfg.password,
            identifier="jarvis-bridge",
        )
        return client

    return make


class MqttEvents:
    def __init__(
        self,
        connect: Connect,
        handler: Handler,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_pause_s: float = 60.0,
    ) -> None:
        self._connect = connect
        self._handler = handler
        self._sleep = sleep
        self._max_pause = max_pause_s
        self._stopped = False
        self._pause = 1.0
        self.connected = False  # a subscribed session is running right now

    def stop(self) -> None:
        self._stopped = True

    async def _session(self) -> None:
        async with self._connect() as client:
            for topic in TOPICS:
                await client.subscribe(topic)
            self.connected, self._pause = True, 1.0
            async for message in client.messages:
                if self._stopped:
                    return
                payload = message.payload
                data = payload.encode() if isinstance(payload, str) else bytes(payload or b"")
                if len(data) > MAX_PAYLOAD:
                    continue
                try:
                    await self._handler(str(message.topic), data)
                except Exception as exc:  # noqa: BLE001 - one bad message never stops the loop
                    log.warning("mqtt message failed", extra={"reason": type(exc).__name__})

    async def run(self) -> None:
        self._pause = 1.0
        while not self._stopped:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except ImportError:  # the image has no MQTT library: retrying can't help
                log.critical(NO_LIBRARY)
                raise FatalTaskError("mqtt library missing") from None
            except Exception as exc:  # noqa: BLE001 - connection trouble: wait and try again
                log.warning("mqtt disconnected", extra={"reason": type(exc).__name__})
            finally:
                self.connected = False
            if self._stopped:
                return
            await self._sleep(self._pause)
            self._pause = min(self._pause * 2, self._max_pause)


__all__ = ["TOPICS", "MqttConfig", "MqttCredentialsMissing", "MqttEvents", "real_connect"]
