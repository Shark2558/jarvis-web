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
# The to-do list (slice 10 C) has its own optional scope, hence one more state.
TodoState = Literal["ok", "not_connected", "not_granted", "unavailable"]

EARLIEST = dt.time(4, 0)
LATEST = dt.time(11, 30)
DEFAULT_TIME = "07:00"
_HHMM = re.compile(r"([0-9]{2}):([0-9]{2})")  # ASCII only: `\d` takes ٠٧ and int() parses it
TIME_RULE = "Pick a time between 04:00 and 11:30, on the hour or the half hour."
AI_LABEL = "AI summary — written from your calendar and other people's emails; may be wrong"
# Version of the AI-summary consent text: 1 = calendar + mail (slice 7); 2 = also the titles of
# to-dos due today or overdue (slice 10 C). Titles go to the AI only under consent ≥ 2.
AI_CONSENT_VERSION = 2


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
    ai_consent: int = Field(
        default=1, description="Version of the AI consent text last confirmed (AI_CONSENT_VERSION)"
    )
    # R1 D13 / D15: the deterministic Deliveries and Family today sections (never sent to the AI)
    deliveries: bool = True
    family: bool = True
    # R2 D5: the deterministic Documents section (vault documents due), never sent to the AI
    vault: bool = True
    # R3 B: the deterministic "Home overnight" section (held alerts, parcels, visitors), never AI
    home: bool = True

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
    reminder: bool = Field(default=False, description="A reminder JARVIS set (slice 11)")


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


class InboxGroup(Frozen):
    key: str
    label: str
    unread: int = 0


class InboxSection(Frozen):
    total: int = 0
    items: tuple[InboxItem, ...] = ()
    groups: tuple[InboxGroup, ...] = ()  # R11.1 D20: Gmail's own categories, counted
    withheld: int = 0  # not listed: they look like a code or a bank message
    exact: bool = True  # False: the INBOX label could not be read; `total` is "about"
    failed: int = 0  # listed messages that could not be read just now ...
    listed: int = 0  # ... of these


class JarvisSection(Frozen):
    approvals_waiting: int = 0


class TodoItem(Frozen):
    title: str
    due: str = Field(description="YYYY-MM-DD: a date (Google Tasks keeps no time)")
    overdue: bool = False
    list: str = Field(default="", description="The list's name; '' when the owner has one list")


class TodoSection(Frozen):
    """Overdue + due today across the owner's lists (slice 10 C)."""

    total: int = Field(default=0, description="How many were found (items holds ≤ 10)")
    overdue: int = 0
    items: tuple[TodoItem, ...] = ()
    complete: bool = Field(
        default=True, description="False: the read budget ran out, so the counts are 'at least'"
    )


class DeliveryItem(Frozen):
    """One parcel (R1 D13). `item` is the mail subject: someone else's words."""

    item: str
    status: str = Field(description="ordered | shipped | out_for_delivery | delivered | ...")
    merchant: str = ""
    carrier: str = ""
    expected: str = Field(default="", description="YYYY-MM-DD, '' when the mail gave none")


class DeliveriesSection(Frozen):
    """Parcels on their way (or delivered today), from order emails. Deterministic, no AI."""

    total: int = Field(default=0, description="How many were found (items holds <= 5)")
    items: tuple[DeliveryItem, ...] = ()
    state: SectionState = "ok"


class FamilyEvent(Frozen):
    when: str = Field(description="'09:30', 'All day' or '10:00-11:00'")
    title: str = Field(default="", description="Their words; '' for a busy block")


class FamilyMemberDay(Frozen):
    name: str = Field(description="The owner's own label for the person")
    events: tuple[FamilyEvent, ...] = ()
    busy_only: bool = False
    unavailable: bool = False


class FamilySection(Frozen):
    """What family members' calendars hold today (R1 D15); titles are their words."""

    members: tuple[FamilyMemberDay, ...] = ()
    state: SectionState = "ok"


class VaultDueItem(Frozen):
    """One vault document that is due: the type label, whose, the date. Never a name or last 4."""

    type_label: str
    whose: Literal["you", "family"] = "you"
    expires_on: str = Field(description="YYYY-MM-DD")
    days_left: int


class VaultDueSection(Frozen):
    """Vault documents expiring within 90 days or expired in the last 30 (R2 D5). Deterministic,
    no AI. `inbox_copy`: the Gmail copy may carry the details (else it says only how many)."""

    total: int = Field(default=0, description="How many are due (items holds <= 5)")
    items: tuple[VaultDueItem, ...] = ()
    state: SectionState = "ok"
    inbox_copy: bool = False


