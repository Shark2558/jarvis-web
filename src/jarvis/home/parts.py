# src/jarvis/home/parts.py
"""What the tool gateway needs from R3's home, camera and faces services (I1). Cloud only: never in
the home kit. `tools.setup.build_gateway(home=...)` registers the tools from these."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.camera.service import CameraServices
from jarvis.faces.service import FacesService
from jarvis.home.devices import DeviceService
from jarvis.home.tools import HomeStatusReader


@dataclass(frozen=True)
class HomeParts:
    devices: DeviceService
    status: HomeStatusReader
    camera: CameraServices
    faces: FacesService | None = None


__all__ = ["HomeParts"]
