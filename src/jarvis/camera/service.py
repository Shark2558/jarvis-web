# src/jarvis/camera/service.py
"""Everything workstream B builds, wired from the ports it needs (R3). I1 calls `build_camera` once
in `api/home_wiring.py`, sets `app.state.camera`, registers `services.events` with the webhook
dispatcher, `services.state` as a `StateSource`, `services.jobs` with A's watchdog and
`services.privacy` with the privacy registry.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.camera.alarm import Alarm, ArmPendingJob, DisarmGate, PermissionChecker
from jarvis.camera.config import CameraConfigService
from jarvis.camera.events import CameraEvents
from jarvis.camera.feed import Feed, FeedSweepJob
from jarvis.camera.history import History
from jarvis.camera.packages import Packages
from jarvis.camera.ports import HomeDirectory, SnapshotPolicy
from jarvis.camera.privacy import CameraData, CameraHomePrivacy, HomeFeedPrivacy
from jarvis.camera.state import CameraStateSource
from jarvis.faces.ports import FaceDirectory
from jarvis.home.ports import HomeCaller
from jarvis.keyring import Keyring
from jarvis.notify.ports import Notifier
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob


@dataclass(frozen=True)
class CameraServices:
    alarm: Alarm
    gate: DisarmGate
    config: CameraConfigService
    feed: Feed
    history: History
    packages: Packages
    events: CameraEvents
    state: CameraStateSource
    data: CameraData
    jobs: tuple[TickJob, ...]
    privacy: tuple[HomeFeedPrivacy, CameraHomePrivacy]


def build_camera(
    *,
    docs: Docs,
    keyring: Keyring,
    caller: HomeCaller,
    faces: FaceDirectory,
    notifier: Notifier,
    homes: HomeDirectory,
    permissions: PermissionChecker | None = None,
    snapshots: SnapshotPolicy | None = None,
    tz: str,
    clock: Callable[[], float] = time.time,
    prefix: str = "jarvis_",
) -> CameraServices:
    config = CameraConfigService(
        docs, keyring, caller=caller, snapshots=snapshots, clock=clock, prefix=prefix
    )
    alarm = Alarm(docs, caller=caller, clock=clock, prefix=prefix)
    feed = Feed(docs, keyring, faces=faces, config=config, tz=tz, clock=clock, prefix=prefix)
    packages = Packages(config)
    events = CameraEvents(
        alarm=alarm,
        config=config,
        feed=feed,
        notifier=notifier,
        faces=faces,
        snapshots=snapshots,
        packages=packages,
        tz=tz,
        clock=clock,
    )
    return CameraServices(
        alarm=alarm,
        gate=DisarmGate(alarm, homes, permissions),
        config=config,
        feed=feed,
        history=History(caller=caller, config=config, faces=faces, tz=tz, clock=clock),
        packages=packages,
        events=events,
        state=CameraStateSource(alarm, config),
        data=CameraData(alarm, config),
        jobs=(ArmPendingJob(alarm, notifier, tz=tz), FeedSweepJob(feed)),
        privacy=(HomeFeedPrivacy(feed), CameraHomePrivacy()),
    )


__all__ = ["CameraServices", "build_camera"]
