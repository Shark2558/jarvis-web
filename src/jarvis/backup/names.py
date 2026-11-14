# src/jarvis/backup/names.py
"""Part A's two tool names (`hardening.ports.TOOL_FAMILIES["backup"]`), in a module with no
imports of its own, so `core/guardrails.py` can name the drill card at its top
(`NO_BULK_TOOLS`: never part of Approve all, INTEGRATION-A "Needs I1" #1) without an import
cycle: `backup.tools` itself imports `core.guardrails`.
"""

from __future__ import annotations

SHOW = "vitals_backups"
START = "vitals_drill_start"

__all__ = ["SHOW", "START"]
