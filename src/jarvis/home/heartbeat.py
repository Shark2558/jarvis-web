# src/jarvis/home/heartbeat.py
"""The cloud's handlers for the events A owns: `heartbeat` and `hazard` (R3 D6, D9). Cloud only.

- heartbeat: remembers that the laptop is alive (in process, written when the state changed or 5
  minutes passed), keeps the parts it reported, and, when an outage alert had gone out, says the
  laptop is back (`home_online`, info). The reply with the cloud's state is built by the webhook.
- hazard: an exposed hazard sensor turned on -> one urgent `home_hazard` alert from a fixed
  template. A sensor the owner did not expose, or whose device class differs from what he exposed,
  is ignored: the bridge can't make the cloud ring about something he never chose.
"""

from __future__ import annotations

from typing import Any

from jarvis.home.classes import HAZARD_CLASSES
from jarvis.home.ports import Ack, Detection, FaceSeen, Hazard, Heartbeat, Package
from jarvis.home.store import HomeStore
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.tools.card import one_line

log = get_logger(__name__)

LAPTOP_BACK = "Your home laptop is back online."
_WORDS = {
    "smoke": "Smoke",
    "carbon_monoxide": "Carbon monoxide",
    "gas": "Gas",
    "moisture": "A water leak",
    "safety": "A safety sensor",
}
Event = Heartbeat | Detection | FaceSeen | Package | Hazard | Ack


def parts_for_store(event: Heartbeat) -> dict[str, Any]:
    """The clear part of a heartbeat the cloud keeps: no picture counts, no person ids."""
    p = event.parts
    out: dict[str, Any] = {}
    if p.ha is not None:
        out["ha"] = p.ha
    if p.frigate is not None:
        out["frigate"] = p.frigate
    if p.doorstep_model is not None:
        out["doorstep_model"] = p.doorstep_model
    if p.mqtt is not None:
        out["mqtt"] = p.mqtt
    if p.cameras is not None:
        out["cameras"] = [{"id": c.id, "online": c.online} for c in p.cameras]
    return out


class HeartbeatHandler:
    handles = frozenset({"heartbeat"})

    def __init__(self, store: HomeStore, notifier: Notifier | None) -> None:
        self._store = store
        self._notifier = notifier

    async def handle(self, uid: str, event: Event) -> None:
        if not isinstance(event, Heartbeat):
            return
        parts = parts_for_store(event)
        seen = await self._store.seen(
            uid,
            parts=parts,
            bridge_version=event.bridge_version,
            # Frigate silent, or the bridge not receiving its events: the camera can't alert
            degraded=parts.get("frigate") is False or parts.get("mqtt") is False,
        )
        if seen is not None and seen.previous == "offline" and seen.outage_alerted:
            if self._notifier is not None:
                await self._notifier.notify(
                    uid, Signal(source="home", kind="home_online"), LAPTOP_BACK
                )


class HazardHandler:
    handles = frozenset({"hazard"})

    def __init__(self, store: HomeStore, notifier: Notifier | None) -> None:
        self._store = store
        self._notifier = notifier

    async def handle(self, uid: str, event: Event) -> None:
        if not isinstance(event, Hazard) or event.state != "on" or self._notifier is None:
            return
        if event.device_class not in HAZARD_CLASSES:
            return
        devices = await self._store.load_devices(uid)
        match = next((e for e in devices.entries if e.entity_id == event.entity), None)
        if match is None or match.device_class != event.device_class:
            log.info("home hazard from an unexposed sensor ignored")
            return
        where = f" at {one_line(match.label, 40)}" if match.label else ""
        text = f"{_WORDS[event.device_class]} was detected{where}. Check your home now."
        await self._notifier.notify(uid, Signal(source="home", kind="home_hazard"), text)


__all__ = ["HazardHandler", "HeartbeatHandler", "parts_for_store"]
