# src/jarvis/helpers/kinds.py
"""The fixed names of R11 (docs/plans/r11-free-helpers.md D2-D6, D16, D17, data model).

Every part uses exactly these: its alert kinds (the gate refuses any other), its tick job names
(the composites refuse any other), its privacy ids, its tool-name families and its collections
(the Architecture Guide's C60 card lists them all, so the coverage check stays green while the
parts build in parallel). Pure data, no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, get_args

from jarvis.alerts import R11_ALERT_KINDS, AlertKind

PartName = Literal["today", "house", "nudges", "kitchen"]
PARTS: tuple[PartName, ...] = get_args(PartName)  # A, B, C, D, in build order
LETTER: Mapping[PartName, str] = MappingProxyType(
    {"today": "A", "house": "B", "nudges": "C", "kitchen": "D"}
)

NudgeKind = Literal[
    "nudge_standup", "nudge_hydrate", "nudge_activity", "nudge_free_time", "nudge_focus"
]
NUDGE_KINDS: tuple[NudgeKind, ...] = get_args(NudgeKind)
# D6: the per-kind daily caps until the owner sets his own (never above the deployment's total)
DEFAULT_CAPS: Mapping[str, int] = MappingProxyType(
    {
        "nudge_standup": 8,
        "nudge_hydrate": 8,
        "nudge_activity": 3,
        "nudge_free_time": 2,
        "nudge_focus": 2,
    }
)
MAX_CAP = 24  # a per-kind cap the owner may set (the deployment's daily total still applies)

# D5: which part may send which kind (`gate.PartSender` refuses the rest)
KINDS_OF: Mapping[PartName, tuple[AlertKind, ...]] = MappingProxyType(
    {
        "today": ("bill_due", "birthday"),
        "house": (
            "chore_due",
            "maintenance_due",
            "weather_warning",
            "weather_note",
            "disaster_alert",
            "breach_notice",
        ),
        "nudges": NUDGE_KINDS,
        "kitchen": (),
    }
)

# D3: the jobs each part may put on the 5-minute clock and on the morning tick
CLOCK_JOB = "helpers_clock"
DAILY_JOB = "helpers_daily"
SWEEP_JOB = "helpers_sweep"  # I0's own: old send-log days
CLOCK_JOBS: Mapping[PartName, tuple[str, ...]] = MappingProxyType(
    {
        "today": ("bills_due", "birthdays"),
        "house": ("chores_due", "maint_due", "weather_poll", "disaster_poll"),
        "nudges": ("nudges", "activity_check"),
        "kitchen": (),
    }
)
DAILY_JOBS: Mapping[PartName, tuple[str, ...]] = MappingProxyType(
    {"today": (), "house": ("breach_watch",), "nudges": (), "kitchen": ("grocery_spend",)}
)

# D17: privacy ids (section "Helpers"); I0 owns `helpers_nudge`
PRIVACY_SECTION = "Helpers"
GATE_PRIVACY_ID = "helpers_nudge"
PRIVACY_IDS: Mapping[PartName, tuple[str, ...]] = MappingProxyType(
    {
        "today": ("helpers_bills", "helpers_birthdays"),
        "house": ("helpers_house", "helpers_place"),
        "nudges": ("helpers_wellbeing",),
        "kitchen": ("helpers_kitchen", "helpers_spend"),
    }
)

# D16: the tool-name families of each part (a part registers only tools named so)
TOOL_FAMILIES: Mapping[PartName, tuple[str, ...]] = MappingProxyType(
    {
        "today": ("bill_", "focus_", "pending_", "contacts_birthdays"),
        "house": ("chore_", "maint_", "weather_", "disaster_", "breach_"),
        "nudges": ("nudge_", "freetime_"),
        "kitchen": (
            "pantry_",
            "recipe_",
            "nutrition_",
            "spend_",
            "kitchen_",
            "calendar_kitchen_blocks",
        ),
    }
)

# The data model's collections (without the prefix), by owner; listed in the guide's C60 card
COLLECTIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "core": ("helpers_nudge", "helpers_gate", "helpers_clock"),
        "today": ("bills", "bills_told", "birthdays_told"),
        "house": ("chores", "maintenance", "house_told", "outside"),
        "nudges": ("nudges", "wellbeing"),
        "kitchen": ("kitchen", "spend", "spend_scan"),
    }
)

# The console's sub-tabs, one per part (D19), in order
TABS: Mapping[PartName, str] = MappingProxyType(
    {"today": "Today", "house": "Home", "nudges": "Nudges", "kitchen": "Kitchen"}
)


def tool_allowed(part: PartName, name: str) -> bool:
    """Whether `name` is in one of the part's tool families (a prefix, or the exact name)."""
    return any(name == f or (f.endswith("_") and name.startswith(f)) for f in TOOL_FAMILIES[part])


def part_kinds() -> frozenset[str]:
    """Every kind some part may send (tests: exactly `alerts.R11_ALERT_KINDS`)."""
    return frozenset(k for kinds in KINDS_OF.values() for k in kinds)


__all__ = [
    "CLOCK_JOB",
    "CLOCK_JOBS",
    "COLLECTIONS",
    "DAILY_JOB",
    "DAILY_JOBS",
    "DEFAULT_CAPS",
    "GATE_PRIVACY_ID",
    "KINDS_OF",
    "LETTER",
    "MAX_CAP",
    "NUDGE_KINDS",
    "PARTS",
    "PRIVACY_IDS",
    "PRIVACY_SECTION",
    "SWEEP_JOB",
    "TABS",
    "R11_ALERT_KINDS",
    "TOOL_FAMILIES",
    "NudgeKind",
    "PartName",
    "part_kinds",
    "tool_allowed",
]
