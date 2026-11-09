# src/jarvis/privacy/existing.py
"""The existing categories, assembled for the privacy dashboard (R2 D14, R5 D16).

`ExistingParts` says what is switched on on this server; `existing_sources` builds the matching
sources in the order the panel shows them. Split out of `sources.py` (no behaviour change): this
module may import `voice.privacy`, which itself builds on `sources.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from jarvis.billing.meter import UsageMeter
from jarvis.brief.store import BriefStore
from jarvis.core.guardrails import ConfirmationGate
from jarvis.documents.service import DocumentService
from jarvis.drive.roots import RootsStore
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import TokenStore
from jarvis.permissions.service import PermissionsService
from jarvis.places.store import MapsPlaces
from jarvis.privacy.sources import (
    CallbackSource,
    approvals_source,
    audit_source,
    briefs_source,
    conversations_source,
    counters_source,
    deleted_source,
    drive_source,
    faces_source,
    google_source,
    marks_source,
    memory_source,
    passkeys_source,
    places_source,
    settings_source,
    spend_source,
)
from jarvis.recall.service import MemoryService
from jarvis.storage.sessions import DocSessionStore
from jarvis.tools.audit import AuditTrail
from jarvis.tools.task_marks import OutsideTasks
from jarvis.undo.service import UndoBin
from jarvis.voice.privacy import voice_phrases_source
from jarvis.voice.settings import VoiceSettingsStore


@dataclass(frozen=True)
class ExistingParts:
    """What the existing categories are built from (a part that is None is left out: the feature is
    switched off on this server, so there is nothing of it to show)."""

    memory: MemoryService | None = None
    sessions: DocSessionStore | None = None
    documents: DocumentService | None = None
    undo: UndoBin | None = None
    tokens: TokenStore | None = None
    google: GoogleConnector | None = None
    roots: RootsStore | None = None
    places: MapsPlaces | None = None
    briefs: BriefStore | None = None
    meter: UsageMeter | None = None
    gate: ConfirmationGate | None = None
    permissions: PermissionsService | None = None
    audit: AuditTrail | None = None
    marks: OutsideTasks | None = None
    voice: VoiceSettingsStore | None = None  # R5 D16: the words to recognise
    today: Callable[[], date] = lambda: datetime.now(UTC).date()  # noqa: E731
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def existing_sources(p: ExistingParts) -> list[CallbackSource]:
    """The existing categories in the order the panel shows them, then the faces placeholder."""
    out: list[CallbackSource | None] = [
        memory_source(p.memory) if p.memory else None,
        conversations_source(p.sessions, p.documents) if p.sessions else None,
        deleted_source(p.undo) if p.undo else None,
        google_source(p.tokens, p.google) if p.tokens else None,
        drive_source(p.roots) if p.roots else None,
        places_source(p.places) if p.places else None,
        briefs_source(p.briefs, p.today) if p.briefs else None,
        settings_source(p.briefs, p.memory) if p.briefs else None,
        voice_phrases_source(p.voice) if p.voice else None,
        spend_source(p.meter, p.clock) if p.meter else None,
        approvals_source(p.gate) if p.gate else None,
        passkeys_source(p.permissions) if p.permissions else None,
        audit_source(p.audit) if p.audit else None,
        marks_source(p.marks) if p.marks else None,
        counters_source(),
        faces_source(),
    ]
    return [s for s in out if s is not None]


__all__ = ["ExistingParts", "existing_sources"]
