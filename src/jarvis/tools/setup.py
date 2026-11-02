"""Default gateway wiring: builtin dev tools, plus the Google tools when an account link is
configured (then the fake calendar/message builtins step aside so the model sees no twins), plus
the memory tools when long-term memory is on, plus web_search / web_read with a Tavily key, plus
the document tools (slice 10 E). The to-do tools (Google Tasks) come with the Google tools: their
scope is optional per owner, so they check it on every call (slice 10 C1). With the Recently
deleted bin (slice 11, `undo`) the calendar and to-do deletes are undo-able and the undo tools
(deleted_list / deleted_restore) are registered; without it every delete stays R3."""

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
    from jarvis.documents.service import DocumentService
    from jarvis.recall.service import MemoryService
    from jarvis.undo.service import UndoBin
    from jarvis.web.service import WebService

# builtins that stand in for real connectors; dropped once the real ones are registered
# (slice 11 B: the in-memory create_reminder too, now that reminders are real calendar pop-ups)
FAKE_TWINS = frozenset({"get_calendar", "send_message", "create_reminder"})


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
) -> Gateway:
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

        for t in calendar_tools(google, undo=undo) + reminder_tools(google) + gmail_tools(google):
            reg.register(t)
        for t in tasks_tools(google, default_tz=s.user_timezone, undo=undo):
            reg.register(t)
    if undo is not None:  # slice 11: Recently deleted (restore needs the Google tools above)
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
    return Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(approvals),
        audit=audit if audit is not None else AuditLog(),
    )
