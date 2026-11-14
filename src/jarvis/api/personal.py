# src/jarvis/api/personal.py
"""R2 I1: the owner's personal data on the app (Layer 7 data, Layer 8 nudges; plan
docs/plans/r2-memory-vault.md "Workstreams -> I1"). Kept out of `api/app.py` so that file stays a
short list of named steps.

- `wire_personal` (after Drive, before the gateway): the vault (its extractor is the documents'
  ONE sandboxed slot, `DocumentService.extract`, never an in-process PDF parser), notes and links,
  things, the DigiLocker inbox (Drive tools never read the picked folder, vault on or off), and the
  Recently deleted restorers + purgers for the three new kinds. Each is OFF (None, with plain words)
  without the server's token key: nothing of the owner's is ever stored in clear.
- `personal_tick_jobs`: vault reminders, the DigiLocker import and two sweeps, each a `TickJob`
  with a unique name that is none of the tick's own sweeps.
- `wire_privacy` (after the gateway and the brief): the privacy dashboard's registry in panel
  order: existing -> R1 -> vault -> DigiLocker folder -> notes -> things -> R3 (home, home feed,
  camera at home, alert choices, browsers; `api/home_wiring.py`) -> faces (R3 C, last).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from jarvis.api.home_wiring import home_privacy_sources
from jarvis.api.r6_wiring import r6_privacy_sources
from jarvis.api.r7_wiring import mobile_privacy_sources
from jarvis.api.r11_1_wiring import fix_privacy_sources
from jarvis.api.r11_wiring import r11_privacy_sources
from jarvis.api.r14_wiring import r14_privacy_sources
from jarvis.api.rows import DRIVE_TOOL
from jarvis.belongings.privacy import BelongingsPrivacy
from jarvis.belongings.service import BelongingsService
from jarvis.belongings.store import BelongingsStore
from jarvis.brief.store import BriefStore
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.family.store import FamilyStore
from jarvis.groceries.store import GroceryStore
from jarvis.kb.privacy import NotesPrivacy
from jarvis.kb.service import NOT_CONFIGURED, build_notes_service
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.privacy.existing import ExistingParts, existing_sources
from jarvis.privacy.ports import PrivacyRegistry, PrivacySource
from jarvis.privacy.service import PrivacyService
from jarvis.privacy.sources_r1 import R1Parts, r1_sources
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail
from jarvis.tools.policy import Effect, Policy
from jarvis.undo.service import UndoBin
from jarvis.vault.build import VaultStack, build_vault
from jarvis.vault.service import VaultService
from jarvis.vault_inbox.job import InboxJob
from jarvis.vault_inbox.privacy import inbox_source
from jarvis.vault_inbox.service import InboxService
from jarvis.vault_inbox.store import InboxStore

log = get_logger(__name__)

NOTES_OFF = "Notes are switched off on this server."
NO_KEY_NOTE = (  # the token key's own warning names the setting (integrations.google)
    "No encryption key on this server: the vault, notes and things are OFF (never stored in clear)"
)
# The tick's own sweep names (api/brief.py): a job may never take one of them
RESERVED_JOB_NAMES = frozenset(
    {"memory", "documents", "undo", "outside_tasks", "permissions", "telegram", "activity", "web"}
)
SWEEP_BUDGET_S = 30.0


# ---- the features ---------------------------------------------------------------------------


def wire_personal(app: FastAPI, s: Settings, docs: Docs) -> None:
    """The vault, notes, things and the DigiLocker inbox on `app.state` (None when off)."""
    ring = Keyring.from_settings(s)
    if ring is None and (s.vault_enabled or s.notes_enabled or s.belongings_enabled):
        log.warning(NO_KEY_NOTE)
    undo: UndoBin | None = app.state.undo
    store = BriefStore(docs, prefix=s.firestore_prefix)
    vault = build_vault(
        s,
        docs,
        extract=app.state.documents.extract,  # the one sandboxed extraction slot (slice 10 E)
        undo=undo,
        alerts=app.state.alerts,
        brief_time=_brief_time(store),
        zone_for=_zone_for(store, s.user_timezone),
    )
    app.state.vault_stack = vault
    app.state.vault = vault.service if vault else None
    app.state.vault_unlock = vault.unlock if vault else None
    app.state.vault_reminders = vault.reminders if vault else None
    app.state.notes = build_notes_service(s, docs, web=app.state.web, undo=undo)
    app.state.notes_reason = NOT_CONFIGURED if s.notes_enabled else NOTES_OFF
    app.state.belongings = (
        BelongingsService(BelongingsStore(docs, ring, prefix=s.firestore_prefix), undo)
        if ring is not None and s.belongings_enabled
        else None
    )
    app.state.vault_inbox = _wire_inbox(app, s, docs)
    if undo is not None:
        register_undo(undo, vault, app.state.notes, app.state.belongings)


def register_undo(
    undo: UndoBin,
    vault: VaultStack | None,
    notes: Any,
    belongings: BelongingsService | None,
) -> None:
    """Restore in place and, when the bin entry expires or the owner presses Remove now, purge
    for good (the purgers shred only while the item is still tombstoned by that entry)."""
    if vault is not None:
        undo.register("vault_item", vault.restorer, vault.purger)
    if notes is not None:
        undo.register("note", notes, notes)
    if belongings is not None:
        undo.register("thing", belongings, belongings)


def _wire_inbox(app: FastAPI, s: Settings, docs: Docs) -> InboxService | None:
    """D9: with Drive configured, the inbox id is ALWAYS denied to the Drive tools (a folder
    picked while the vault was on stays unreadable if it is later off); the import needs the
    vault."""
    drive = app.state.drive
    if drive is None:
        return None
    store = InboxStore(docs, prefix=s.firestore_prefix)
    if drive.inbox is None:
        drive.inbox = store.folder_id
    vault: VaultService | None = app.state.vault
    if vault is None:
        return None
    return InboxService(drive, store, vault, review_count=_waiting_review(vault))


def _waiting_review(vault: VaultService) -> Callable[[str], Awaitable[int]]:
    """DigiLocker imports still under "Check details" (dates not confirmed)."""

    async def count(uid: str) -> int:
        index = await vault.index(uid)
        return sum(
            1 for i in index.live_items() if i.source.kind == "digilocker" and not i.dates_confirmed
        )

    return count


def _brief_time(store: BriefStore) -> Callable[[str], Awaitable[dt.time | None]]:
    """The owner's brief time while the brief is on (else None: 09:00)."""

    async def at(uid: str) -> dt.time | None:
        st = await store.get_settings(uid)
        return st.at if st.enabled else None

    return at


