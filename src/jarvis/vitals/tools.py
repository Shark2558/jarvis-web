# src/jarvis/vitals/tools.py
"""`vitals_show` (R1), `vitals_set_key` and `vitals_delete_key` (R2) -- R4 D2, D12. Names match the
`vitals` / `vitals_change` permission rows (`vitals_*`). Deterministic: no model call. The owner
types a limit and an expiry for a key; the key's VALUE is never accepted or stored (a value that
looks like one is refused). Removing a tracked key is reversible metadata (re-add it), so R2.

Registration is the integrator's: `for t in tools(VitalsDeps(service, settings)): reg.register(t)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.vitals.brief import spoken_summary
from jarvis.vitals.models import ID_PATTERN, Kind, Provider, describe_error
from jarvis.vitals.service import VitalsService
from jarvis.vitals.store import BAD_ID, VitalsFull, VitalsUnavailable, valid_id

SHOWN = "Checked your Vitals board"
SAVED = "Updated a tracked key in Vitals"
REMOVED = "Removed a tracked key from Vitals"
KINDS: tuple[Kind, ...] = ("key", "quota", "billing", "storage", "allowance")
_DATE = {"type": "string", "description": "ISO 8601 date or time, e.g. 2027-01-15"}
MASK_AT = 12  # a card shows at most this many characters of a label, then an ellipsis


@dataclass(frozen=True)
class VitalsDeps:
    service: VitalsService
    settings: Settings


def _date_arg(v: Any, name: str) -> str | None:
    """The raw date text for `Provider` to parse (a naive or date-only value means the end of that
    day in the owner's zone, see `jarvis.vitals.models.aware`)."""
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ValueError(f"{name} must be a date like 2027-01-15")
    return v


def _provider(a: dict[str, Any]) -> Provider:
    """Build the record; the model's own guard refuses anything that looks like a key value."""
    try:
        return Provider(
            id=a["id"],
            label=a["label"],
            kind=a["kind"],
            source="manual",
            limit=a.get("limit"),
            used=a.get("used"),
            unit=a.get("unit") or "",
            reset_at=_date_arg(a.get("reset_at"), "reset_at"),  # type: ignore[arg-type]
            expires_at=_date_arg(a.get("expires_at"), "expires_at"),  # type: ignore[arg-type]
            note=a.get("note") or "",
        )
    except ValidationError as exc:
        raise ValueError(describe_error(exc)) from None


def check_set_key(a: dict[str, Any]) -> None:
    """Gateway stage "propose": runs before any approval card or audit text is made."""
    _provider(a)


def check_delete_key(a: dict[str, Any]) -> None:
    if not isinstance(a.get("id"), str) or not valid_id(a["id"]):
        raise ValueError(BAD_ID)


def summarize_set_key(a: dict[str, Any]) -> str:
    label = str(a.get("label", "a key"))
    shown = label if len(label) <= MASK_AT else label[:MASK_AT] + "…"
    return f"Track {shown} in Vitals"


def summarize_delete_key(a: dict[str, Any]) -> str:
    return f"Stop tracking {str(a.get('id', 'a key'))[:40]} in Vitals"


class VitalsAPI:
    def __init__(self, svc: VitalsService) -> None:
        self._svc = svc

    async def show(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        try:
            board = await self._svc.board_cached(uid)
        except VitalsUnavailable as exc:
            return {"status": "unavailable", "message": str(exc)}
        out = board.to_json()
        if a.get("attention_only") is True:
            keep = {v.provider.id for v in board.attention()}
            out["items"] = [i for i in out["items"] if i["id"] in keep]
        out["spoken"] = spoken_summary(board)  # fixed words: what No-AI mode reads out
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
            check=check_set_key,
            summarize=summarize_set_key,
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
            check=check_delete_key,
            summarize=summarize_delete_key,
            activity_words=REMOVED,
        ),
    ]


__all__ = ["VitalsAPI", "VitalsDeps", "tools"]
