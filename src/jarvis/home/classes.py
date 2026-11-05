# src/jarvis/home/classes.py
"""Device classes, actions and the service table (R3 D6, D17), shared by the cloud and the bridge.

Standard library plus `jarvis.home.ports` only (it ships in the home kit). The cloud stores the
class the owner picked and the bridge enforces it again against what Home Assistant reports, so a
wrong cloud record can never loosen a lock: a class may only be picked from `allowed_tiers`, and
the bridge refuses any exposed entity whose class is looser than the floor it works out itself.

- read: sensors, no action at all.
- everyday (R2): lights, fans, media players, blinds and curtains. May be tightened to passkey.
- passkey (R3): switches and plugs (a plug may power a geyser), climate, water heaters.
- always_passkey (R3): locks, alarm panels, sirens, valves, garage / gate / door covers.
- never exposed: scripts, automations, shell and REST commands, `homeassistant`, `hassio`,
  `notify`, `camera`, and Frigate's own detect / record / snapshot switches (use arm / disarm).
"""

from __future__ import annotations

from typing import Any, Final

from jarvis.home.ports import NEVER_EXPOSED_DOMAINS

READ_DOMAINS: Final = frozenset({"sensor", "binary_sensor", "weather"})
EVERYDAY_DOMAINS: Final = frozenset({"light", "fan", "media_player"})
ALWAYS_DOMAINS: Final = frozenset({"lock", "alarm_control_panel", "siren", "valve"})
COVER_EVERYDAY_CLASSES: Final = frozenset({"blind", "curtain", "shade", "awning", "shutter"})
COVER_ALWAYS_CLASSES: Final = frozenset({"garage", "gate", "door"})
HAZARD_CLASSES: Final = frozenset({"smoke", "carbon_monoxide", "gas", "moisture", "safety"})
# Frigate's own switches in Home Assistant (its HA integration): arming is the only door.
FRIGATE_SWITCH_SUFFIXES: Final = (
    "_detect",
    "_motion",
    "_recordings",
    "_snapshots",
    "_review_alerts",
    "_review_detections",
    "_audio_detection",
    "_improve_contrast",
    "_object_descriptions",
    "_ptz_autotracker",
)
STRICTNESS: Final = {"read": 0, "everyday": 1, "passkey": 2, "always_passkey": 3}

ACTIONS: Final[dict[str, tuple[str, ...]]] = {
    "light": ("turn_on", "turn_off", "toggle", "set_brightness"),
    "fan": ("turn_on", "turn_off", "toggle"),
    "switch": ("turn_on", "turn_off", "toggle"),
    "media_player": ("media_pause", "media_play", "set_volume"),
    "cover": ("open", "close"),
    "lock": ("lock", "unlock"),
    "climate": ("turn_on", "turn_off"),
    "water_heater": ("turn_on", "turn_off"),
    "siren": ("turn_on", "turn_off"),
    "valve": ("open", "close"),
    "alarm_control_panel": (),
}
ALL_ACTIONS: Final = tuple(sorted({a for acts in ACTIONS.values() for a in acts}))
VALUE_ACTIONS: Final[dict[str, tuple[float, float]]] = {
    "set_brightness": (0, 100),
    "set_volume": (0.0, 1.0),
}
_SERVICE: Final = {
    "set_brightness": "turn_on",
    "media_pause": "media_pause",
    "media_play": "media_play",
    "set_volume": "volume_set",
}


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def is_frigate_switch(entity_id: str) -> bool:
    return domain_of(entity_id) == "switch" and entity_id.endswith(FRIGATE_SWITCH_SUFFIXES)


def allowed_tiers(entity_id: str, device_class: str | None) -> tuple[str, ...]:
    """The classes the owner may pick for this entity, the default first; () = not exposable."""
    domain = domain_of(entity_id)
    if domain in NEVER_EXPOSED_DOMAINS or is_frigate_switch(entity_id):
        return ()
    if domain in READ_DOMAINS:
        return ("read",)
    if domain in EVERYDAY_DOMAINS:
        return ("everyday", "passkey")
    if domain == "switch":
        return ("passkey", "everyday")
    if domain in ("climate", "water_heater"):
        return ("passkey",)
    if domain in ALWAYS_DOMAINS:
        return ("always_passkey",)
    if domain == "cover":
        cls = device_class if isinstance(device_class, str) else ""
        if cls in COVER_ALWAYS_CLASSES:
            return ("always_passkey",)
        if cls in COVER_EVERYDAY_CLASSES:
            return ("everyday", "passkey")
        return ("passkey",)
    return ()


def tier_ok(entity_id: str, device_class: str | None, tier: str) -> bool:
    return tier in allowed_tiers(entity_id, device_class)


def floor_tier(entity_id: str, device_class: str | None) -> str | None:
    """The loosest class this entity may ever have (the bridge's own view), None = never."""
    tiers = allowed_tiers(entity_id, device_class)
    return min(tiers, key=lambda t: STRICTNESS[t]) if tiers else None


def actions_for(entity_id: str) -> tuple[str, ...]:
    return ACTIONS.get(domain_of(entity_id), ())


def check_action(entity_id: str, action: object, value: object) -> float | int | None:
    """The bounded value for this action (None when it takes none), or ValueError (plain)."""
    if not isinstance(action, str) or action not in actions_for(entity_id):
        raise ValueError("that device can't do that")
    bounds = VALUE_ACTIONS.get(action)
    if bounds is None:
        if value is not None:
            raise ValueError("that action takes no value")
        return None
    lo, hi = bounds
    if isinstance(value, bool) or not isinstance(value, int | float) or value != value:
        raise ValueError("that action needs a number")
    if not lo <= value <= hi:
        raise ValueError(f"the value must be between {lo} and {hi}")
    return int(value) if action == "set_brightness" else float(value)


def service_call(
    entity_id: str, action: str, value: float | int | None
) -> tuple[str, str, dict[str, Any]]:
    """(domain, service, data) for Home Assistant's REST API. Fixed table: nothing free-form."""
    domain = domain_of(entity_id)
    data: dict[str, Any] = {"entity_id": entity_id}
    if action == "set_brightness":
        data["brightness_pct"] = value
    elif action == "set_volume":
        data["volume_level"] = value
    if action in ("open", "close"):
        service = f"{action}_{'cover' if domain == 'cover' else 'valve'}"
    else:
        service = _SERVICE.get(action, action)
    return domain, service, data


__all__ = [
    "ACTIONS",
    "ALL_ACTIONS",
    "HAZARD_CLASSES",
    "STRICTNESS",
    "actions_for",
    "allowed_tiers",
    "check_action",
    "domain_of",
    "floor_tier",
    "service_call",
    "tier_ok",
]
