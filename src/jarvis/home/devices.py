# src/jarvis/home/devices.py
"""Home Assistant devices through the bridge (R3 D6, D17). Cloud only.

The owner picks at most 50 entities to expose; each gets a class (`jarvis.home.classes`) he may
only change within its table. The cloud checks every request against that list and the fixed
action table, then asks the bridge, which checks again against Home Assistant. Names Home
Assistant reports are other people's words: they are cleaned, kept only for matching and showing
(fenced by the tools), and never vouch. A label the owner typed is his own.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from jarvis.home import classes
from jarvis.home.models import LABEL_MAX, DevicesRecord, ExposedEntry
from jarvis.home.ports import (
    ENTITY_ID,
    MAX_EXPOSED,
    BridgeState,
    DevicesState,
    ExposedDevice,
    HomeCaller,
    HomeOffline,
    HomeRefused,
)
from jarvis.home.store import HomeStore
from jarvis.logging import get_logger
from jarvis.tools.card import one_line
from jarvis.tools.external import model_text

log = get_logger(__name__)

NAME_MAX = 80
CACHE_TTL_S = 120.0
MAX_CATALOGUE = 500
HA_OFF = "Home Assistant isn't linked yet; the camera still works."
BAD_LIST = "That list of devices isn't valid."
_ENTITY = ENTITY_ID
_SHORT = r"^[a-z0-9_ .:+-]{0,32}$"


class DeviceRejected(Exception):
    """`code` is a short word; the message is plain words for the owner."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore")
    entity_id: StrictStr
    name: StrictStr = ""
    device_class: StrictStr | None = None
    state: StrictStr | None = None


def clean_name(text: object, limit: int) -> str:
    return one_line(model_text(text if isinstance(text, str) else ""), limit)


def _device_class(raw: object) -> str | None:
    return raw if isinstance(raw, str) and 0 < len(raw) <= 32 and raw.isascii() else None


def parse_items(reply: Mapping[str, Any]) -> list[_Item]:
    """The bridge's device list, strictly: anything that doesn't fit is dropped."""
    out: list[_Item] = []
    raw = reply.get("devices")
    for row in raw[:MAX_CATALOGUE] if isinstance(raw, list) else []:
        try:
            item = _Item.model_validate(row)
        except ValidationError:
            continue
        if re.fullmatch(_ENTITY, item.entity_id):
            out.append(item)
    return out


