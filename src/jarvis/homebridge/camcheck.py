# src/jarvis/homebridge/camcheck.py
"""R8 row 377 (docs/plans/r8-vision.md 4.6; builder B from I0 on): the no-cloud camera check.

`POST /bridge/v1/camera-check` takes a private-range IP only (RFC 1918; anything else refused),
then checks RTSP `DESCRIBE` on the main and sub streams, ONVIF `GetDeviceInformation` and
`GetProfiles`, and the codec (H.264); standard library and httpx only. The camera's user name and
password are typed on the bridge's local page and never leave the laptop; the cloud sees only
pass or fail and the missing piece, in plain words. "No cloud" means it still passes after he
blocks the camera's internet at the router and restarts it. The owner's camera is an Imou Ranger
S2 (RTSP and ONVIF per its listing); nothing here names a model.

I0: a stub that answers "not built yet".
"""

from __future__ import annotations

from jarvis.home.ports import CAMERA_CHECK_ROUTE
from jarvis.homebridge.plugins import BridgeContext, BridgePlugin
from jarvis.homebridge.r8_stub import StubPlugin

NAME = "camcheck"


def create_plugin(ctx: BridgeContext) -> BridgePlugin:
    return StubPlugin(NAME, ctx, (CAMERA_CHECK_ROUTE,))


__all__ = ["NAME", "create_plugin"]
