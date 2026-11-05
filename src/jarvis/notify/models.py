# src/jarvis/notify/models.py
"""The owner's notify settings (R3 D10; Firestore `notify/{uid}`), pure data.

`NotifySettings` is what `policy.decide` reads. `tz` is not stored: the service fills it from
`Settings.user_timezone`. Defaults follow D20: quiet hours 23:00-06:30 on, only urgent things
ring, names off, snapshot off, nobody on the VIP list, greeting alerts feed-only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
MAX_VIPS = 20
KindSwitch = Literal["on", "off", "feed"]
# Burglar and hazard alerts (and the storm summary that follows them) have no switch:
# disarming is the switch (D10 rule 2).
NO_SWITCH: frozenset[str] = frozenset({"home_intruder", "home_hazard", "home_summary", "test"})
DEFAULT_SWITCH: dict[str, KindSwitch] = {"home_greeting": "feed"}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QuietHours(_Frozen):
    on: StrictBool = True
    start: str = Field(default="23:00", pattern=HHMM)
    end: str = Field(default="06:30", pattern=HHMM)


class Snapshot(_Frozen):
    on: StrictBool = False
    at: str | None = Field(default=None, max_length=40)


class Vip(_Frozen):
    id: str = Field(pattern=r"^v_[0-9a-f]{8}$")
    kind: Literal["face", "phone", "email"]
    ref: str = Field(min_length=1, max_length=200)


class NotifySettings(_Frozen):
    quiet: QuietHours = Field(default_factory=QuietHours)
    ring_for: Literal["important", "urgent"] = "urgent"
    kinds: dict[str, KindSwitch] = Field(default_factory=dict)
    names_in_alerts: StrictBool = False
    snapshot: Snapshot = Field(default_factory=Snapshot)
    vip: tuple[Vip, ...] = Field(default=(), max_length=MAX_VIPS)
    rev: int = Field(default=0, ge=0)
    tz: str = Field(default="Asia/Kolkata", exclude=True, max_length=64)

    @field_validator("kinds")
    @classmethod
    def _known_kinds(cls, v: dict[str, KindSwitch]) -> dict[str, KindSwitch]:
        from jarvis.notify.ports import DEFAULT_URGENCY

        for k in v:
            if k not in DEFAULT_URGENCY:
                raise ValueError("unknown alert kind")
        return v

    def switch(self, kind: str) -> KindSwitch:
        """on | off | feed. Kinds with no switch are always on."""
        if kind in NO_SWITCH:
            return "on"
        return self.kinds.get(kind) or DEFAULT_SWITCH.get(kind, "on")


__all__ = [
    "DEFAULT_SWITCH",
    "MAX_VIPS",
    "NO_SWITCH",
    "KindSwitch",
    "NotifySettings",
    "QuietHours",
    "Snapshot",
    "Vip",
]
