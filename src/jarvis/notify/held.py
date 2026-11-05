# src/jarvis/notify/held.py
"""Held alerts (R3 D10): important alerts that arrived in quiet hours are kept as kind + time (+
camera id), no text, and sent as ONE summary when quiet hours end (the service reads the items,
sends, and only then discards them)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from jarvis.notify.ports import Signal
from jarvis.notify.store import NotifyStore

_WORDS = {
    "home_package": "package",
    "home_offline": "laptop offline",
    "home_arm_failed": "alarm arming problem",
    "approval_waiting": "waiting for approval",
    "vault_expiry": "document reminder",
    "test": "test",
}


class Held:
    def __init__(self, store: NotifyStore) -> None:
        self._store = store

    async def add(self, uid: str, signal: Signal, now: datetime) -> int:
        item = {"kind": signal.kind, "at": now.isoformat()}
        if signal.camera:
            item["camera"] = signal.camera
        return await self._store.held_add(uid, item)


def summary(items: list[dict[str, str]]) -> str:
    counts = Counter(_WORDS.get(i.get("kind", ""), "alert") for i in items)
    parts = [f"{n} {word}" for word, n in sorted(counts.items())]
    total = len(items)
    noun = "alert" if total == 1 else "alerts"
    return f"While you were resting, {total} {noun} were held ({', '.join(parts)}). Open JARVIS."


__all__ = ["Held", "summary"]
