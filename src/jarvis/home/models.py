# src/jarvis/home/models.py
"""The cloud's view of a linked home (R3 D4, D6; Layer 7). Cloud only (not in the home kit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from jarvis.home.signing import HomeKeys, derive_keys

HomeState = Literal["linked", "online", "offline", "degraded"]
LABEL_MAX = 40
BRIDGE_PORT = 8443


@dataclass(frozen=True, repr=False)
class HomeRecord:
    """The encrypted part of a home: where the bridge is and the seed that makes both keys."""

    home_id: str
    bridge_url: str
    seed: bytes

    def keys(self) -> HomeKeys:
        return derive_keys(self.seed)

    def __repr__(self) -> str:
        return f"HomeRecord({self.home_id})"


@dataclass(frozen=True)
class HomeStatus:
    """The clear part of a home document: no URL, no seed, no name."""

    home_id: str
    state: HomeState
    linked_at: float
    last_seen_at: float | None
    parts: dict[str, Any] = field(default_factory=dict)
    bridge_version: str | None = None
    dropped_disarmed: int = 0
    outage_alerted: bool = False


@dataclass(frozen=True)
class ExposedEntry:
    """One device the owner chose to expose. `label` is the owner's own name (vouches); without
    one the Home Assistant name is other people's words (fenced)."""

    entity_id: str
    tier: str
    device_class: str | None = None
    label: str | None = None
    name: str | None = None  # Home Assistant's name when exposed: other people's words


@dataclass(frozen=True)
class DevicesRecord:
    rev: int = 0
    entries: tuple[ExposedEntry, ...] = ()


@dataclass(frozen=True)
class Seen:
    previous: HomeState
    outage_alerted: bool


__all__ = [
    "BRIDGE_PORT",
    "LABEL_MAX",
    "DevicesRecord",
    "ExposedEntry",
    "HomeRecord",
    "HomeState",
    "HomeStatus",
    "Seen",
]
