# src/jarvis/telegram/models.py
"""Telegram updates, parsed tolerantly (unknown fields ignored, anything malformed is None), and
the stored link between the owner and their Telegram account (R1 data model)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class User(_In):
    id: int
    is_bot: bool = False


class Chat(_In):
    id: int
    type: str = ""


class Message(_In):
    message_id: int = 0
    sender: User | None = Field(default=None, alias="from")
    chat: Chat
    text: str | None = None
    # Someone else's words typed by the owner's own thumb: a forwarded message, one sent via a bot,
    # a reply to an external message. Parsed only to be recognised (review: outside content).
    forward_origin: Any = None
    forward_from: Any = None
    forward_from_chat: Any = None
    forward_sender_name: Any = None
    forward_date: Any = None
    via_bot: Any = None
    external_reply: Any = None

    @property
    def outside_content(self) -> bool:
        """True when this text may be someone else's: never owner instructions."""
        return any(
            v is not None
            for v in (
                self.forward_origin,
                self.forward_from,
                self.forward_from_chat,
                self.forward_sender_name,
                self.forward_date,
                self.via_bot,
                self.external_reply,
            )
        )


class CallbackQuery(_In):
    id: str
    sender: User = Field(alias="from")
    message: Message | None = None
    data: str | None = None


class Update(_In):
    update_id: int
    message: Message | None = None
    callback_query: CallbackQuery | None = None


def parse_update(raw: bytes | str | dict[str, Any] | None) -> Update | None:
    """The update, or None for anything that is not a well-formed one. Never raises."""
    try:
        data = json.loads(raw) if isinstance(raw, bytes | str) else raw
        if not isinstance(data, dict):
            return None
        return Update.model_validate(data)
    except (ValueError, ValidationError, RecursionError):
        return None


class AlertToggles(BaseModel):
    approval_waiting: bool = True
    offline: bool = True
    brief_ready: bool = False
    vault_expiry: bool = False  # R2 D5: a vault document is due; off until he switches it on


class TelegramLink(BaseModel):
    """telegram/{uid}: who the owner is on Telegram."""

    tg_user_id: int
    chat_id: int
    paired_at: str
    session_id: str | None = None
    allow_private_reads: bool = False
    # R2 D12: the vault list, notes and things (its own switch; telegram.rules)
    allow_personal_reads: bool = False
    alerts: AlertToggles = Field(default_factory=AlertToggles)
    rev: int = 0


__all__ = [
    "AlertToggles",
    "CallbackQuery",
    "Chat",
    "Message",
    "TelegramLink",
    "Update",
    "User",
    "parse_update",
]
