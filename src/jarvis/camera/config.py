# src/jarvis/camera/config.py
"""The owner's camera settings and what the bridge last reported (R3 D7, D15, D16).

    {prefix}home_cameras/{uid}   {blob, updated_at}
        blob = AES-GCM(JSON CameraSettings) under the `home` key, AAD `home/cameras/{uid}/v1`

Labels are the owner's own words. The bridge's view (`SettingsState`: alarm zones per camera,
package zone, retention, greetings, packages, snapshot) is built from here and pushed to the bridge
whenever it changes. Heartbeats only write when something changed (the budget is ~600 writes a day).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from jarvis.camera.models import (
    CameraConfig,
    CameraSettings,
    CameraStatus,
    clean_label,
)
from jarvis.camera.ports import CameraUnavailable, NoSnapshots, SnapshotPolicy
from jarvis.camera.sealed import SealedDoc
from jarvis.home.ports import (
    BridgeMethod,
    CameraSetting,
    HeartbeatParts,
    HomeCaller,
    HomeUnavailable,
    SettingsState,
)
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs

log = get_logger(__name__)

EVENT_TOUCH_EVERY_S = 60.0  # last-event times are written at most this often per camera
PUSH_METHOD: BridgeMethod = "POST"
STATE_PATH = "/bridge/v1/state"


class CameraConfigService:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring,
        *,
        caller: HomeCaller | None = None,
        snapshots: SnapshotPolicy | None = None,
        clock: Callable[[], float] = time.time,
        prefix: str = "jarvis_",
    ) -> None:
        self._doc: SealedDoc[CameraSettings] = SealedDoc(
            docs,
            keyring,
            collection=f"{prefix}home_cameras",
            purpose="home",
            name="home/cameras",
            model=CameraSettings,
        )
        self._caller = caller
        self._snapshots: SnapshotPolicy = snapshots or NoSnapshots()
        self._clock = clock

    async def get(self, uid: str) -> CameraSettings:
        return await self._doc.load(uid)

    async def has_alarm_zones(self, uid: str) -> bool:
        """Does any camera have an alarm zone? (Unreadable settings: say yes, never a false alarm
        about the setup.)"""
        try:
            return any(c.alarm_zones for c in (await self.get(uid)).cameras.values())
        except Exception as exc:  # noqa: BLE001
            log.warning("camera settings unreadable", extra={"reason": type(exc).__name__})
            return True

    async def set_cameras(
        self,
        uid: str,
        cameras: Mapping[str, CameraConfig],
        *,
        retention_days: int | None = None,
        greetings: bool | None = None,
    ) -> CameraSettings:
        clean = {
            cid: CameraConfig(
                label=clean_label(c.label, cid.replace("_", " ")),
                alarm_zones=tuple(dict.fromkeys(c.alarm_zones)),
                package_zone=c.package_zone,
            )
            for cid, c in cameras.items()
        }

        def change(cur: CameraSettings) -> CameraSettings:
            return cur.model_copy(
                update={
                    "cameras": clean,
                    "retention_days": cur.retention_days
                    if retention_days is None
                    else retention_days,
                    "greetings": cur.greetings if greetings is None else greetings,
                    "rev": cur.rev + 1,
                }
            )

        saved = await self._doc.update(uid, change)
        await self.push(uid)
        return saved

    async def _status(self, uid: str, fn: Callable[[CameraStatus], CameraStatus]) -> CameraSettings:
        def change(cur: CameraSettings) -> CameraSettings | None:
            new = fn(cur.status)
            return None if new == cur.status else cur.model_copy(update={"status": new})

        return await self._doc.update(uid, change)

    async def update_status(
        self, uid: str, fn: Callable[[CameraStatus], CameraStatus]
    ) -> CameraSettings:
        return await self._status(uid, fn)

    async def record_heartbeat(self, uid: str, parts: HeartbeatParts) -> None:
        """Store what a heartbeat reported about the cameras and the doorstep model (if changed)."""
        if parts.cameras is None and parts.doorstep_model is None:
            return

        def change(st: CameraStatus) -> CameraStatus:
            online = st.online if parts.cameras is None else {c.id: c.online for c in parts.cameras}
            model = st.doorstep_model if parts.doorstep_model is None else parts.doorstep_model
            return st.model_copy(update={"online": online, "doorstep_model": model})

        await self._status(uid, change)

    async def touch_event(self, uid: str, camera: str, at: float) -> None:
        def change(st: CameraStatus) -> CameraStatus:
            seen = st.last_event.get(camera)
            if seen is not None and at - seen < EVENT_TOUCH_EVERY_S:
                return st
            return st.model_copy(update={"last_event": {**st.last_event, camera: at}})

        await self._status(uid, change)

    # ---- the bridge's view -------------------------------------------------------------------

    async def settings_state(self, uid: str) -> SettingsState:
        s = await self.get(uid)
        return SettingsState(
            rev=s.rev,
            cameras={
                cid: CameraSetting(alarm_zones=c.alarm_zones, package_zone=c.package_zone)
                for cid, c in s.cameras.items()
            },
            retention_days=s.retention_days,
            greetings=s.greetings,
            packages=s.packages_on,
            snapshot=await self._snapshots.snapshot_on(uid),
        )

    async def push(self, uid: str) -> bool:
        """Tell the bridge the new settings. False when the laptop didn't answer (it catches up
        from the next heartbeat reply)."""
        if self._caller is None:
            return False
        try:
            state = await self.settings_state(uid)
            await self._caller.call(
                uid, PUSH_METHOD, STATE_PATH, {"settings": state.model_dump(mode="json")}
            )
        except HomeUnavailable:
            return False
        except CameraUnavailable:
            return False
        except Exception as exc:  # noqa: BLE001 - a push never fails the change that caused it
            log.warning("camera settings push failed", extra={"reason": type(exc).__name__})
            return False
        return True

    async def wipe(self, uid: str) -> None:
        await self._doc.delete(uid)


__all__ = ["EVENT_TOUCH_EVERY_S", "CameraConfigService"]
