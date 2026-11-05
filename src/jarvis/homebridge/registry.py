# src/jarvis/homebridge/registry.py
"""The bridge's plugins, in start order (R3 I1). The core plugin (health, state, devices) is built
by the bridge itself (`homebridge/app.py`); this lists the others: B's camera (Frigate MQTT ->
detections, packages, history) and C's faces (the face library, its retention sweeps and the local
Faces page). The bridge builds each with its `BridgeContext` and checks the routes once. The camera
finds the faces plugin through `BridgeContext.peers` when a face arrives (consent lives there)."""

from __future__ import annotations

from jarvis.homebridge.camera import camera_plugin
from jarvis.homebridge.faces import create_plugin as faces_plugin
from jarvis.homebridge.plugins import PluginFactory

PLUGINS: tuple[PluginFactory, ...] = (camera_plugin, faces_plugin)

__all__ = ["PLUGINS"]
