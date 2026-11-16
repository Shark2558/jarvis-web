# src/jarvis/wardrobe/catalog/events.py
"""The one builder of a server-made ledger event (docs/plans/r13-wardrobe.md D4): a tap in his
panel unless `source` says otherwise; the store settles its time when it is appended."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.wardrobe.model import Event, new_id


def event(pid: str, kind: str, at: datetime, **fields: Any) -> Event:
    body = {"id": new_id("we"), "piece": pid, "kind": kind, "at": at, "recorded": at}
    given = {k: v for k, v in fields.items() if v is not None}
    return Event.model_validate({**body, "source": "tap", **given})


__all__ = ["event"]
