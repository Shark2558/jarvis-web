# tests/frigate_fakes.py -- R3 B bridge fakes: Frigate's HTTP API (httpx MockTransport), an MQTT
# client, an event sink that records what the bridge would sign and post, and a ready plugin.
from __future__ import annotations

import json
import struct
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx

from jarvis.home.ports import (
    ArmState,
    BridgeState,
    CameraSetting,
    FacesState,
    SettingsState,
)
from jarvis.homebridge.camera import CameraPlugin
from jarvis.homebridge.frigate import FrigateClient
from jarvis.homebridge.plugins import BridgeContext

PERSON = "fp_0123456789ab"
NOW = 1_793_000_000.0


def jpeg(width: int = 320, height: int = 240, *, exif: bytes = b"") -> bytes:
    """A tiny fake JPEG with real segment structure: SOI, APP1 (EXIF), COM, DQT, SOF0, SOS, EOI."""
    app1 = b"\xff\xe1" + struct.pack(">H", 2 + len(exif)) + exif if exif else b""
    com = b"\xff\xfe" + struct.pack(">H", 2 + 7) + b"secret!"
    dqt = b"\xff\xdb" + struct.pack(">H", 2 + 65) + b"\x00" + bytes(64)
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 8 + 3, 8, height, width, 1) + b"\x01\x11\x00"
    sos = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00" + b"\x12\x34\x56"
    return b"\xff\xd8" + app1 + com + dqt + sof + sos + b"\xff\xd9"


class Sink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def post_event(self, event: Any) -> bool:
        self.events.append(event)
        return True


class FrigateFake:
    """Frigate's internal API. `calls` records (path, params); thumbnails are never needed."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.snapshot: bytes | None = None
        self.up = True
        self.stats: dict[str, Any] = {
            "cameras": {"gate": {"camera_fps": 5.0}, "yard": {"camera_fps": 0}}
        }
        self.config: dict[str, Any] = {"classification": {"custom": {"doorstep": {}}}}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((path, dict(request.url.params)))
        if not self.up:
            raise httpx.ConnectError("down")
        if path == "/api/events":
            return httpx.Response(200, json=self.events)
        if path == "/api/stats":
            return httpx.Response(200, json=self.stats)
        if path == "/api/config":
            return httpx.Response(200, json=self.config)
        if path.endswith("/snapshot.jpg"):
            if self.snapshot is None:
                return httpx.Response(404)
            return httpx.Response(200, content=self.snapshot)
        return httpx.Response(404)

    def client(self) -> FrigateClient:
        return FrigateClient(
            "http://frigate:5000", httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        )


class FakeMqttClient:
    def __init__(self, script: list[tuple[str, bytes] | Exception], log: list[str]) -> None:
        self.script = script
        self.log = log

    async def subscribe(self, topic: str) -> None:
        self.log.append(topic)

    @property
    def messages(self) -> Any:
        async def gen() -> Any:
            for item in self.script:
                if isinstance(item, Exception):
                    raise item
                topic, payload = item

                class M:
                    pass

                m = M()
                m.topic = topic  # type: ignore[attr-defined]
                m.payload = payload  # type: ignore[attr-defined]
                yield m

        return gen()


def fake_connect(
    sessions: list[list[tuple[str, bytes] | Exception] | Exception], log: list[str]
) -> Callable[[], Any]:
    state = {"n": 0}

    @asynccontextmanager
    async def connect() -> Any:
        i = state["n"]
        state["n"] += 1
        item = sessions[min(i, len(sessions) - 1)]
        if isinstance(item, Exception):
            raise item
        yield FakeMqttClient(item, log)

    return connect


def ctx(tmp: Path, sink: Sink, *, now: float = NOW) -> BridgeContext:
    return BridgeContext(
        env={"FRIGATE_URL": "http://frigate:5000"}, data_dir=tmp, events=sink, now=lambda: now
    )


def state(
    *,
    armed: bool = True,
    rev: int = 1,
    zones: tuple[str, ...] = ("gate",),
    package_zone: str | None = "doorstep",
    snapshot: bool = False,
    greetings: bool = True,
    packages: bool = True,
    faces: tuple[str, ...] = (),
    srev: int = 1,
) -> BridgeState:
    return BridgeState(
        arm=ArmState(armed=armed, mode="away", rev=rev),
        settings=SettingsState(
            rev=srev,
            cameras={"gate": CameraSetting(alarm_zones=zones, package_zone=package_zone)},
            snapshot=snapshot,
            greetings=greetings,
            packages=packages,
        ),
        faces=FacesState(rev=srev, people=faces),
    )


def plugin(tmp: Path, sink: Sink, fr: FrigateFake | None = None, **kw: Any) -> CameraPlugin:
    return CameraPlugin(ctx(tmp, sink, **kw), frigate=(fr or FrigateFake()).client())


def event_payload(
    *,
    event_id: str = "1793000000.1-abc",
    camera: str = "gate",
    label: str = "person",
    zones: list[str] | None = None,
    kind: str = "new",
    sub_label: Any = None,
    score: float = 0.82,
    **extra: Any,
) -> bytes:
    after = {
        "id": event_id,
        "camera": camera,
        "label": label,
        "sub_label": sub_label,
        "top_score": score,
        "start_time": NOW,
        "end_time": None,
        "entered_zones": ["gate"] if zones is None else zones,
        "current_zones": [],
        "false_positive": False,
        "box": [1, 2, 3, 4],
        **extra,
    }
    return json.dumps({"type": kind, "before": after, "after": after}).encode()
