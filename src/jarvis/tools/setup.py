"""Default gateway wiring: builtin dev tools, plus the Google tools when an account link is
configured (then the fake calendar/message builtins step aside so the model sees no twins), plus
the memory tools when long-term memory is on, plus web_search / web_read with a Tavily key, plus
the document tools (slice 10 E). The to-do tools (Google Tasks) come with the Google tools: their
scope is optional per owner, so they check it on every call (slice 10 C1). With the Recently
deleted bin (slice 11, `undo`) the calendar and to-do deletes are undo-able and — with Google
linked, whose tools restore — the undo tools (deleted_list / deleted_restore) are registered;
without it every delete stays R3. Slice 12 D5/D6: contacts_search with the Google link, and
whatsapp_draft always. With Drive configured (slice 12 D1, `drive`): the read-only
chosen-folders Drive tools. With JARVIS's own Google API key (slice 12, `media`): Maps and
YouTube search, plus the owner's playlists when the Google link exists."""

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
    from jarvis.documents.service import DocumentService
    from jarvis.drive.service import DriveService
    from jarvis.media.service import MediaServices
    from jarvis.recall.service import MemoryService
    from jarvis.storage.docs import Docs
    from jarvis.tools.task_marks import OutsideTasks
    from jarvis.undo.service import UndoBin
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
) -> Gateway:
    """`marks`: the owner's to-dos JARVIS wrote from outside content (slice 11 D8) on the Docs
    port; give it in production, or the set lives only as long as the process. `drive` (slice 12
    D1): the chosen-folders Drive tools, only when Drive is configured (`JARVIS_DRIVE=on`)."""
    reg = ToolRegistry()
    for t in builtin_tools(InMemoryWorld()):
        if google is not None and t.name in FAKE_TWINS:
            continue
        reg.register(t)
    if google is not None:
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
    _register_people(reg, google)
    if undo is not None and google is not None:  # slice 11: restore needs the Google tools
        from jarvis.undo.tools import undo_tools

        for t in undo_tools(undo):
            reg.register(t)
    if memory is not None:
        from jarvis.recall.tools import memory_tools

        for t in memory_tools(memory):
            reg.register(t)
    if web is not None:  # slice 10 B: only with a Tavily key (jarvis.web.service)
        from jarvis.web.tools import web_tools

        for t in web_tools(web):
            reg.register(t)
    if documents is not None:
        from jarvis.documents.tools import document_tools

        for t in document_tools(documents):
            reg.register(t)
    if drive is not None:  # slice 12 D1: read-only, chosen folders only
        from jarvis.drive.tools import drive_tools

        for t in drive_tools(drive):
            reg.register(t)
    if media is not None:  # slice 12 D2–D4: only with JARVIS's server-side Google API key
        from jarvis.media.tools import youtube_tools
        from jarvis.places.tools import maps_tools

        for t in maps_tools(media.maps) + youtube_tools(media.youtube):
            reg.register(t)
    return Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(approvals),
        audit=audit if audit is not None else AuditLog(),
    )
