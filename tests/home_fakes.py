# tests/home_fakes.py -- a cloud and a home bridge wired together in process (R3 A).
# The cloud's /home/* doors and the real bridge app talk through ASGI transports; Home Assistant is
# an httpx MockTransport; DNS is a fake resolver; the clock is a list. No network, no Docker.
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from jarvis.alerts import AlertKind
from jarvis.api.home import install_home
from jarvis.home.client import HomeClient
from jarvis.home.devices import DeviceService
from jarvis.home.heartbeat import HazardHandler, HeartbeatHandler
from jarvis.home.link import LinkService
from jarvis.home.ports import ArmView, BridgeState
from jarvis.home.store import HomeStore
from jarvis.home.watchdog import OfflineJob, Watchdog
from jarvis.home.webhook import HomeWebhook
from jarvis.homebridge.app import Bridge, create_bridge
from jarvis.homebridge.config import BridgeConfig
from jarvis.keyring import Keyring
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import MemoryDocs

UID = "u_owner"
ROOT = bytes(range(1, 33))
URL = "https://laptop.tail1234.ts.net:8443"
HA_TOKEN = "ha-long-lived-token-SECRET-123"
PUBLIC_IP = "8.8.8.8"


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


async def public_resolver(host: str) -> list[str]:
    return [PUBLIC_IP]


async def private_resolver(host: str) -> list[str]:
    return ["10.0.0.7"]


class Notes:
    """A Notifier that records what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, Signal, str]] = []

    async def notify(
        self, uid: str, signal: Signal, message: str, *, named_message=None, photo=None
    ) -> Delivery:
        self.sent.append((uid, signal, message))
        return Delivery(action="ring", reason="test", telegram=True)

    def kinds(self) -> list[AlertKind]:
        return [s.kind for _, s, _ in self.sent]


class Arm:
    def __init__(self, armed: bool = False) -> None:
        self.armed = armed

    async def view(self, uid: str) -> ArmView:
        return ArmView(armed=self.armed, mode="away", rev=1, confirmed=True)


class StateBits:
    def __init__(self, state: BridgeState) -> None:
        self.state = state

    async def state_part(self, uid: str) -> BridgeState:
        return self.state


HA_STATES: list[dict[str, Any]] = [
    {"entity_id": "light.torch", "state": "off", "attributes": {"friendly_name": "Torch"}},
    {"entity_id": "switch.plug", "state": "off", "attributes": {"friendly_name": "Geyser plug"}},
    {"entity_id": "lock.gate", "state": "locked", "attributes": {"friendly_name": "Gate lock"}},
    {
        "entity_id": "cover.shutter",
        "state": "closed",
        "attributes": {"friendly_name": "Shutter", "device_class": "garage"},
    },
    {
        "entity_id": "binary_sensor.kitchen_smoke",
        "state": "off",
        "attributes": {"friendly_name": "Smoke", "device_class": "smoke"},
    },
    {"entity_id": "script.goodnight", "state": "off", "attributes": {}},
    {"entity_id": "camera.gate", "state": "idle", "attributes": {}},
    {"entity_id": "switch.gate_detect", "state": "on", "attributes": {}},
]


@dataclass
class World:
    clock: Clock
    docs: MemoryDocs
    store: HomeStore
    notes: Notes
    arm: Arm
    app: FastAPI
    cloud: httpx.AsyncClient
    bridge: Bridge
    client: HomeClient
    link: LinkService
    devices: DeviceService
    webhook: HomeWebhook
    watchdog: Watchdog
    offline: OfflineJob
    ha_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    ha_states: list[dict[str, Any]] = field(default_factory=lambda: [dict(s) for s in HA_STATES])
    bridge_state: StateBits | None = None
    tmp: Path | None = None

    async def link_up(self, code: str | None = None) -> str:
        """Run the real linking flow (code -> bridge -> /home/link -> test call -> seed)."""
        made = code or (await self.link.code(UID)).code
        home_id = await self.bridge.link.link(made, URL, bytes(range(40, 72)))
        return home_id

    async def aclose(self) -> None:
        await self.bridge.link.aclose()
        await self.bridge.ha.aclose()
        await self.cloud.aclose()


def build(tmp: Path, *, ha_token: str = HA_TOKEN, per_minute: int = 60) -> World:
    clock = Clock()
    docs = MemoryDocs()
    ring = Keyring(ROOT)
    store = HomeStore(docs, ring, clock=clock)
    notes = Notes()
    arm = Arm()
    app = FastAPI()
    install_home(app)
    cloud = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cloud.test")
    cfg = BridgeConfig(jarvis_url="https://cloud.test", data_dir=tmp / "data", ha_token=ha_token)
    holder: dict[str, Any] = {}

    def ha_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {HA_TOKEN}"
        w: World = holder["w"]
        if request.method == "GET" and request.url.path == "/api/states":
            return httpx.Response(200, json=w.ha_states)
        if request.method == "GET" and request.url.path == "/api/":
            return httpx.Response(200, json={"message": "API running."})
        if request.method == "POST" and request.url.path.startswith("/api/services/"):
            w.ha_calls.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    bridge = create_bridge(
        cfg,
        (),
        clock=clock,
        http=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://cloud.test"
        ),
        ha_http=httpx.AsyncClient(transport=httpx.MockTransport(ha_handler)),
    )
    client = HomeClient(
        store, clock=clock, resolver=public_resolver, inner=httpx.ASGITransport(app=bridge.app)
    )
    link = LinkService(store, client, clock=clock, resolver=public_resolver)
    devices = DeviceService(store, client, clock=clock)
    bits = StateBits(BridgeState())
    webhook = HomeWebhook(
        store,
        [HeartbeatHandler(store, notes), HazardHandler(store, notes)],
        [bits, devices],
        clock=clock,
        per_minute=per_minute,
    )
    offline = OfflineJob(store, notes, arm, clock=clock, offline_after_s=720)
    dog = Watchdog(store, offline)
    app.state.home_store = store
    app.state.home_link = link
    app.state.home_webhook = webhook
    app.state.home_watchdog = dog
    app.state.home_devices = devices
    w = World(
        clock,
        docs,
        store,
        notes,
        arm,
        app,
        cloud,
        bridge,
        client,
        link,
        devices,
        webhook,
        dog,
        offline,
    )
    w.bridge_state = bits
    w.tmp = tmp
    holder["w"] = w
    return w