def resolve_entry(entries: Sequence[ExposedEntry], text: str) -> ExposedEntry | None:
    """One exposed device by entity id, then the owner's label, then Home Assistant's name."""
    wanted = text.strip().casefold()
    if not wanted:
        return None
    matchers: tuple[Callable[[ExposedEntry], bool], ...] = (
        lambda e: e.entity_id.casefold() == wanted,
        lambda e: e.label is not None and e.label.casefold() == wanted,
        lambda e: e.name is not None and e.name.casefold() == wanted,
    )
    for match in matchers:
        hits = [e for e in entries if match(e)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None
    return None


class DeviceService:
    def __init__(
        self,
        store: HomeStore,
        caller: HomeCaller,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._caller = caller
        self._clock = clock
        self._cache: dict[str, tuple[float, DevicesRecord]] = {}

    # ---- reading the list ----------------------------------------------------------------------

    async def exposed(self, uid: str) -> DevicesRecord:
        rec = await self._store.load_devices(uid)
        self._cache[uid] = (self._clock(), rec)
        return rec

    def cached(self, uid: str) -> DevicesRecord | None:
        """The last list read in the last 2 minutes, for the one pure (sync) risk check."""
        hit = self._cache.get(uid)
        return hit[1] if hit is not None and self._clock() - hit[0] <= CACHE_TTL_S else None

    async def state_part(self, uid: str) -> BridgeState:
        rec = await self._store.load_devices(uid)
        return BridgeState(
            devices=DevicesState(
                rev=rec.rev,
                exposed=tuple(
                    ExposedDevice(entity_id=e.entity_id, tier=e.tier)  # type: ignore[arg-type]
                    for e in rec.entries
                ),
            )
        )

    # ---- the catalogue and the exposed list ----------------------------------------------------

    async def catalogue(self, uid: str) -> list[dict[str, Any]]:
        """Every exposable entity Home Assistant has, with the classes he may pick."""
        reply = await self._raw_catalogue(uid)
        out: list[dict[str, Any]] = []
        for item in parse_items(reply):
            tiers = classes.allowed_tiers(item.entity_id, _device_class(item.device_class))
            if tiers:
                out.append(
                    {
                        "entity_id": item.entity_id,
                        "name": clean_name(item.name, NAME_MAX),
                        "device_class": _device_class(item.device_class),
                        "classes": list(tiers),
                        "default": tiers[0],
                    }
                )
        return out

    async def expose(self, uid: str, wanted: object) -> DevicesRecord:
        """Replace the exposed list. Every entity must exist at home and every class must be one
        its table allows; labels are cleaned. Pushes the list to the bridge (best effort)."""
        if not isinstance(wanted, list) or len(wanted) > MAX_EXPOSED:
            raise DeviceRejected("too_many", f"You can expose up to {MAX_EXPOSED} devices.")
        known = {i.entity_id: i for i in parse_items(await self._raw_catalogue(uid))}
        entries: list[ExposedEntry] = []
        for row in wanted:
            entries.append(self._entry(row, known, entries))
        saved = await self._store.save_devices(uid, tuple(entries))
        self._cache[uid] = (self._clock(), saved)
        await self._push(uid, saved)
        return saved

    async def _raw_catalogue(self, uid: str) -> Mapping[str, Any]:
        reply = await self._caller.call(uid, "GET", "/bridge/v1/devices", query={"catalogue": "1"})
        if reply.get("ha") is False:
            raise HomeRefused("ha_off", HA_OFF)
        return reply

    @staticmethod
    def _entry(
        row: object, known: Mapping[str, _Item], so_far: Sequence[ExposedEntry]
    ) -> ExposedEntry:
        if not isinstance(row, dict):
            raise DeviceRejected("invalid", BAD_LIST)
        entity, tier = row.get("entity_id"), row.get("class")
        if not isinstance(entity, str) or entity not in known or not isinstance(tier, str):
            raise DeviceRejected("unknown_device", "One of those devices isn't in Home Assistant.")
        if any(e.entity_id == entity for e in so_far):
            raise DeviceRejected("invalid", BAD_LIST)
        item = known[entity]
        dclass = _device_class(item.device_class)
        if not classes.tier_ok(entity, dclass, tier):
            raise DeviceRejected("class_not_allowed", "That device can't be set to that class.")
        label = row.get("label")
        clean = clean_name(label, LABEL_MAX) if isinstance(label, str) else ""
        return ExposedEntry(
            entity_id=entity,
            tier=tier,
            device_class=dclass,
            label=clean or None,
            name=clean_name(item.name, NAME_MAX) or None,
        )

    async def _push(self, uid: str, rec: DevicesRecord) -> None:
        state = await self.state_part(uid)
        try:
            await self._caller.call(uid, "POST", "/bridge/v1/state", state.model_dump(mode="json"))
        except (HomeOffline, HomeRefused):
            log.info("devices will reach the laptop at its next heartbeat")

    # ---- using a device ------------------------------------------------------------------------

    async def states(self, uid: str) -> dict[str, _Item]:
        """The current state of the exposed devices only (anything else the laptop sends is
        ignored)."""
        rec = await self.exposed(uid)
        reply = await self._caller.call(uid, "GET", "/bridge/v1/devices")
        if reply.get("ha") is False:
            raise HomeRefused("ha_off", HA_OFF)
        mine = {e.entity_id for e in rec.entries}
        return {i.entity_id: i for i in parse_items(reply) if i.entity_id in mine}

    async def control(
        self, uid: str, entry: ExposedEntry, action: str, value: object
    ) -> dict[str, Any]:
        """Do one allow-listed action on one exposed device. Raises ValueError (plain words) for
        an action the table doesn't have, HomeOffline / HomeRefused from the bridge."""
        if entry.tier == "read":
            raise ValueError("that device is read only")
        bounded = classes.check_action(entry.entity_id, action, value)
        body: dict[str, Any] = {"entity_id": entry.entity_id, "action": action}
        if bounded is not None:
            body["value"] = bounded
        reply = await self._caller.call(uid, "POST", "/bridge/v1/devices/action", body)
        if reply.get("done") is not True:
            raise HomeRefused("not_done", "Your home laptop didn't do that.")
        return {"done": True}


__all__ = [
    "DeviceRejected",
    "DeviceService",
    "clean_name",
    "parse_items",
    "resolve_entry",
]