def _zone_for(store: BriefStore, default_tz: str) -> Callable[[str], Awaitable[ZoneInfo]]:
    async def zone(uid: str) -> ZoneInfo:
        st = await store.get_settings(uid)
        try:
            return ZoneInfo(st.tz or default_tz)
        except (KeyError, ValueError):  # an odd cached zone: the server's
            return ZoneInfo(default_tz)

    return zone


# ---- tick jobs --------------------------------------------------------------------------------


@dataclass  # not frozen: `TickJob` declares name / budget_s as plain attributes
class OwnerSweep:
    """A per-owner sweep as a tick job; one owner's failure stops no one (counts only)."""

    name: str
    sweep: Callable[[str], Awaitable[int]]
    budget_s: float = SWEEP_BUDGET_S

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        swept = failed = 0
        for uid in owners:
            try:
                swept += int(await self.sweep(uid))
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning(
                    "sweep failed for an owner",
                    extra={"job": self.name, "error": type(exc).__name__},
                )
                failed += 1
        return {"owners": len(owners), "swept": swept, "failed": failed}


def _drive_allowed(app: FastAPI) -> Callable[[str], Awaitable[bool]]:
    """No DigiLocker import while the owner's Drive row is Never (or can't be read)."""

    async def allowed(uid: str) -> bool:
        perms = getattr(app.state, "permissions", None)
        if perms is None:
            return True
        try:
            rules = await perms.rules_for(uid)
        except Exception as exc:  # noqa: BLE001 - fail closed: no import this tick
            log.warning(
                "permissions unreadable for the inbox job", extra={"error": type(exc).__name__}
            )
            return False
        return Policy(rules).decide(DRIVE_TOOL, ActionRisk.READ_ONLY, {}) is not Effect.DENY

    return allowed


