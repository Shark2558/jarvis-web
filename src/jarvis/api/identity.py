# src/jarvis/api/identity.py
"""Who is calling (Layer 3: context). The user id is derived on the server from the sign-in and
never accepted from the client: a body or query `user_id` is ignored everywhere.

- Google sign-in   → `u_` + sha256(email)[:16]  (stable; the email itself is never stored as an id)
- API bearer token → the first owner email's id (the CLI is the primary owner's tool)
- no owners configured (local dev, tests) → "owner", the id used before this existed
"""

from __future__ import annotations

import asyncio
import hashlib

from fastapi import Request

from jarvis.api.auth import session_email
from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.memory.base import SessionStore

log = get_logger(__name__)

LEGACY_USER_ID = "owner"
ADOPT_TIMEOUT_S = 20.0  # start-up must stay well inside Cloud Run's start-up probe
_ID_HEX = 16


def user_id_for_email(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    return f"u_{digest[:_ID_HEX]}"


def primary_user_id(s: Settings) -> str:
    return user_id_for_email(s.owner_emails[0]) if s.owner_emails else LEGACY_USER_ID


def current_user(request: Request) -> str:
    """FastAPI dependency. Use only on routes that already depend on `require_auth`."""
    s: Settings = request.app.state.settings
    email = session_email(request, s)
    return user_id_for_email(email) if email else primary_user_id(s)


async def adopt_legacy_sessions(store: SessionStore, s: Settings) -> None:
    """Conversations saved before ids existed belong to the first owner. Idempotent and
    best-effort and time-boxed: a failure or timeout is logged and start-up continues (the
    rest are adopted at the next start; each moved session is complete on its own)."""
    new = primary_user_id(s)
    if new == LEGACY_USER_ID:
        return
    try:
        moved = await asyncio.wait_for(
            store.reassign_user(LEGACY_USER_ID, new), timeout=ADOPT_TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001 — never block start-up on a one-off migration
        log.warning("legacy conversations not adopted yet", extra={"reason": type(exc).__name__})
        return
    if moved:
        log.info("legacy conversations adopted", extra={"count": moved})
