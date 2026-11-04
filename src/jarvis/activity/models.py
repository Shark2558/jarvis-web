# src/jarvis/activity/models.py
"""What the Activity view keeps and shows (R1 plan D7/D8; Layer 7 data model).

An `ActivityItem` is one thing JARVIS did (or was stopped from doing) for the owner, in plain
words. It never holds query text of a read, a result, or anything the model said. `ActivityRow`
is what `GET /v1/activity` sends: plain text the console renders with textContent.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ACT_ID = re.compile(r"act_[0-9a-f]{20}")

Kind = Literal["read", "write", "delete", "send", "draft", "restore"]
Outcome = Literal["done", "waiting", "refused", "failed", "declined"]
Channel = Literal["console", "voice", "telegram"]
UndoState = Literal["available", "restored", "expired", "gone"]
Day = Literal["today", "yesterday"]


class ActivityItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    user_id: str
    at: datetime
    tool: str
    risk: str
    kind: Kind
    outcome: Outcome
    words: str
    channel: Channel = "console"
    offline: bool = False
    session_id: str | None = None
    trace_id: str | None = None
    audit_seq: int | None = None
    undo_id: str | None = None


class UndoView(BaseModel):
    id: str
    state: UndoState


class ActivityRow(BaseModel):
    id: str
    at: datetime
    words: str
    outcome: Outcome
    channel: Channel
    offline: bool
    undo: UndoView | None = None
    undo_note: str = ""


class ActivityView(BaseModel):
    day: Day
    items: list[ActivityRow]
    verified: bool = True
    available: bool = True


__all__ = [
    "ACT_ID",
    "ActivityItem",
    "ActivityRow",
    "ActivityView",
    "Channel",
    "Day",
    "Kind",
    "Outcome",
    "UndoState",
    "UndoView",
]
