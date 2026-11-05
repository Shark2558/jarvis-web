# src/jarvis/homebridge/heartbeat.py
"""The bridge's heartbeat (R3 D8, D9). Ships in the home kit.

Every `SettingsState.heartbeat_s` (default 120) the bridge posts a `heartbeat` with each plugin's
part (Home Assistant, Frigate, cameras, faces). The cloud's signed answer carries its state, so a
laptop that just woke catches up; each part is applied only if newer. After an arm change the
camera plugin sends the `arm:` ack (the cloud says "Armed" only after it), and every answer goes to
the plugins' optional `on_reply`, so a lost ack is sent again (review M7). The heartbeat also keeps
the cloud instance warm (D9). `state_rev` is the arm part's applied rev, the one the cloud acks.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Callable, Sequence

from jarvis.home.ports import BridgeState, Heartbeat, HeartbeatParts
from jarvis.homebridge.cloud import CloudLink
from jarvis.homebridge.config import BRIDGE_VERSION
from jarvis.homebridge.plugins import BridgePlugin
from jarvis.homebridge.state import BridgeStore

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 120


def _event_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


class HeartbeatLoop:
    def __init__(
        self,
        store: BridgeStore,
        link: CloudLink,
        plugins: Sequence[BridgePlugin],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._link = link
        self._plugins = plugins
        self._clock = clock

    async def parts(self) -> HeartbeatParts:
        merged = HeartbeatParts()
        for plugin in self._plugins:
            try:
                merged = merged.merged(await plugin.heartbeat_part())
            except Exception as exc:  # noqa: BLE001 - a broken plugin never stops the heartbeat
                log.error(
                    "a bridge part failed",
                    extra={"plugin": plugin.name, "error": type(exc).__name__},
                )
        return merged

    async def apply(self, state: BridgeState) -> None:
        """Keep the newer parts and tell every plugin what changed. The arm ack is the camera
        plugin's (`arm:<rev>:...`, the only one the cloud counts; review M7 dropped the core's)."""
        changed = self._store.apply(state)
        if all(v is None for v in changed.model_dump().values()):
            return
        for plugin in self._plugins:
            try:
                await plugin.apply_state(changed)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "a bridge part failed",
                    extra={"plugin": plugin.name, "error": type(exc).__name__},
                )

    async def replied(self, state: BridgeState) -> None:
        """The cloud's whole answer, to each plugin that wants it (`on_reply`, optional)."""
        for plugin in self._plugins:
            hook = getattr(plugin, "on_reply", None)
            if hook is None:
                continue
            try:
                await hook(state)
            except Exception as exc:  # noqa: BLE001 - one plugin never stops the heartbeat
                log.error(
                    "a bridge part failed",
                    extra={"plugin": plugin.name, "error": type(exc).__name__},
                )

    async def beat(self) -> bool:
        """One heartbeat. True if the cloud answered."""
        arm = self._store.state.arm
        event = Heartbeat(
            id=_event_id("hb"),
            type="heartbeat",
            at=float(self._clock()),
            bridge_version=BRIDGE_VERSION,
            state_rev=arm.rev if arm is not None else 0,
            parts=await self.parts(),
        )
        state = await self._link.heartbeat(event)
        if state is None:
            return False
        await self.apply(state)
        await self.replied(state)
        return True

    def interval(self) -> float:
        s = self._store.state.settings
        return float(s.heartbeat_s if s is not None else DEFAULT_INTERVAL_S)

    async def run(self) -> None:
        while True:
            if self._store.linked() is not None and not self._link.unlinked:
                await self.beat()
            await asyncio.sleep(self.interval())


__all__ = ["HeartbeatLoop"]
