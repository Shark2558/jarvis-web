# src/jarvis/telegram/rules.py
"""Privacy on Telegram (R1 D4). Bot chats are cloud chats on Telegram's servers, not end-to-end
encrypted, so email, Drive, documents and contacts readouts are refused during a Telegram turn
unless the owner switched them on (Integrations -> Telegram). `ChannelRules` wraps the gateway's
`OwnerRules` and appends DENY rules (source "telegram") only while `core.channel.on_telegram()`.
Unpaired or unreadable state fails closed. No gateway change."""

from __future__ import annotations

from jarvis.core.channel import on_telegram
from jarvis.logging import get_logger
from jarvis.telegram.store import TelegramStore
from jarvis.tools.policy import Effect, OwnerRules, PolicyRule

log = get_logger(__name__)

# gmail_track_packages (carrier and status only), gmail_create_draft and the rest stay allowed
PRIVATE_PATTERNS: tuple[str, ...] = (
    "gmail_search",
    "gmail_read",
    "gmail_unread_digest",
    "drive_*",
    "doc_*",
    "docs_*",
    "contacts_*",
)
REFUSAL = "Not available from Telegram — your choice in Integrations → Telegram; open the console."


def _deny_rules() -> list[PolicyRule]:
    return [
        PolicyRule(tool_pattern=p, effect=Effect.DENY, source="telegram", reason=REFUSAL)
        for p in PRIVATE_PATTERNS
    ]


class ChannelRules:
    """An `OwnerRules` that adds the Telegram privacy rules to another's."""

    def __init__(self, inner: OwnerRules | None, store: TelegramStore) -> None:
        self._inner = inner
        self._store = store

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        rules = list(await self._inner.rules_for(user_id)) if self._inner is not None else []
        if not on_telegram():
            return rules
        try:
            link = await self._store.get(user_id)
            allowed = link is not None and link.allow_private_reads
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.warning("telegram settings unreadable", extra={"error": type(exc).__name__})
            allowed = False
        return rules if allowed else [*rules, *_deny_rules()]


__all__ = ["PRIVATE_PATTERNS", "REFUSAL", "ChannelRules"]
