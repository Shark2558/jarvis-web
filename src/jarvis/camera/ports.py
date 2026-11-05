# src/jarvis/camera/ports.py
"""The few things camera code needs from other workstreams, as small local ports (R3 B).

A owns the home link and D the notify settings; I1 wires these adapters. Each default here is the
safe one: no home id (nothing can be disarmed), no snapshot (no picture leaves home).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from jarvis.logging import get_logger

if TYPE_CHECKING:
    from jarvis.faces.ports import FaceDirectory, Resolved

log = get_logger(__name__)


class CameraUnavailable(RuntimeError):
    """Camera data can't be read or saved right now (plain words, never a cause)."""


class AlarmRefused(Exception):
    """The alarm change was refused. `code` is a short word, the message plain words."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@runtime_checkable
class HomeDirectory(Protocol):
    """A's link record: the owner's home id `h_<8 hex>`, or None when no laptop is linked."""

    async def home_id(self, uid: str) -> str | None: ...


@runtime_checkable
class SnapshotPolicy(Protocol):
    """D's notify settings: did the owner opt in to a small photo with burglar alerts?"""

    async def snapshot_on(self, uid: str) -> bool: ...


class NoSnapshots:
    async def snapshot_on(self, uid: str) -> bool:
        return False


async def safe_resolve(
    faces: FaceDirectory, uid: str, person: str | None, score: float | None
) -> Resolved:
    """Who a face is, or "nobody recognised" when the directory can't answer. A face lookup that
    fails must never cost a burglar alert, so every camera path asks through here."""
    from jarvis.faces.ports import Resolved

    try:
        return await faces.resolve(uid, person, score)
    except Exception as exc:  # noqa: BLE001 - unrecognised is the safe answer
        log.warning("face lookup failed", extra={"reason": type(exc).__name__})
        return Resolved()


__all__ = [
    "AlarmRefused",
    "CameraUnavailable",
    "HomeDirectory",
    "NoSnapshots",
    "SnapshotPolicy",
    "safe_resolve",
]
