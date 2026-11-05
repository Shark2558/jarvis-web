# src/jarvis/homebridge/plugins.py
"""The bridge's plugin seam (R3 I0). A core, B camera and C faces each add one plugin.

- `routes()`: the signed API routes the plugin serves. Each must be one of
  `jarvis.home.ports.BRIDGE_ROUTES`; the bridge app (A) checks the signature, size-caps and parses
  JSON BEFORE a handler runs, signs the answer, and turns `HomeRefused(code, words)` into a signed
  refusal. A handler gets the query and the parsed body (None for GET) and returns a JSON object.
- `tasks()`: long-running loops (MQTT, retention sweeps, the local Faces page server); each entry
  is a zero-argument coroutine function, so the bridge can restart one that stopped.
- `heartbeat_part()`: this plugin's part of the next heartbeat (`HeartbeatParts`, others None).
- `apply_state(state)`: a new `BridgeState` from the cloud (parts it doesn't carry are unchanged).

A plugin is built by a factory from a `BridgeContext`: the bridge.env values (each plugin reads
and validates its own keys), its data directory, the event sink that signs and posts events up
(with the outbox and retries, A) and the clock.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from jarvis.home.ports import (
    Ack,
    BridgeMethod,
    BridgeState,
    Detection,
    FaceSeen,
    Hazard,
    Heartbeat,
    HeartbeatParts,
    Package,
    route_allowed,
)

Query = Mapping[str, str]
Handler = Callable[[Query, Mapping[str, Any] | None], Awaitable[dict[str, Any]]]
TaskFactory = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class BridgeRoute:
    method: BridgeMethod
    path: str
    handler: Handler

    def __post_init__(self) -> None:
        if not route_allowed(self.method, self.path):
            raise ValueError("not one of the bridge's fixed routes")


@runtime_checkable
class EventSink(Protocol):
    async def post_event(
        self, event: Heartbeat | Detection | FaceSeen | Package | Hazard | Ack
    ) -> bool: ...


@dataclass(frozen=True)
class BridgeContext:
    """`peers` (I1): the plugins already built, by name, filled by the bridge as it builds them,
    so one plugin can use another's public parts later (B's camera asks C's face library whether
    a face is a consented id). Read it when a message arrives, never in a factory."""

    env: Mapping[str, str]
    data_dir: Path
    events: EventSink
    now: Callable[[], float] = field(default=time.time)
    peers: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class BridgePlugin(Protocol):
    name: str

    def routes(self) -> Sequence[BridgeRoute]: ...

    def tasks(self) -> Sequence[TaskFactory]: ...

    async def heartbeat_part(self) -> HeartbeatParts: ...

    async def apply_state(self, state: BridgeState) -> None: ...


PluginFactory = Callable[[BridgeContext], BridgePlugin]


def check_routes(plugins: Iterable[BridgePlugin]) -> None:
    """Each plugin name once, each fixed route served by at most one plugin (ValueError)."""
    names: set[str] = set()
    served: set[tuple[str, str]] = set()
    for plugin in plugins:
        if plugin.name in names:
            raise ValueError("two bridge plugins share a name")
        names.add(plugin.name)
        for route in plugin.routes():
            key = (route.method, route.path)
            if key in served:
                raise ValueError("a bridge route is served twice")
            served.add(key)


__all__ = [
    "BridgeContext",
    "BridgePlugin",
    "BridgeRoute",
    "EventSink",
    "Handler",
    "PluginFactory",
    "Query",
    "TaskFactory",
    "check_routes",
]
