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
  sources, read when called, so C can read A's).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from jarvis.offline.rules import NoAIRouter

if TYPE_CHECKING:
    from jarvis.billing import Billing
    from jarvis.config import Settings
    from jarvis.helpers.gate import PartSender
    from jarvis.helpers.kinds import PartName
    from jarvis.integrations.google import GoogleConnector
    from jarvis.keyring import Keyring
    from jarvis.llm.brains import BrainRegistry
    from jarvis.offline.mode import BrainMode
    from jarvis.privacy.ports import PrivacySource
    from jarvis.storage.docs import Docs
    from jarvis.ticks import TickJob
    from jarvis.tools.audit import AuditTrail
    from jarvis.tools.base import Tool
    from jarvis.tools.policy import OwnerRules

Urgency = Literal["overdue", "today", "soon", "later"]
MAX_LABEL = 80
MAX_BRIEF_LINES = 3  # a contributor's lines in the brief (the section holds at most 8 in all)
MAX_LINE = 160

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


__all__ = [
    "MAX_BRIEF_LINES",
    "MAX_LABEL",
    "MAX_LINE",
    "BriefContributor",
    "HelperContext",
    "HelperPart",
    "NoAIRouter",
    "PendingItem",
    "PendingSource",
    "Urgency",
]
