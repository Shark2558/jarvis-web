"""Default gateway wiring: builtin dev tools, plus the Google tools when an account link is
configured (then the fake calendar/message builtins step aside so the model sees no twins), plus
the memory tools when long-term memory is on, plus web_search / web_read with a Tavily key, plus
the document tools (slice 10 E). The to-do tools (Google Tasks) come with the Google tools: their
scope is optional per owner, so they check it on every call (slice 10 C1). With the Recently
deleted bin (slice 11, `undo`) the calendar and to-do deletes are undo-able and the undo tools
(deleted_list / deleted_restore) are registered (R2 review M2: notes and things restore without
Google; an event or a to-do without Google says Google isn't connected); without it every delete
stays R3. Slice 12 D5/D6: contacts_search with the Google link, and
whatsapp_draft always. With Drive configured (slice 12 D1, `drive`): the read-only
chosen-folders Drive tools. With JARVIS's own Google API key (slice 12, `media`): Maps and
YouTube search, plus the owner's playlists when the Google link exists. R2 (each only when on, i.e.
with the server's token key): the vault's metadata tools, notes and links (kb_*), and where things
are kept (belongings_*). R3 (only with the home on, i.e. the token key and JARVIS_HOME_ENABLED):
home_status / home_devices / home_control, home_arm / home_disarm (which never disarms: it points to
the Home panel's passkey button), camera_history and, with Faces on, faces_list. R4 (`r4`,
`api/r4_wiring.register_r4_tools`): vitals_* and systems_check with the always-on tools (no-AI mode
routes to them), the own-account connectors and scoped people research, each only when its service
exists."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jarvis.config import Settings
from jarvis.core.guardrails import ApprovalStore, ConfirmationGate
from jarvis.integrations.google import GoogleConnector
from jarvis.tools.audit import AuditLog, AuditTrail
from jarvis.tools.builtin import InMemoryWorld, builtin_tools
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from jarvis.activity.store import ActivityStore
    from jarvis.api.r4_wiring import R4Parts
    from jarvis.belongings.service import BelongingsService
    from jarvis.documents.service import DocumentService
    from jarvis.drive.service import DriveService
    from jarvis.home.parts import HomeParts
    from jarvis.kb.service import NotesService
    from jarvis.media.service import MediaServices
    from jarvis.recall.service import MemoryService
    from jarvis.storage.docs import Docs
    from jarvis.tools.base import Tool
    from jarvis.tools.task_marks import OutsideTasks
    from jarvis.undo.service import UndoBin
    from jarvis.vault.service import VaultService
    from jarvis.web.service import WebService

# builtins that stand in for real connectors; dropped once the real ones are registered
# (slice 11 B: the in-memory create_reminder too, now that reminders are real calendar pop-ups)
FAKE_TWINS = frozenset({"get_calendar", "send_message", "create_reminder"})


def _register_people(reg: ToolRegistry, google: GoogleConnector | None) -> None:
    """Slice 12 D5/D6: contacts_search with the Google link (its scope is optional per owner, so
    it checks on every call), and whatsapp_draft always — a typed number needs no Google; with
    the link it can also look a name up in Contacts (one client, one warm-up record)."""
    from jarvis.whatsapp.tools import whatsapp_tools

    contacts = None
    if google is not None:
        from jarvis.contacts.client import ContactsClient
        from jarvis.contacts.tools import contacts_tools

        contacts = ContactsClient(google)
        for t in contacts_tools(contacts):
            reg.register(t)
    for t in whatsapp_tools(contacts):
        reg.register(t)


def _register_google(
    reg: ToolRegistry,
    s: Settings,
    google: GoogleConnector,
    *,
    undo: UndoBin | None,
    marks: OutsideTasks | None,
    docs: Docs | None,
) -> None:
    """Calendar, reminders, Gmail and to-dos (their deletes undo-able with the bin), and R1's
    parcels, mail aloud, groceries and family calendars (on the Docs port)."""
    from jarvis.tools.gmail import gmail_tools
    from jarvis.tools.google_calendar import calendar_tools
    from jarvis.tools.google_tasks import tasks_tools
    from jarvis.tools.reminders import reminder_tools

    tz = s.user_timezone  # slice 11 fix: the reminders' zone when the calendar's can't be read
    for t in calendar_tools(google, undo=undo) + reminder_tools(google, default_tz=tz):
        reg.register(t)
    for t in gmail_tools(google) + tasks_tools(google, default_tz=tz, undo=undo, marks=marks):
        reg.register(t)
    if docs is not None:  # R1 D: parcels, mail aloud, groceries, family calendars
        from jarvis.tools.r1_tools import r1_tools

        for t in r1_tools(google, docs=docs, s=s, marks=marks):
            reg.register(t)


def _register_services(
    reg: ToolRegistry,
    memory: MemoryService | None,
    web: WebService | None,
    documents: DocumentService | None,
    drive: DriveService | None,
    media: MediaServices | None,
) -> None:
    """Long-term memory, web search (a Tavily key), attached files, Drive (chosen folders,
    read-only) and Maps / YouTube (JARVIS's own Google API key): each only when it exists."""
    tools: list[Tool] = []
    if memory is not None:
        from jarvis.recall.tools import memory_tools

        tools += memory_tools(memory)
    if web is not None:  # slice 10 B: only with a Tavily key (jarvis.web.service)
        from jarvis.web.tools import web_tools

        tools += web_tools(web)
    if documents is not None:
        from jarvis.documents.tools import document_tools

        tools += document_tools(documents)
    if drive is not None:  # slice 12 D1: read-only, chosen folders only
        from jarvis.drive.tools import drive_tools

        tools += drive_tools(drive)
    if media is not None:  # slice 12 D2-D4: only with JARVIS's server-side Google API key
        from jarvis.media.tools import youtube_tools
        from jarvis.places.tools import maps_tools

        tools += maps_tools(media.maps) + youtube_tools(media.youtube)
    for t in tools:
        reg.register(t)


def _register_personal(
    reg: ToolRegistry,
    vault: VaultService | None,
    notes: NotesService | None,
    belongings: BelongingsService | None,
) -> None:
    """R2: the owner's vault list (metadata only), notes and things. Telegram refuses all three by
    default (`telegram.rules.PERSONAL_PATTERNS`); offline mode never offers them."""
    if vault is not None:
        from jarvis.vault.tools import vault_tools

        for t in vault_tools(vault):
            reg.register(t)
    if notes is not None:
        from jarvis.kb.tools import notes_tools

        for t in notes_tools(notes):
            reg.register(t)
    if belongings is not None:
        from jarvis.belongings.tools import belongings_tools

        for t in belongings_tools(belongings):
            reg.register(t)


def _register_home(reg: ToolRegistry, home: HomeParts | None) -> None:
    """R3: the home, its alarm, camera history and the people JARVIS recognises. Telegram refuses
    home_devices, camera_* and faces_* by default (`telegram.rules.HOME_PATTERNS`); home_status
    and home_arm stay. A training brain is offered no tools at all and offline mode only
    `llm.fallback.OFFLINE_TOOLS` (none of these), so the private ones reach neither."""
    if home is None:
        return
    from jarvis.camera.tools import camera_tools
    from jarvis.home.tools import home_tools

    cam = home.camera
    tools = home_tools(home.devices, home.status) + camera_tools(cam.alarm, cam.gate, cam.history)
    if home.faces is not None:
        from jarvis.faces.tools import faces_tools

        tools += faces_tools(home.faces)
    for t in tools:
        reg.register(t)


def attach_activity(gw: Gateway, store: ActivityStore, s: Settings) -> None:
    """R1 D7: the Activity recorder hears every call's outcome after its audit entry. Once per
    gateway, so an injected gateway gets it too and a second call changes nothing."""
    from jarvis.activity.recorder import ActivityRecorder

    if any(isinstance(o, ActivityRecorder) for o in gw.observers):
        return
    gw.observers.append(ActivityRecorder(store, gw.registry, timezone=s.user_timezone))


def build_gateway(
    s: Settings,
    *,
    approvals: ApprovalStore | None = None,
    audit: AuditTrail | None = None,
    google: GoogleConnector | None = None,
    memory: MemoryService | None = None,
    web: WebService | None = None,
    documents: DocumentService | None = None,
    undo: UndoBin | None = None,
    marks: OutsideTasks | None = None,
    drive: DriveService | None = None,
    media: MediaServices | None = None,
    docs: Docs | None = None,
    vault: VaultService | None = None,
    notes: NotesService | None = None,
    belongings: BelongingsService | None = None,
    home: HomeParts | None = None,
    r4: R4Parts | None = None,
) -> Gateway:
    """`marks`: the owner's to-dos JARVIS wrote from outside content (slice 11 D8) on the Docs
    port; give it in production, or the set lives only as long as the process. `drive` (slice 12
    D1): the chosen-folders Drive tools, only when Drive is configured (`JARVIS_DRIVE=on`)."""
    reg = ToolRegistry()
    for t in builtin_tools(InMemoryWorld()):
        if google is not None and t.name in FAKE_TWINS:
            continue
        reg.register(t)
    if r4 is not None:  # R4 W6: vitals_show / systems_check are always-on (no-AI mode needs them)
        from jarvis.api.r4_wiring import register_r4_tools

        register_r4_tools(reg, r4)
    if google is not None:
        _register_google(reg, s, google, undo=undo, marks=marks, docs=docs)
    _register_people(reg, google)
    if undo is not None:  # R2 review M2: notes and things are undo-able without Google too
        from jarvis.undo.tools import undo_tools

        for t in undo_tools(undo):
            reg.register(t)
    _register_services(reg, memory, web, documents, drive, media)
    _register_personal(reg, vault, notes, belongings)
    _register_home(reg, home)
    return Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(approvals),
        audit=audit if audit is not None else AuditLog(),
    )
