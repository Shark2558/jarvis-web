# src/jarvis/homebridge/r8_stub.py
"""R8 I0 (docs/plans/r8-vision.md v8.0.3 seams S14, S24): the shared shape of the three R8 bridge
plugins while they are stubs. A stub serves its fixed routes with a plain refusal ("not built
yet"), runs no task, reports nothing in a heartbeat and ignores the state push. Each builder
replaces its stub's factory body; the registry (`registry.PLUGINS`) keeps its place."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.home.ports import BridgeState, HeartbeatParts, HomeRefused
from jarvis.homebridge.plugins import BridgeContext, BridgeRoute, TaskFactory

NOT_BUILT = "That part of the home kit isn't built yet."


class StubPlugin:
    def __init__(self, name: str, ctx: BridgeContext, routes: Sequence[tuple[str, str]]) -> None:
        self.name = name
        self._ctx = ctx
        self._routes = tuple(BridgeRoute(m, p, self._refuse) for m, p in routes)  # type: ignore[arg-type]

    async def _refuse(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        raise HomeRefused("not_built", NOT_BUILT)

    def routes(self) -> Sequence[BridgeRoute]:
        return self._routes

    def tasks(self) -> Sequence[TaskFactory]:
        return ()

    async def heartbeat_part(self) -> HeartbeatParts:
        return HeartbeatParts()

    async def apply_state(self, state: BridgeState) -> None:
        return None


__all__ = ["NOT_BUILT", "StubPlugin"]
