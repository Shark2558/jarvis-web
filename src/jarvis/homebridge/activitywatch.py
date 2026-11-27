# src/jarvis/homebridge/activitywatch.py
"""R8 row 183 (docs/plans/r8-vision.md 4.7, ADR-53; builder C from I0 on): screen time.

ActivityWatch (MPL-2.0) is installed by the owner on the laptop, never shipped. This plugin reads
its local REST API (`AW_URL`, default http://host.docker.internal:5600: the window and "away"
buckets) and serves `GET /bridge/v1/screentime?day=yyyy-mm-dd`: per-program minutes and active
time for that day. Window titles never leave the laptop. With no ActivityWatch it answers "off
until ActivityWatch is installed".

I0: a stub that answers "not built yet".
"""

from __future__ import annotations

from jarvis.home.ports import SCREENTIME_ROUTE
from jarvis.homebridge.plugins import BridgeContext, BridgePlugin
from jarvis.homebridge.r8_stub import StubPlugin

NAME = "activitywatch"


def create_plugin(ctx: BridgeContext) -> BridgePlugin:
    return StubPlugin(NAME, ctx, (SCREENTIME_ROUTE,))


__all__ = ["NAME", "create_plugin"]
