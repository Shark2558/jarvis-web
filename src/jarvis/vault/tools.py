# src/jarvis/vault/tools.py
"""Vault tools (R2 D7): vault_list, vault_expiring (R1, `vault_read` row), vault_set_dates (R2,
`vault_change` row). They return METADATA ONLY: type, whose ("you" / the holder's label), title,
"ends 4821", dates, days left and a state. No tool can read a file, its text or a full number, and
none adds or deletes items (the Vault panel does). Free text (titles, holder labels) is the owner's
own typing but is still fenced ("your vault") and the results vouch, so a vault look-up does not
taint the round. On a spoken or Telegram turn the last 4 is left out and text is masked.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Preview, Tool
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.external import wrap_external
from jarvis.tools.provenance import vouch
from jarvis.tools.spoken import mask_for_speech, speaking_now
from jarvis.vault.models import ID_ITEM, ME, TYPES, Item, VaultIndex, days_left
from jarvis.vault.service import VaultService

SOURCE = "your vault"
SOON_DAYS = 30
MAX_WITHIN = 365
MAX_LISTED = 100
HOLDER_MAX = 40
_DATE = {"type": "string", "description": "ISO date, e.g. 2027-03-03"}


def state_of(item: Item, left: int | None) -> str:
    if not item.dates_confirmed or left is None:
        return "check details" if not item.dates_confirmed else "no expiry date"
    if left < 0:
        return "expired"
    return "expires soon" if left <= SOON_DAYS else "ok"


def _fence(text: str) -> str:
    out = mask_for_speech(text) if speaking_now() else text
    return wrap_external(out, source=SOURCE, limit=120)


def row(index: VaultIndex, item: Item, today: dt.date) -> dict[str, Any]:
    left = days_left(item, today) if item.dates_confirmed else None
    info = TYPES.get(item.type, TYPES["other"])
    spoken = speaking_now()
    return {
        "id": item.id,
        "type": info.label,
        "whose": "you" if item.holder_id == ME else _fence(index.holder_label(item.holder_id)),
        "title": _fence(item.title),
        "ends": None if spoken or not item.last4 else item.last4,
        "expires_on": item.expires_on.isoformat()
        if item.dates_confirmed and item.expires_on
        else None,
        "days_left": left,
        "state": state_of(item, left),
        "files": len(item.files),
    }


def _check_list(a: dict[str, Any]) -> None:
    for key in ("holder", "type"):
        if key in a and not (isinstance(a[key], str) and 0 < len(a[key].strip()) <= HOLDER_MAX):
            raise ValueError(f"{key} must be short text")
    if "type" in a and _type_of(a["type"]) is None:
        raise ValueError("type is a kind of document, such as passport or driving licence")


def _type_of(text: str) -> str | None:
    t = text.strip().casefold().replace("_", " ")
    for key, info in TYPES.items():
        if t in (key.replace("_", " "), info.label.casefold()):
            return key
    return None


def _check_expiring(a: dict[str, Any]) -> None:
    w = a.get("within_days", 90)
    if isinstance(w, bool) or not isinstance(w, int) or not 1 <= w <= MAX_WITHIN:
        raise ValueError(f"within_days must be between 1 and {MAX_WITHIN}")


def _iso(value: Any, name: str) -> dt.date:
    try:
        d = dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        d = None
    if d is None or not 1950 <= d.year <= 2100:
        raise ValueError(f"{name} must be a date like 2027-03-03")
    return d


def _check_set(a: dict[str, Any]) -> None:
    if not isinstance(a.get("item"), str) or not ID_ITEM.fullmatch(a["item"]):
        raise ValueError("item is a vault id from vault_list (v_...)")
    if "issued_on" not in a and "expires_on" not in a:
        raise ValueError("give issued_on, expires_on or both")
    issued = _iso(a["issued_on"], "issued_on") if "issued_on" in a else None
    expires = _iso(a["expires_on"], "expires_on") if "expires_on" in a else None
    if issued and expires and expires < issued:
        raise ValueError("expires_on is before issued_on")


class VaultTools:
    def __init__(self, svc: VaultService) -> None:
        self._svc = svc

    async def list(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        index = await self._svc.index(uid)
        today = self._svc.today()
        items = list(index.live_items())
        if "holder" in a:
            want = a["holder"].strip().casefold()
            ids = {ME} if want in ("you", "me", "mine") else set()
            ids |= {h.id for h in index.holders if h.label.casefold() == want}
            items = [i for i in items if i.holder_id in ids]
        if "type" in a:
            key = _type_of(a["type"])
            items = [i for i in items if i.type == key]
        rows = [row(index, i, today) for i in items[:MAX_LISTED]]
        out: dict[str, Any] = {"documents": rows, "count": len(rows)}
        if not index.live_items():
            out["note"] = "Nothing is in the vault yet. Add documents in the Vault panel."
        return vouch(out, True)

    async def expiring(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        within = a.get("within_days", 90)
        index = await self._svc.index(uid)
        today = self._svc.today()
        due = self._svc.due_of(index, today, within, 30)
        rows = []
        for d in due:
            item = index.item(d.item_id)
            if item is not None:
                rows.append(row(index, item, today))
        return vouch({"within_days": within, "documents": rows, "count": len(rows)}, True)

    async def preview_set(self, a: dict[str, Any]) -> Preview:
        uid = require_tool_context().user_id
        item = await self._svc.get_item(uid, a["item"])
        if item is None:
            raise ValueError("that document isn't in the vault")
        info = TYPES.get(item.type, TYPES["other"])
        whose = "your" if item.holder_id == ME else "a family member's"
        parts = []
        for key, label, old in (
            ("issued_on", "issue date", item.issued_on),
            ("expires_on", "expiry date", item.expires_on),
        ):
            if key in a:
                before = old.isoformat() if old else "not set"
                parts.append(f"{label}: {before} -> {a[key]}")
        return Preview(one_line(f"Change {whose} {info.label.lower()} ({'; '.join(parts)})", 300))

    async def set_dates(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        done = await self._svc.set_dates(
            ctx.user_id, a["item"], issued_on=a.get("issued_on"), expires_on=a.get("expires_on")
        )
        out = {
            "status": "done",
            "id": done["id"],
            "type": done["type_label"],
            "expires_on": done["expires_on"],
            "days_left": done["days_left"],
        }
        return vouch(out, not ctx.outside)


def vault_tools(svc: VaultService) -> list[Tool]:
    api = VaultTools(svc)
    return [
        Tool(
            "vault_list",
            "List the owner's vault documents: type, whose, title, the last 4 characters, expiry "
            "date, days left and a state. Metadata only: files and full ID numbers are never "
            "available. Optional holder ('you' or a family member's name) and type filters.",
            {
                "type": "object",
                "properties": {
                    "holder": {"type": "string", "description": "'you' or a family member"},
                    "type": {"type": "string", "description": "e.g. passport, driving licence"},
                },
            },
            ActionRisk.READ_ONLY,
            api.list,
            agent="vault",
            check=_check_list,
            may_vouch=True,
            activity_words="Looked at your vault list",
        ),
        Tool(
            "vault_expiring",
            "List vault documents that expire within N days (default 90, at most 365) or expired "
            "in the last 30 days. Only documents whose dates the owner confirmed. Metadata only.",
            {
                "type": "object",
                "properties": {"within_days": {"type": "integer", "minimum": 1, "maximum": 365}},
            },
            ActionRisk.READ_ONLY,
            api.expiring,
            agent="vault",
            check=_check_expiring,
            may_vouch=True,
            activity_words="Looked at your vault list",
        ),
        Tool(
            "vault_set_dates",
            "Change the issue and/or expiry date of a vault document when the owner tells you the "
            "new date (e.g. insurance renewed). `item` is the id from vault_list. The owner "
            "approves a card showing old -> new. Cannot add or remove documents.",
            {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "id from vault_list"},
                    "issued_on": _DATE,
                    "expires_on": _DATE,
                },
                "required": ["item"],
            },
            ActionRisk.REVERSIBLE,
            api.set_dates,
            agent="vault",
            check=_check_set,
            preview=api.preview_set,
            may_vouch=True,
            activity_words="Changed a vault date",
        ),
    ]


__all__ = ["VaultTools", "row", "state_of", "vault_tools"]
