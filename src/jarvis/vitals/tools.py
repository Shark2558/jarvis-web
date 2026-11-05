# src/jarvis/vitals/tools.py
"""`vitals_show` (R1), `vitals_set_key` and `vitals_delete_key` (R2) -- R4 D2, D12. Names match the
`vitals` / `vitals_change` permission rows (`vitals_*`). Deterministic: no model call. The owner
types a limit and an expiry for a key; the key's VALUE is never accepted or stored (a value that
looks like one is refused). Removing a tracked key is reversible metadata (re-add it), so R2.

Registration is the integrator's: `for t in tools(VitalsDeps(service, settings)): reg.register(t)`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.vitals.models import ID_PATTERN, Kind, Provider
from jarvis.vitals.service import VitalsService
from jarvis.vitals.store import VitalsFull, VitalsUnavailable

SHOWN = "Checked your Vitals board"
SAVED = "Updated a tracked key in Vitals"
REMOVED = "Removed a tracked key from Vitals"
SECRET_LOOKING = re.compile(r"[A-Za-z0-9_\-]{32,}")
NEVER_PASTE = "Never paste a key's value here: type only its name, limit and expiry."
KINDS: tuple[Kind, ...] = ("key", "quota", "billing", "storage", "allowance")
_DATE = {"type": "string", "description": "ISO 8601 date or time, e.g. 2027-01-15"}


@dataclass(frozen=True)
class VitalsDeps:
    service: VitalsService
    settings: Settings


def _when(v: Any, name: str) -> datetime | None:
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ValueError(f"{name} must be a date like 2027-01-15")
    try:
        d = (
            datetime.combine(date.fromisoformat(v), datetime.min.time())
            if len(v) == 10
            else (datetime.fromisoformat(v))
        )
    except ValueError:
        raise ValueError(f"{name} must be a date like 2027-01-15") from None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _provider(a: dict[str, Any]) -> Provider:
    for field in ("label", "note", "unit"):
        if SECRET_LOOKING.search(str(a.get(field) or "")):
            raise ValueError(NEVER_PASTE)
    try:
        return Provider(
            id=a["id"],
            label=a["label"],
            kind=a["kind"],
            source="manual",
            limit=a.get("limit"),
            used=a.get("used"),
            unit=a.get("unit") or "",
            reset_at=_when(a.get("reset_at"), "reset_at"),
            expires_at=_when(a.get("expires_at"), "expires_at"),
            note=a.get("note") or "",
        )
    except ValidationError as exc:
        fields = ", ".join(sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]}))
        raise ValueError(f"Those values aren't valid ({fields}).") from None


class VitalsAPI:
    def __init__(self, svc: VitalsService) -> None:
        self._svc = svc

    async def show(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        try:
            board = await self._svc.board(uid)
        except VitalsUnavailable as exc:
            return {"status": "unavailable", "message": str(exc)}
        out = board.to_json()
        if a.get("attention_only") is True:
            keep = {v.provider.id for v in board.attention()}
            out["items"] = [i for i in out["items"] if i["id"] in keep]
        return out

    async def set_key(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        try:
            p = _provider(a)
            await self._svc.set_key(uid, p)
        except (ValueError, VitalsFull) as exc:
            return {"status": "rejected", "message": str(exc)}
        except VitalsUnavailable as exc:
            return {"status": "unavailable", "message": str(exc)}
        return {"saved": p.id, "label": p.label}

    async def delete_key(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        try:
            removed = await self._svc.delete_key(uid, str(a.get("id", "")))
        except (ValueError, VitalsUnavailable) as exc:
            return {"status": "unavailable", "message": str(exc)}
        return {"removed": removed}


def _id_prop() -> dict[str, Any]:
    return {"type": "string", "pattern": ID_PATTERN, "description": "short id, e.g. brave-search"}


def tools(deps: VitalsDeps) -> list[Tool]:
    if not deps.settings.vitals_enabled:
        return []
    api = VitalsAPI(deps.service)
    return [
        Tool(
            "vitals_show",
            "Show the Vitals board: every tracked key, quota, bill and allowance with its used / "
            "limit, reset, expiry and status (ok, amber, red, unknown), plus this month's AI "
            "spend in rupees. attention_only=true lists only amber and red items. Read-only.",
            {
                "type": "object",
                "properties": {"attention_only": {"type": "boolean"}},
            },
            ActionRisk.READ_ONLY,
            api.show,
            agent="vitals",
            activity_words=SHOWN,
        ),
        Tool(
            "vitals_set_key",
            "Add or edit a tracked key in Vitals: its name, limit, usage, reset and expiry. "
            "Never put the key's value anywhere: it is refused. Replaces a record with the "
            "same id.",
            {
                "type": "object",
                "properties": {
                    "id": _id_prop(),
                    "label": {"type": "string", "maxLength": 80},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "limit": {"type": "number", "minimum": 0},
                    "used": {"type": "number", "minimum": 0},
                    "unit": {"type": "string", "maxLength": 20},
                    "reset_at": _DATE,
                    "expires_at": _DATE,
                    "note": {"type": "string", "maxLength": 300},
                },
                "required": ["id", "label", "kind"],
            },
            ActionRisk.REVERSIBLE,
            api.set_key,
            agent="vitals",
            summarize=lambda a: f"Track {str(a.get('label', 'a key'))[:80]} in Vitals",
            activity_words=SAVED,
        ),
        Tool(
            "vitals_delete_key",
            "Stop tracking a key in Vitals (removes the record; add it again any time). Built-in "
            "items such as AI spend can't be removed.",
            {"type": "object", "properties": {"id": _id_prop()}, "required": ["id"]},
            ActionRisk.REVERSIBLE,
            api.delete_key,
            agent="vitals",
            summarize=lambda a: f"Stop tracking {str(a.get('id', 'a key'))[:40]} in Vitals",
            activity_words=REMOVED,
        ),
    ]


__all__ = ["VitalsAPI", "VitalsDeps", "tools"]
