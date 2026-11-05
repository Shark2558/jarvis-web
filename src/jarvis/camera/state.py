# src/jarvis/camera/state.py
"""B's part of the bridge state (R3 D8): the arm state and the camera settings.

A merges the parts of every workstream into the heartbeat reply and the state push
(`jarvis.home.ports.StateSource`); the bridge catches up from it when the laptop wakes.
"""

from __future__ import annotations

from jarvis.camera.alarm import Alarm
from jarvis.camera.config import CameraConfigService
from jarvis.home.ports import ArmState, BridgeState


class CameraStateSource:
    def __init__(self, alarm: Alarm, config: CameraConfigService) -> None:
        self._alarm = alarm
        self._config = config

    async def state_part(self, uid: str) -> BridgeState:
        rec = await self._alarm.record(uid)
        return BridgeState(
            arm=ArmState(armed=rec.armed, mode=rec.mode, rev=rec.rev),
            settings=await self._config.settings_state(uid),
        )


__all__ = ["CameraStateSource"]
