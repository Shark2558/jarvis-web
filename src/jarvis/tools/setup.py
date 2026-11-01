"""Default gateway wiring: builtin dev tools, plus the Google tools when an account link is
configured (then the fake calendar/message builtins step aside so the model sees no twins), plus
the memory tools when long-term memory is on, plus the document tools (slice 10 E)."""

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

# builtins that stand in for real connectors; dropped once the real ones are registered
FAKE_TWINS = frozenset({"get_calendar", "send_message"})


def build_gateway(
    _: Settings,
    *,
    approvals: ApprovalStore | None = None,
    audit: AuditTrail | None = None,
    google: GoogleConnector | None = None,
    memory: MemoryService | None = None,
    documents: DocumentService | None = None,
) -> Gateway:
    reg = ToolRegistry()
    for t in builtin_tools(InMemoryWorld()):
        if google is not None and t.name in FAKE_TWINS:
            continue
        reg.register(t)
    if google is not None:
        from jarvis.tools.gmail import gmail_tools
        from jarvis.tools.google_calendar import calendar_tools

        for t in calendar_tools(google) + gmail_tools(google):
            reg.register(t)
    if memory is not None:
        from jarvis.recall.tools import memory_tools

        for t in memory_tools(memory):
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
