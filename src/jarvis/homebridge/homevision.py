# src/jarvis/homebridge/homevision.py
"""R8 row 216's home leg (docs/plans/r8-vision.md v8.0.3 4.5a, the owner's D3 and D4, ADR-49;
builder J from I0 on): vision on the home laptop for the home camera.

It reads the home camera's RTSP sub-stream (`HOMEVISION_RTSP_URL` in bridge.env: the address and
the camera's password stay on the laptop; `HOMEVISION_CAMERA` is its id in the camera setup),
decodes about 1 frame a second (2 while a slouch is suspected, up to 15 during a seated
session), runs MediaPipe's pose landmarker there (`HOMEVISION_MODELS_DIR`: the pinned files,
SHA-256 checked; full if the laptop keeps 15 frames a second, else lite), names enrolled people
through the faces plugin's library (`BridgeContext.peers["faces"]`, consent only, the owner's
D6), and runs the home use cases' rules (`jarvis.coach.home.REGISTRY`) one body at a time. Up go
only `CoachReport` events (views and tallies; never a frame, a point or a box) and its heartbeat
part (`HomeVisionPart`). It obeys the coach part of the state push (`CoachState`: which use cases
on which camera, the target, "cameras off") and never touches Frigate or the alarm.

I0: a stub with no route and no task: it runs nothing.
"""

from __future__ import annotations

from jarvis.homebridge.plugins import BridgeContext, BridgePlugin
from jarvis.homebridge.r8_stub import StubPlugin

NAME = "homevision"


def create_plugin(ctx: BridgeContext) -> BridgePlugin:
    return StubPlugin(NAME, ctx, ())


__all__ = ["NAME", "create_plugin"]
