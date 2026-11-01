# src/jarvis/brief/models.py
"""Morning brief data (Layer 7 records, Layer 8 views). Every model is frozen.

`BriefData` is what was collected (facts only, already cleaned to one-line text); `BriefRecord`
is the stored document per owner per local day; the `*View` models are the exact JSON shapes
the console reads (`api/brief.py`). Snippets of mail never appear here: they go to the AI only.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BriefStatus = Literal["generating", "ready", "failed"]
ViewStatus = Literal["none", "generating", "ready", "failed"]
Trigger = Literal["scheduled", "manual", "open"]
InboxStatus = Literal["off", "sending", "delivered", "failed", "unknown"]
SectionState = Literal["ok", "not_connected", "unavailable"]

EARLIEST = dt.time(4, 0)
LATEST = dt.time(11, 30)
DEFAULT_TIME = "07:00"
_HHMM = re.compile(r"([0-9]{2}):([0-9]{2})")  # ASCII only: `\d` takes ٠٧ and int() parses it
TIME_RULE = "Pick a time between 04:00 and 11:30, on the hour or the half hour."
AI_LABEL = "AI summary — written from your calendar and other people's emails; may be wrong"


def parse_brief_time(value: str) -> dt.time:
    """'HH:MM' in 04:00…11:30 on :00 or :30 → time; ValueError (owner-friendly) otherwise."""
    m = _HHMM.fullmatch(value) if isinstance(value, str) else None
    if m is None:
        raise ValueError(TIME_RULE)
    hour, minute = int(m.group(1)), int(m.group(2))
    if minute not in (0, 30) or hour > 23:
        raise ValueError(TIME_RULE)
    t = dt.time(hour, minute)
    if not EARLIEST <= t <= LATEST:
        raise ValueError(TIME_RULE)
    return t


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


# ---- settings -----------------------------------------------------------------------------


class BriefSettings(Frozen):
    enabled: bool = True
    time: str = DEFAULT_TIME
    ai_summary: bool = False
    inbox_delivery: bool = False
    updated_at: dt.datetime | None = None
    tz: str | None = Field(default=None, description="Last calendar time zone seen (cache)")

    @field_validator("time")
    @classmethod
    def _check_time(cls, v: str) -> str:
        parse_brief_time(v)
        return v

    @property
    def at(self) -> dt.time:
        return parse_brief_time(self.time)


# ---- collected data -----------------------------------------------------------------------


class BriefEvent(Frozen):
    title: str
    start: str = Field(description="Local HH:MM; '' for all-day")
    end: str = Field(description="Local HH:MM; '' for all-day")
    all_day: bool = False
    starts_earlier: bool = Field(default=False, description="Began before this day")
    ends_later: bool = Field(default=False, description="Runs past midnight")
    location: str | None = None
    attendees: int = 0
    has_video: bool = False
    overlaps_with: tuple[str, ...] = ()


class FreeBlock(Frozen):
    start: str
    end: str
    minutes: int


class CalendarSection(Frozen):
    today: tuple[BriefEvent, ...] = ()
    clashes: int = 0
    free_blocks: tuple[FreeBlock, ...] = ()
    tomorrow_first: BriefEvent | None = None


class InboxItem(Frozen):
    from_name: str
    from_address: str
    subject: str
    date: str = Field(description="ISO 8601 in the brief's time zone ('' if unknown)")
    when: str = Field(description="'07:42' or 'yesterday 21:10'")


class InboxSection(Frozen):
    total: int = 0
    items: tuple[InboxItem, ...] = ()


class JarvisSection(Frozen):
    approvals_waiting: int = 0


class SectionsStatus(Frozen):
    calendar: SectionState = "ok"
    inbox: SectionState = "ok"
    jarvis: SectionState = "ok"


class BriefData(Frozen):
    date: str
    tz: str
    calendar: CalendarSection = CalendarSection()
    inbox: InboxSection = InboxSection()
    jarvis: JarvisSection = JarvisSection()
    sections_status: SectionsStatus = SectionsStatus()


# ---- stored record ------------------------------------------------------------------------


class AIBlock(Frozen):
    lines: tuple[str, ...]
    model: str
    cost_usd: float = 0.0


class InboxState(Frozen):
    status: InboxStatus = "off"
    at: dt.datetime | None = None
    message_id: str | None = None


class BriefRecord(Frozen):
    """`{prefix}briefs/{uid}_{YYYY-MM-DD}` (local date)."""

    user_id: str
    date: str
    tz: str
    status: BriefStatus
    claim_id: str
    claimed_at: dt.datetime
    trigger: Trigger
    created_at: dt.datetime | None = Field(default=None, description="When the content was made")
    data: BriefData | None = None
    ai: AIBlock | None = None
    ai_note: str | None = None
    text: str = ""
    error: str | None = None
    seen_at: dt.datetime | None = None
    inbox: InboxState = InboxState()
    ai_calls_today: int = 0
    generations: int = 0
    retries: int = Field(
        default=0, description="Scheduled retries of a brief with an unavailable section"
    )


# ---- API views (the console codes against these exact shapes) -----------------------------


class AIView(Frozen):
    lines: tuple[str, ...]
    model: str
    cost_usd: float
    label: str = AI_LABEL


class BriefView(Frozen):
    date: str
    tz: str
    status: BriefStatus
    trigger: Trigger
    created_at: dt.datetime | None
    seen_at: dt.datetime | None
    data: BriefData | None
    ai: AIView | None
    ai_note: str | None
    text: str
    error: str | None
    inbox: InboxState
    ai_calls_today: int
    generations_left: int


class SettingsView(Frozen):
    enabled: bool
    time: str
    ai_summary: bool
    inbox_delivery: bool
    updated_at: dt.datetime | None


class TodayView(Frozen):
    date: str
    tz: str
    status: ViewStatus
    brief: BriefView | None
    settings: SettingsView
    due_at: dt.datetime | None
    google_connected: bool
    ai_available: bool
    inbox_available: bool
    ai_cost_note: str


class SeenView(Frozen):
    ok: bool
    date: str
    seen_at: dt.datetime


class SettingsPatch(BaseModel):
    """PUT /v1/brief/settings body. Strict: a confirm flag must be the JSON literal true."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    enabled: bool | None = None
    time: str | None = None
    ai_summary: bool | None = None
    inbox_delivery: bool | None = None
    confirm_spend: bool = False
    confirm_inbox: bool = False


class TickResult(Frozen):
    checked: int = 0
    generated: int = 0
    delivered: int = 0


__all__ = [
    "AI_LABEL",
    "AIBlock",
    "AIView",
    "BriefData",
    "BriefEvent",
    "BriefRecord",
    "BriefSettings",
    "BriefStatus",
    "BriefView",
    "CalendarSection",
    "FreeBlock",
    "InboxItem",
    "InboxSection",
    "InboxState",
    "JarvisSection",
    "SectionState",
    "SectionsStatus",
    "SeenView",
    "SettingsPatch",
    "SettingsView",
    "TickResult",
    "TodayView",
    "Trigger",
    "parse_brief_time",
]