class HomeOvernightItem(Frozen):
    """One thing the camera noted overnight: a local time and fixed words. Never a name."""

    when: str = Field(description="HH:MM local")
    words: str


class HomeOvernightSection(Frozen):
    """What the home camera noted since last evening (R3 D10, D16). Counts and times only: no
    name, no picture. Deterministic, never part of the AI-summary input."""

    total: int = Field(default=0, description="How many entries there were (items holds <= 5)")
    held: int = Field(default=0, description="Alerts held back for quiet hours")
    items: tuple[HomeOvernightItem, ...] = ()
    state: SectionState = "ok"


class VitalsSection(Frozen):
    """R4 I1 (W10): the Vitals board's red / amber lines and this month's AI spend, as
    `vitals.brief.vitals_lines` words them (labels and limits, never a key). Deterministic, never
    part of the AI-summary input; absent (None) when the board has nothing to say."""

    lines: tuple[str, ...] = ()
    state: SectionState = "ok"


class HelpersSection(Frozen):
    """R11 (docs/plans/r11-free-helpers.md, I0 seam 8): today's helper lines (bills due, birthdays,
    chores and upkeep, the weather, a nudge's state, the month's grocery spend), each a fixed
    template from one part's `BriefContributor`. Deterministic, never part of the AI-summary
    input; absent (None) when no helper has anything to say."""

    lines: tuple[str, ...] = ()
    state: SectionState = "ok"


class SectionsStatus(Frozen):
    calendar: SectionState = "ok"
    inbox: SectionState = "ok"
    jarvis: SectionState = "ok"
    todo: TodoState = "ok"
    # R1: older stored records lack these two, so they default to "ok"
    deliveries: SectionState = "ok"
    family: SectionState = "ok"
    vault: SectionState = "ok"
    home: SectionState = "ok"
    vitals: SectionState = "ok"
    helpers: SectionState = "ok"  # R11


class BriefData(Frozen):
    date: str
    tz: str
    calendar: CalendarSection = CalendarSection()
    inbox: InboxSection = InboxSection()
    jarvis: JarvisSection = JarvisSection()
    # None: not read (a brief made before the to-do section existed, or its state says why)
    todo: TodoSection | None = None
    # R1: None = not read (switched off in the brief settings, no members, or an older brief)
    deliveries: DeliveriesSection | None = None
    family: FamilySection | None = None
    # R2: None = nothing due, switched off, or an older brief
    vault: VaultDueSection | None = None
    # R3: None = nothing overnight, switched off, not linked, or an older brief
    home: HomeOvernightSection | None = None
    # R4: None = nothing red or amber and no spend line, Vitals off, or an older brief
    vitals: VitalsSection | None = None
    # R11: None = no helper has a line today, helpers off, or an older brief
    helpers: HelpersSection | None = None
    sections_status: SectionsStatus = SectionsStatus()


# ---- stored record ------------------------------------------------------------------------


class AIBlock(Frozen):
    lines: tuple[str, ...]
    model: str
    cost_usd: float = 0.0
    offline: bool = False  # the owner's laptop answered, not the cloud model


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
    # the AI summary is on under the consent that names to-do titles (else they are not sent)
    ai_todo_consent: bool = False
    deliveries: bool = True
    family: bool = True
    vault: bool = True
    home: bool = True


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
    deliveries: bool | None = None
    family: bool | None = None
    vault: bool | None = None
    home: bool | None = None
    confirm_spend: bool = False
    confirm_inbox: bool = False


class TickResult(Frozen):
    checked: int = 0
    generated: int = 0
    delivered: int = 0
    # housekeeping sweeps of this tick: name -> "ok" | "failed" (no error text, ever)
    sweeps: dict[str, Literal["ok", "failed"]] = Field(default_factory=dict)


__all__ = [
    "AI_CONSENT_VERSION",
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
    "DeliveriesSection",
    "DeliveryItem",
    "FamilyEvent",
    "FamilyMemberDay",
    "FamilySection",
    "FreeBlock",
    "InboxGroup",
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
    "TodoItem",
    "TodoSection",
    "TodoState",
    "VaultDueItem",
    "VaultDueSection",
    "VitalsSection",
    "HelpersSection",
    "Trigger",
    "parse_brief_time",
]
