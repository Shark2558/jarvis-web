# src/jarvis/tools/setup.py
"""Default gateway wiring. Real connectors register here in later slices."""

from __future__ import annotations

from jarvis.config import Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.tools.audit import AuditLog
from jarvis.tools.builtin import InMemoryWorld, builtin_tools
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry


def build_gateway(_: Settings) -> Gateway:
    reg = ToolRegistry()
    for t in builtin_tools(InMemoryWorld()):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
