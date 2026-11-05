# tests/camera_fakes.py -- fakes for R3 B (camera, alarm, history, packages): a bridge caller, a
# notifier that records, a face directory, a clock, and a rig of the real services over MemoryDocs.
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from jarvis.camera.alarm import Alarm, DisarmGate
from jarvis.camera.config import CameraConfigService
from jarvis.camera.events import CameraEvents
from jarvis.camera.feed import Feed
from jarvis.camera.history import History
from jarvis.camera.models import CameraConfig
from jarvis.faces.ports import Resolved
from jarvis.home.ports import HOME_OFFLINE, BridgeMethod, HomeOffline
from jarvis.keyring import Keyring
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import MemoryDocs

UID = "u_owner"
OTHER = "u_other"
HOME = "h_0a1b2c3d"
ROOT = bytes(range(1, 33))
T0 = 1_793_000_000.0  # a fixed epoch; tests move the clock from here
PERSON = "fp_0123456789ab"
CHILD = "fp_ba9876543210"


class Clock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeCaller:
    """Stands in for the cloud's HomeClient: records calls, answers from `replies`."""

    def __init__(self) -> None:
        self.online = True
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, str] | None]] = []
        self.replies: dict[tuple[str, str], dict[str, Any]] = {}

    async def call(
        self,
        uid: str,
        method: BridgeMethod,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        query: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, dict(body) if body else None, dict(query or {})))
        if not self.online:
            raise HomeOffline(HOME_OFFLINE)
        return self.replies.get((method, path), {})


@dataclass
class Sent:
    signal: Signal
    message: str
    named: str | None
    photo: bytes | None


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[Sent] = []
        self.fail_times = 0
        self.action = "ring"
        self.reaches = True  # False: the policy said ring, but no channel took it

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("telegram down")
        self.sent.append(Sent(signal, message, named_message, photo))
        return Delivery(
            action=self.action,  # type: ignore[arg-type]
            reason="test",
            telegram=self.action != "drop" and self.reaches,
            push=1 if self.reaches else 0,
            photo_sent=photo is not None,
        )


class FakeFaces:
    def __init__(self) -> None:
        self.people: dict[str, Resolved] = {}

    async def resolve(self, uid: str, person: str | None, score: float | None) -> Resolved:
        if person is None or score is None or score < 0.9:
            return Resolved()
        return self.people.get(person, Resolved())


class FakeHomes:
    def __init__(self, home: str | None = HOME) -> None:
        self.home = home

    async def home_id(self, uid: str) -> str | None:
        return self.home


class Snap:
    def __init__(self, on: bool = False) -> None:
        self.on = on

    async def snapshot_on(self, uid: str) -> bool:
        return self.on


@dataclass
class Rig:
    docs: MemoryDocs
    clock: Clock
    caller: FakeCaller
    notifier: RecordingNotifier
    faces: FakeFaces
    snap: Snap
    config: CameraConfigService
    alarm: Alarm
    feed: Feed
    events: CameraEvents
    history: History
    gate: DisarmGate
    homes: FakeHomes = field(default_factory=FakeHomes)


async def rig(*, camera: bool = True, tz: str = "Asia/Kolkata") -> Rig:
    docs = MemoryDocs()
    clock = Clock()
    caller = FakeCaller()
    notifier = RecordingNotifier()
    faces = FakeFaces()
    snap = Snap()
    ring = Keyring(ROOT)
    config = CameraConfigService(docs, ring, caller=caller, snapshots=snap, clock=clock)
    alarm = Alarm(docs, caller=caller, clock=clock, has_zones=config.has_alarm_zones)
    feed = Feed(docs, ring, faces=faces, config=config, tz=tz, clock=clock)
    events = CameraEvents(
        alarm=alarm,
        config=config,
        feed=feed,
        notifier=notifier,
        faces=faces,
        snapshots=snap,
        tz=tz,
        clock=clock,
    )
    history = History(caller=caller, config=config, faces=faces, tz=tz, clock=clock)
    homes = FakeHomes()
    gate = DisarmGate(alarm, homes)
    if camera:
        cam = CameraConfig(label="Gate", alarm_zones=("gate",), package_zone="doorstep")
        await config.set_cameras(UID, {"gate": cam})
        caller.calls.clear()
    return Rig(
        docs,
        clock,
        caller,
        notifier,
        faces,
        snap,
        config,
        alarm,
        feed,
        events,
        history,
        gate,
        homes,
    )
