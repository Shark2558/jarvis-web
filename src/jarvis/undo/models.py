# src/jarvis/undo/models.py
"""What the "Recently deleted" bin keeps (slice 11 D1; Layer 7 data model).

A `DeletedItem` is one undo-able delete: the owner's event or to-do as it was just before JARVIS
deleted it (`snapshot`, the fields a restore needs), its title as one clean line (often someone
else's words: fenced before it reaches the model), when it was deleted and when the copy goes
(+30 days). `restored` / `restored_id` make a restore idempotent; `restoring_since` is the claim a
restore holds while it recreates the item, so two clicks never make two copies. `owner_authored`
(captured at delete time, never from a client) records whether the item was the owner's own words.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.tools.provenance import all_owner_authored as provenance_all

RETENTION_DAYS = 30
TITLE_LIMIT = 200
UNDO_ID = re.compile(r"del_[0-9a-f]{20}")

# R2 D8: vault documents, notes and things are soft-deleted inside their own encrypted stores; the
# bin entry holds only `snapshot = {ref: <item id>}` under a generic title. Their restore clears the
# tombstone in place (same id, so no "new copy" wording) and their purge hard-deletes the item.
Kind = Literal["event", "task", "vault_item", "note", "thing"]
KINDS: tuple[Kind, ...] = ("event", "task", "vault_item", "note", "thing")
KIND_WORDS: dict[str, str] = {
    "event": "event",
    "task": "to-do",
    "vault_item": "vault document",
    "note": "note",
    "thing": "thing",
}
IN_PLACE_KINDS: frozenset[str] = frozenset({"vault_item", "note", "thing"})
# "Remove now" for these can't be brought back: the caller asks for a passkey (purpose
# `privacy_delete`, target = the bin id) where passkeys are in force.
PASSKEY_PURGE_KINDS: frozenset[str] = frozenset({"vault_item", "note", "thing"})
# The line an approval card for an undo-able delete carries (a tainted round, the 11th delete).
CARD_LINE = f"Kept in Recently deleted for {RETENTION_DAYS} days: you can undo it."


class DeletedItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    user_id: str
    kind: Kind
    title: str
    snapshot: dict[str, Any] = Field(default_factory=dict)
    deleted_at: datetime
    expires_at: datetime
    restored: bool = False
    restored_at: datetime | None = None
    restored_id: str | None = None
    restoring_since: datetime | None = None
    # plan D8: the item was the owner's own words when it was deleted (calendar: organised and
    # created by the owner, nobody else on it, not from Gmail; to-do: no links, not assigned).
    # A Recently deleted listing whose every item is owner-authored can then be trusted.
    owner_authored: bool = False
    # slice 11 fix: where the delete came from — the conversation and the request's trace id
    # (the audit entry of the delete carries the same trace id in the logs)
    session_id: str | None = None
    trace_id: str | None = None

    def expired(self, now: datetime) -> bool:
        return now >= self.expires_at


def all_owner_authored(items: list[DeletedItem]) -> bool:
    """Plan D8: a listing can be trusted only when every item in it is the owner's own words —
    the one rule (`provenance.all_owner_authored`) over each item's recorded verdict."""
    return provenance_all(items, lambda i: i.owner_authored)


class RestoreStatus(StrEnum):
    RESTORED = "restored"
    ALREADY_RESTORED = "already_restored"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    STILL_THERE = "still_there"  # the original was never deleted: no copy is made


class RestoreOutcome(BaseModel):
    """What a restore did, in plain words. `title` is one clean line (not fenced): the console
    shows it with textContent; the tool fences it before the model sees it."""

    model_config = ConfigDict(frozen=True)

    status: RestoreStatus
    message: str
    undo_id: str = ""
    kind: Kind | None = None
    title: str = ""
    new_id: str | None = None
    note: str = ""
    owner_authored: bool = False  # plan D8: the item's recorded verdict (its title is his words)


class UndoRef(BaseModel):
    """A delete in a reply that can be undone (ChatResponse.undo → the console's Undo chip)."""

    model_config = ConfigDict(frozen=True)

    undo_id: str
    kind: Kind

    @classmethod
    def from_result(cls, result: Any) -> UndoRef | None:
        """Read from a delete tool's result; anything odd is ignored, never guessed."""
        if not isinstance(result, dict):
            return None
        uid, kind = result.get("undo_id"), result.get("kind")
        if not isinstance(uid, str) or not UNDO_ID.fullmatch(uid) or kind not in KINDS:
            return None
        return cls(undo_id=uid, kind=kind)


class DeletedView(BaseModel):
    """GET /v1/deleted: one row of "Recently deleted"."""

    id: str
    kind: Kind
    title: str
    deleted_at: datetime
    expires_at: datetime
    restored: bool

    @classmethod
    def of(cls, item: DeletedItem) -> DeletedView:
        return cls(
            id=item.id,
            kind=item.kind,
            title=item.title,
            deleted_at=item.deleted_at,
            expires_at=item.expires_at,
            restored=item.restored,
        )


class DeletedList(BaseModel):
    items: list[DeletedView]
    kept_days: int = RETENTION_DAYS
    # slice 11 fix: False on a server without persistent storage (no bin: deletes stay R3)
    available: bool = True


__all__ = [
    "CARD_LINE",
    "IN_PLACE_KINDS",
    "KINDS",
    "KIND_WORDS",
    "PASSKEY_PURGE_KINDS",
    "RETENTION_DAYS",
    "TITLE_LIMIT",
    "UNDO_ID",
    "DeletedItem",
    "DeletedList",
    "DeletedView",
    "Kind",
    "RestoreOutcome",
    "RestoreStatus",
    "UndoRef",
    "all_owner_authored",
]
