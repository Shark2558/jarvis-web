# src/jarvis/homebridge/registry.py
"""The bridge's plugins, in start order (R3 I1). The core plugin (health, state, devices) is built
by the bridge itself (`homebridge/app.py`); this lists the others: B's camera (Frigate MQTT ->
detections, packages, history) and C's faces (the face library, its retention sweeps and the local
Faces page). The bridge builds each with its `BridgeContext` and checks the routes once. The camera
finds the faces plugin through `BridgeContext.peers` when a face arrives (consent lives there)."""

from __future__ import annotations

from jarvis.homebridge.activitywatch import create_plugin as activitywatch_plugin
from jarvis.homebridge.camcheck import create_plugin as camcheck_plugin
from jarvis.homebridge.camera import camera_plugin
from jarvis.homebridge.face_groups import create_plugin as face_groups_plugin
from jarvis.homebridge.faces import create_plugin as faces_plugin
from jarvis.homebridge.homevision import create_plugin as homevision_plugin
from jarvis.homebridge.plugins import PluginFactory

# R11.1 O7: face groups from still pictures (photos JARVIS sends, the watched folder). It reads
# consent from the faces plugin through `BridgeContext.peers`, as the camera does.
# R8 I0 (docs/plans/r8-vision.md v8.0.3 seams S14, S24): the home camera's vision (J), screen
# time (C) and the no-cloud camera check (B), stubs until their builders; homevision after faces,
# whose library it reads through `BridgeContext.peers`.
PLUGINS: tuple[PluginFactory, ...] = (
    *(camera_plugin, faces_plugin, face_groups_plugin),
    *(homevision_plugin, activitywatch_plugin, camcheck_plugin),
)

__all__ = ["PLUGINS"]
