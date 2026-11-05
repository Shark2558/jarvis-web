# tests/r3_fakes.py -- R3 I1: the cloud's home, camera and faces services on in-memory documents,
# wired the way api/home_wiring.py wires them, for tests that need the tools or the dispatcher
# without the whole app (the Telegram tool guard, the gateway checks).
from __future__ import annotations

from typing import Any

from jarvis.camera.service import CameraServices, build_camera
from jarvis.faces.directory import Directory
from jarvis.faces.service import FacesService
from jarvis.faces.store import FacesStore
from jarvis.home.client import HomeClient
from jarvis.home.devices import DeviceService
from jarvis.home.parts import HomeParts
from jarvis.home.store import HomeStore
from jarvis.home.tools import HomeStatusReader
from jarvis.keyring import Keyring
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import Docs

R3_READS = ("home_devices", "camera_history", "faces_list")  # the third Telegram group
R3_SAFE = ("home_status", "home_disarm")  # armed or not; the fixed "use the console" answer


class NoHomes:
    async def home_id(self, uid: str) -> str | None:
        return None


class Recorder:
    """A `Notifier` that keeps what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, Signal, str, str | None]] = []

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        self.sent.append((uid, signal, message, named_message))
        return Delivery(action="ring", reason="test", telegram=True)


def home_parts(docs: Docs, ring: Keyring, *, clock: Any = None) -> HomeParts:
    import time

    now = clock or time.time
    store = HomeStore(docs, ring, prefix="r3_", clock=now)
    client = HomeClient(store, clock=now)
    faces_store = FacesStore(docs, ring, prefix="r3_")
    faces = FacesService(faces_store, client)
    camera: CameraServices = build_camera(
        docs=docs,
        keyring=ring,
        caller=client,
        faces=Directory(faces_store),
        notifier=Recorder(),
        homes=NoHomes(),
        tz="Asia/Kolkata",
        clock=now,
        prefix="r3_",
    )
    devices = DeviceService(store, client, clock=now)
    status = HomeStatusReader(store, clock=now, offline_after_s=720, arm=camera.alarm)
    return HomeParts(devices=devices, status=status, camera=camera, faces=faces)


__all__ = ["R3_READS", "R3_SAFE", "NoHomes", "Recorder", "home_parts"]
