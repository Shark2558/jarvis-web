# src/jarvis/homebridge/registry.py
"""The bridge's plugins, in start order (R3 I0: empty; I1 lists A's core, B's camera and C's
faces factories). The bridge builds each with its `BridgeContext` and checks the routes once."""

from __future__ import annotations

from jarvis.homebridge.plugins import PluginFactory

PLUGINS: tuple[PluginFactory, ...] = ()

__all__ = ["PLUGINS"]
