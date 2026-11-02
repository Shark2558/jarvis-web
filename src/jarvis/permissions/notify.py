# src/jarvis/permissions/notify.py
"""A notice in the owner's own Gmail inbox when a passkey reset is requested (slice 10 D review M3).

Reuses the morning brief's inbox-copy path (`jarvis.brief.deliver`: one `users.messages.insert`
into the authenticated mailbox — nothing is sent, nothing leaves the account). Only when the
Google link is connected and its scopes allow insert; best effort: it never raises, and the
caller writes the audit record either way.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from jarvis.brief.deliver import build_brief_message, insert_message
from jarvis.integrations.google import GoogleConnector, can_insert
from jarvis.logging import get_logger

log = get_logger(__name__)

Notify = Callable[[str, str, str], Awaitable[bool]]  # (user id, subject, body) → put in inbox?


def inbox_notifier(google: GoogleConnector | None) -> Notify | None:
    """None without a Google link configured on this server."""
    if google is None:
        return None

    async def notify(uid: str, subject: str, body: str) -> bool:
        try:
            st = await google.status(uid)
            email = str(st.get("email") or "")
            if not st.get("connected") or st.get("needs_reconnect") or not email:
                return False
            if not can_insert(st.get("scopes") or []):
                return False
            raw = build_brief_message(
                owner=email, subject=subject, body=body, now=datetime.now(UTC)
            )
            await insert_message(google, uid, raw)
            return True
        except Exception as exc:  # noqa: BLE001 — a notice must never break the reset itself
            log.warning(
                "passkey reset notice not put in inbox", extra={"error": type(exc).__name__}
            )
            return False

    return notify


__all__ = ["Notify", "inbox_notifier"]