def personal_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    jobs: list[TickJob] = []
    vault: VaultStack | None = app.state.vault_stack
    if vault is not None:
        jobs.append(vault.reminders)
        jobs.append(OwnerSweep("vault_chunks", vault.service.store.sweep))
        jobs.append(OwnerSweep("vault_unlocks", vault.unlock.sweep))
    inbox: InboxService | None = app.state.vault_inbox
    if inbox is not None:
        jobs.append(InboxJob(inbox, allowed=_drive_allowed(app)))
    names = [j.name for j in jobs]
    if len(set(names)) != len(names) or RESERVED_JOB_NAMES & set(names):
        raise RuntimeError("tick job names must be unique and not a tick sweep's")
    return tuple(jobs)


# ---- the privacy dashboard ----------------------------------------------------------------------


def privacy_sources(
    app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail
) -> list[PrivacySource]:
    """Every category in panel order; a feature that is off here is left out."""
    st = app.state
    google, gw, prefix = st.google, st.gateway, s.firestore_prefix
    existing = existing_sources(
        ExistingParts(
            memory=st.memory,
            sessions=cast(Any, st.store),  # any SessionStore: list_for_user / get / delete
            documents=st.documents,
            undo=st.undo,
            tokens=google.store if google is not None else None,
            google=google,
            roots=st.drive.roots if st.drive is not None else None,
            places=st.media.places if st.media is not None else None,
            briefs=BriefStore(docs, prefix=prefix),
            meter=getattr(st.billing, "meter", None),
            gate=gw.gate if gw is not None else None,
            permissions=st.permissions,
            audit=audit,
            marks=st.outside_tasks,
            voice=st.voice.store,  # R5 D16: the words to recognise
        )
    )
    r1 = r1_sources(
        R1Parts(
            telegram=st.telegram.store if st.telegram is not None else None,
            activity=st.activity_store,
            offline=st.offline.store if st.offline is not None else None,
            groceries=GroceryStore(docs, prefix=prefix) if google is not None else None,
            family=FamilyStore(docs, prefix=prefix) if st.family is not None else None,
        )
    )
    r2: list[PrivacySource | None] = [
        st.vault_stack.privacy if st.vault_stack is not None else None,
        inbox_source(st.vault_inbox) if st.vault_inbox is not None else None,
        NotesPrivacy(st.notes) if st.notes is not None else None,
        BelongingsPrivacy(st.belongings) if st.belongings is not None else None,
    ]
    return [
        *(x for x in existing if x.id != "faces"),
        *r1,
        *(x for x in r2 if x is not None),
        *r6_privacy_sources(app),  # R6 D16: the sealed book, its sessions, Book settings
        *r11_privacy_sources(app),  # R11 D17: the helpers' rows (I0's nudge row, then A-D)
        *fix_privacy_sources(app),  # R11.1: the four parts' rows (series, photo imports, ...)
        *mobile_privacy_sources(app),  # R7: linked phones, watch days, SOS, camera results
        *r14_privacy_sources(app),  # R14: backups (A), the token ledger (C), self-health (B)
        *home_privacy_sources(app),  # R3 I1: C's FacesPrivacy replaces the placeholder, last
    ]


def wire_privacy(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> None:
    gw = app.state.gateway
    trail = gw.audit if gw is not None else audit
    registry = PrivacyRegistry()
    for source in privacy_sources(app, s, docs, trail):
        registry.register(source)
    app.state.privacy = PrivacyService(registry, permissions=app.state.permissions, audit=trail)


__all__ = [
    "NOTES_OFF",
    "RESERVED_JOB_NAMES",
    "OwnerSweep",
    "personal_tick_jobs",
    "privacy_sources",
    "register_undo",
    "wire_personal",
    "wire_privacy",
]
