# src/jarvis/helpers/ports.py
"""The plug-in contract of R11 (docs/plans/r11-free-helpers.md D2).

A part's `part.build(ctx: HelperContext) -> HelperPart` gets everything it may use in `ctx` and
hands back everything the app wires for it in the `HelperPart`; it never touches a wiring file.

- `HelperPart`: its tools (registered through the gateway, names in its `kinds.TOOL_FAMILIES`),
  its `clock_jobs` (the 5-minute clock) and `daily_jobs` (the morning tick), named as
  `kinds.CLOCK_JOBS` / `kinds.DAILY_JOBS` say; its privacy rows (`kinds.PRIVACY_IDS`); its brief
  contributors (fixed-template lines for the brief's "Helpers" section); its pending sources (what
  "what is pending" and "top priority now" read, D9); its No-AI phrases (D18); the services its
  own routes read from `app.state.r11_parts[<part>].services`; one plain status line (`ready`).
- `HelperContext`: settings, the document store, the keyring (None: sealed data is OFF), the
  Google link (None: not linked), the part's own bound sender (`gate.PartSender`, the only way to
  tell the owner anything), billing, the brains (tier calls through `jarvis.llm` only), the one
  brain-mode switch, the owner's live permission rules, the audit chain, the configured owners,
  the time zone, the collection prefix, a clock, and `pending_all()` (every built part's pending
  sources, read when called, so C can read A's). I1 adds `reads` (the gateway's governed path
  for a background job's read of his data) and `rain` (Part B's rain hint, read late, for C).
- The integrated review fixes add `HelperPart.paused` (each background reader's "paused" check,
  `jarvis.helpers.paused`: his Helpers tab, the brief and `breach_status` say when a row stops
  it) and `rank` (D9's order, one definition for Part A's pending list and Part C's focus nudge).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, tzinfo
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from jarvis.offline.rules import NoAIRouter

if TYPE_CHECKING:
    from jarvis.billing import Billing
    from jarvis.config import Settings
    from jarvis.helpers.gate import PartSender
    from jarvis.helpers.kinds import PartName
    from jarvis.helpers.paused import PauseSource
    from jarvis.integrations.google import GoogleConnector
    from jarvis.keyring import Keyring
    from jarvis.llm.brains import BrainRegistry
    from jarvis.offline.mode import BrainMode
    from jarvis.privacy.ports import PrivacySource
    from jarvis.storage.docs import Docs
    from jarvis.ticks import TickJob
    from jarvis.tools.audit import AuditTrail
    from jarvis.tools.background import BackgroundReads
    from jarvis.tools.base import Tool
    from jarvis.tools.policy import OwnerRules

Urgency = Literal["overdue", "today", "soon", "later"]
MAX_LABEL = 80
MAX_BRIEF_LINES = 3  # a contributor's lines in the brief (the section holds at most 8 in all)
MAX_LINE = 160
ORDER: dict[str, int] = {"overdue": 0, "today": 1, "soon": 2, "later": 3}
_FAR = datetime.max.replace(tzinfo=UTC)

# NoAIRouter: (text, now in the owner's zone) -> the tool calls to run with no model, or None


@dataclass(frozen=True)
class PendingItem:
    """One thing waiting for the owner (D9). `label` is JARVIS's own words or his own."""

    source: str  # the part's name, or "tasks", "approvals", "calendar"
    label: str
    urgency: Urgency
    due: datetime | None = None
    weight: int = 0  # his own pin raises it; never set from outside content
    ref: str = ""  # an id the source understands (never shown)

    def __post_init__(self) -> None:
        if not self.label.strip() or len(self.label) > MAX_LABEL:
            raise ValueError("a pending item needs a label of at most 80 characters")


def _due_key(item: PendingItem) -> datetime:
    if item.due is None:
        return _FAR
    return item.due if item.due.tzinfo is not None else item.due.replace(tzinfo=UTC)


def rank(items: Sequence[PendingItem]) -> list[PendingItem]:
    """D9's order: overdue, then due today, then urgency (soon, later), then his pin (`weight`),
    then the due date (none last); equal items keep their order."""
    return sorted(items, key=lambda i: (ORDER.get(i.urgency, 9), -i.weight, _due_key(i)))


@runtime_checkable
class PendingSource(Protocol):
    name: str

    async def pending(self, uid: str, now: datetime) -> Sequence[PendingItem]: ...


@runtime_checkable
class BriefContributor(Protocol):
    """Lines for the brief's "Helpers" section: fixed templates, his own words, never AI input."""

    name: str

    async def lines(self, uid: str, tz: tzinfo, day: date) -> Sequence[str]: ...


@dataclass(frozen=True)
class HelperPart:
    name: PartName
    tools: tuple[Tool, ...] = ()
    clock_jobs: tuple[TickJob, ...] = ()
    daily_jobs: tuple[TickJob, ...] = ()
    privacy: tuple[PrivacySource, ...] = ()
    brief: tuple[BriefContributor, ...] = ()
    pending: tuple[PendingSource, ...] = ()
    phrases: tuple[NoAIRouter, ...] = ()
    services: Mapping[str, Any] = field(default_factory=dict)
    ready: str = "not built yet"
    paused: tuple[PauseSource, ...] = ()  # each background reader's "paused" check


@dataclass(frozen=True)
class HelperContext:
    settings: Settings
    docs: Docs
    sender: PartSender
    owners: tuple[str, ...]
    tz: str
    prefix: str
    now: Callable[[], datetime]
    audit: AuditTrail
    pending_all: Callable[[], tuple[PendingSource, ...]]
    permissions: Callable[[], OwnerRules | None]
    keyring: Keyring | None = None
    google: GoogleConnector | None = None
    billing: Billing | None = None
    brains: BrainRegistry | None = None
    brain_mode: BrainMode | None = None
    # I1: the gateway's governed path for a background job's read of his data (Contacts, Gmail,
    # Calendar, Tasks): the gateway's policy and his rows decide, ALLOW only, one kind-only audit
    # line (`jarvis.tools.background`). None: no read at all (fail closed).
    reads: BackgroundReads | None = None
    # I1: Part B's rain hint for Part C's free-time pick, read late: returns an object with
    # `async rain_likely(uid, start, end) -> bool | None` (None, or None back: unknown)
    rain: Callable[[], RainHint | None] | None = None


@runtime_checkable
class RainHint(Protocol):
    """Is rain likely at his place between `start` and `end`? None: unknown (no place, stale)."""

    async def rain_likely(self, uid: str, start: datetime, end: datetime) -> bool | None: ...


__all__ = [
    "MAX_BRIEF_LINES",
    "MAX_LABEL",
    "MAX_LINE",
    "ORDER",
    "BriefContributor",
    "HelperContext",
    "HelperPart",
    "NoAIRouter",
    "PendingItem",
    "PendingSource",
    "RainHint",
    "Urgency",
    "rank",
]
