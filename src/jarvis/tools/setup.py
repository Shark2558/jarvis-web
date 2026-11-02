"""Default gateway wiring: builtin dev tools, plus the Google tools when an account link is
configured (then the fake calendar/message builtins step aside so the model sees no twins), plus
the memory tools when long-term memory is on, plus web_search / web_read with a Tavily key. The
to-do tools (Google Tasks) come with the Google tools: their scope is optional per owner, so they
check it on every call (slice 10 C1)."""

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
    from jarvis.recall.service import MemoryService
    from jarvis.web.service import WebService

# builtins that stand in for real connectors; dropped once the real ones are registered
FAKE_TWINS = frozenset({"get_calendar", "send_message"})


def build_gateway(
    s: Settings,
    *,
    approvals: ApprovalStore | None = None,
    audit: AuditTrail | None = None,
    google: GoogleConnector | None = None,
    memory: MemoryService | None = None,
    web: WebService | None = None,
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

        for t in calendar_tools(google) + gmail_tools(google):
            reg.register(t)
        for t in tasks_tools(google, default_tz=s.user_timezone):
            reg.register(t)
    if memory is not None:
        from jarvis.recall.tools import memory_tools

        for t in memory_tools(memory):
            reg.register(t)
    if web is not None:  # slice 10 B: only with a Tavily key (jarvis.web.service)
        from jarvis.web.tools import web_tools

        for t in web_tools(web):
            reg.register(t)
    return Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(approvals),
        audit=audit if audit is not None else AuditLog(),
    )
