# src/jarvis/homebridge/devices.py
"""Devices at home: the second allow-list (R3 D6, D17). Ships in the home kit.

The cloud already checked; the bridge checks again against what Home Assistant itself reports, so
a wrong or forged cloud record can't loosen anything:

- an action only on an entity in the exposed list the cloud sent;
- the exposed class must be one the entity's table allows (`classes.tier_ok`) using the device
  class Home Assistant reports now: a lock exposed as "everyday" is refused;
- never `script`, `automation`, `shell_command`, `rest_command`, `homeassistant`, `hassio`,
  `notify`, `camera` or Frigate's own detect / record / snapshot switches (arm and disarm are the
  only doors);
- a fixed action table, a bounded value, the Home Assistant call built only by
  `classes.service_call`; no free-form service data exists.

Hazard sensors the owner exposed (`binary_sensor` with a hazard device class) are polled every 10
seconds and each turn-on is sent up as a `hazard` event.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable
from typing import Any

from jarvis.home import classes
from jarvis.home.ports import ExposedDevice, Hazard, HomeRefused
from jarvis.homebridge.ha import HAClient, HAError
from jarvis.homebridge.plugins import EventSink

POLL_S = 10.0
MAX_CATALOGUE = 500
NAME_MAX = 80
NO_HA = "Home Assistant isn't linked yet; the camera still works."


def _text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _class_of(row: dict[str, Any]) -> str | None:
    attrs = row.get("attributes")
    cls = attrs.get("device_class") if isinstance(attrs, dict) else None
    return cls if isinstance(cls, str) and cls.isascii() and len(cls) <= 32 else None


def _entity(row: dict[str, Any]) -> str | None:
    eid = row.get("entity_id")
    return eid if isinstance(eid, str) and "." in eid and len(eid) <= 100 else None


class DeviceBridge:
    def __init__(
        self,
        ha: HAClient,
        exposed: Callable[[], tuple[ExposedDevice, ...]],
        *,
        events: EventSink | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ha = ha
        self._exposed = exposed
        self._events = events
        self._clock = clock
        self._hazard_on: set[str] = set()

    async def _rows(self) -> list[dict[str, Any]]:
        if not self._ha.linked:
            raise HomeRefused("ha_off", NO_HA)
        try:
            return await self._ha.states()
        except HAError as exc:
            raise HomeRefused("ha_" + exc.code, "Home Assistant didn't answer.") from None

    async def catalogue(self) -> dict[str, Any]:
        """Every entity the owner could expose (never-exposed ones are not listed)."""
        out = []
        for row in await self._rows():
            eid = _entity(row)
            if eid is None or not classes.allowed_tiers(eid, _class_of(row)):
                continue
            raw_attrs = row.get("attributes")
            attrs: dict[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}
            out.append(
                {
                    "entity_id": eid,
                    "name": _text(attrs.get("friendly_name"), NAME_MAX),
                    "device_class": _class_of(row),
                    "state": _text(row.get("state"), 32),
                }
            )
            if len(out) >= MAX_CATALOGUE:
                break
        return {"ha": True, "devices": out}

    async def exposed_states(self) -> dict[str, Any]:
        """The exposed entities only, with their state."""
        mine = {d.entity_id for d in self._exposed()}
        out = []
        for row in await self._rows():
            eid = _entity(row)
            if eid in mine:
                out.append({"entity_id": eid, "state": _text(row.get("state"), 32)})
        return {"ha": True, "devices": out}

    async def act(self, entity_id: object, action: object, value: object) -> dict[str, Any]:
        """One action on one exposed entity, or HomeRefused with a short code."""
        entry = next((d for d in self._exposed() if d.entity_id == entity_id), None)
        if entry is None or not isinstance(entity_id, str):
            raise HomeRefused("not_exposed", "That device isn't shared with JARVIS.")
        row = next((r for r in await self._rows() if _entity(r) == entity_id), None)
        if row is None:
            raise HomeRefused("unknown", "Home Assistant doesn't have that device.")
        if not classes.tier_ok(entity_id, _class_of(row), entry.tier) or entry.tier == "read":
            raise HomeRefused("class_not_allowed", "That device can't be controlled that way.")
        try:
            bounded = classes.check_action(entity_id, action, value)
        except ValueError:
            raise HomeRefused("bad_action", "That device can't do that.") from None
        domain, service, data = classes.service_call(entity_id, str(action), bounded)
        try:
            await self._ha.call_service(domain, service, data)
        except HAError as exc:
            raise HomeRefused("ha_" + exc.code, "Home Assistant didn't do that.") from None
        return {"done": True}

    # ---- hazard sensors ------------------------------------------------------------------------

    def _hazards(self) -> set[str]:
        return {
            d.entity_id
            for d in self._exposed()
            if d.entity_id.startswith("binary_sensor.") and d.tier == "read"
        }

    async def poll_hazards(self) -> int:
        """Send a `hazard` event for each exposed hazard sensor that just turned on."""
        watched = self._hazards()
        if not watched or self._events is None:
            return 0
        sent = 0
        now = self._clock()
        for row in await self._rows():
            eid = _entity(row)
            cls = _class_of(row)
            if eid not in watched or cls not in classes.HAZARD_CLASSES:
                continue
            if row.get("state") == "on" and eid not in self._hazard_on:
                self._hazard_on.add(eid)
                event = Hazard(
                    id=f"hz-{hashlib.sha256(eid.encode()).hexdigest()[:10]}-{int(now)}",
                    type="hazard",
                    entity=eid,
                    device_class=cls,  # type: ignore[arg-type]
                    state="on",
                    at=float(now),
                )
                await self._events.post_event(event)
                sent += 1
            elif row.get("state") != "on":
                self._hazard_on.discard(eid)
        return sent

    async def watch(self) -> None:
        """The hazard task: poll forever; Home Assistant being down is not an error."""
        while True:
            try:
                await self.poll_hazards()
            except HomeRefused:
                pass
            await asyncio.sleep(POLL_S)


__all__ = ["DeviceBridge"]
