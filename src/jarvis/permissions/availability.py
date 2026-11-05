# src/jarvis/permissions/availability.py
"""Why a Permissions row may not work yet, in plain words (R1 plan D9; Layer 1 -> 6).

A row is NEVER hidden for this: it is listed with `available` and a `note` ("Connect Google in
Integrations first."). Computed per request from app state and the owner's Google link; fail-soft:
anything unreadable reads as available with no note, so a broken check never hides a row.
Pure reads, no secrets, no Google call except the link's own status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.integrations.google import can_use_contacts, can_use_tasks
from jarvis.logging import get_logger
from jarvis.permissions.groups import GROUPS

log = get_logger(__name__)

NOT_HERE = "Not set up on this server."
CONNECT = "Connect Google in Integrations first."
RECONNECT = "Reconnect Google in Integrations first."
CONTACTS_GRANT = "Press Grant next to Contacts in Integrations first."
TASKS_GRANT = "Press Grant next to To-do list in Integrations first."
WHATSAPP_BY_NAME = "Drafts by name also need the Contacts Grant in Integrations."

_GOOGLE_ROWS = frozenset(
    {
        "calendar_read",
        "calendar_change",
        "calendar_remove",
        "calendar_delete",
        "reminders",
        "email_read",
        "email_draft",
        "email_send",
        "family_read",
        "family_change",
    }
)
_TASKS_ROWS = frozenset({"todo_change", "todo_remove", "todo_delete", "groceries"})
_SERVER_FEATURES = {"drive": "drive", "maps": "media", "youtube": "media", "web": "web"}
# R2 I1: rows whose feature is off without the server's encryption key (or switched off)
NO_KEY = "Not available on this server (no encryption key)."
_KEYED_FEATURES = {
    "vault_read": "vault",
    "vault_change": "vault",
    "notes_read": "notes",
    "notes_change": "notes",
    "belongings": "belongings",
    # R3 I1: the home's rows need the home link's store; camera history needs the camera
    "home_read": "home_store",
    "home_control": "home_store",
    "home_arm": "home_store",
    "home_secure": "home_store",
    "camera": "camera",
}
LINK_HOME = "Link your home laptop in Integrations -> Home first."
_HOME_ROWS = frozenset({"home_read", "home_control", "home_arm", "home_secure", "camera"})


@dataclass(frozen=True)
class Availability:
    available: bool = True
    note: str = ""


OK = Availability()


async def _link(state: Any, uid: str) -> tuple[str, list[str]] | None:
    """('none' | 'off' | 'reconnect' | 'ok', scopes) for the owner's Google link; None = unknown."""
    google = getattr(state, "google", None)
    if google is None:
        return "off", []
    try:
        st = await google.status(uid)
    except Exception as exc:  # noqa: BLE001 - fail-soft: unknown means no note
        log.warning("google status unreadable for notes", extra={"error": type(exc).__name__})
        return None
    if not st.get("connected"):
        return ("reconnect" if st.get("needs_reconnect") else "none"), []
    scopes = [str(s) for s in st.get("scopes") or []]
    return ("reconnect" if st.get("needs_reconnect") else "ok"), scopes


def _google_gate(link: tuple[str, list[str]] | None) -> Availability | None:
    """None when Google is fine (or unknown); else the reason."""
    if link is None or link[0] == "ok":
        return None
    return Availability(False, {"off": NOT_HERE, "reconnect": RECONNECT}.get(link[0], CONNECT))


async def _home_linked(state: Any, uid: str) -> bool | None:
    """Whether the owner linked a home laptop; None when Home is off or unreadable (no note)."""
    store = getattr(state, "home_store", None)
    if store is None:
        return None
    try:
        return await store.status(uid) is not None
    except Exception as exc:  # noqa: BLE001 - fail-soft: unknown means no note
        log.warning("home link unreadable for notes", extra={"error": type(exc).__name__})
        return None


def _row(
    gid: str, state: Any, link: tuple[str, list[str]] | None, home: bool | None = None
) -> Availability:
    if gid in _SERVER_FEATURES:
        return (
            OK
            if getattr(state, _SERVER_FEATURES[gid], None) is not None
            else Availability(False, NOT_HERE)
        )
    if gid in _KEYED_FEATURES:
        on = getattr(state, _KEYED_FEATURES[gid], None) is not None
        if on and gid in _HOME_ROWS and home is False:
            return Availability(False, LINK_HOME)
        return OK if on else Availability(False, NO_KEY)
    if gid == "whatsapp":  # typed numbers always work; names need the Contacts Grant
        has = link is not None and link[0] == "ok" and can_use_contacts(link[1])
        return OK if has or link is None else Availability(True, WHATSAPP_BY_NAME)
    if gid in _GOOGLE_ROWS:
        return _google_gate(link) or OK
    if gid == "contacts" or gid in _TASKS_ROWS:
        if (gate := _google_gate(link)) is not None:
            return gate
        if link is None:
            return OK
        have = can_use_contacts(link[1]) if gid == "contacts" else can_use_tasks(link[1])
        if have:
            return OK
        return Availability(False, CONTACTS_GRANT if gid == "contacts" else TASKS_GRANT)
    return OK


async def notes(state: Any, uid: str) -> dict[str, Availability]:
    """One entry per permission group (all of them, in any state)."""
    link = await _link(state, uid)
    home = await _home_linked(state, uid)
    return {g.id: _row(g.id, state, link, home) for g in GROUPS}


__all__ = [
    "LINK_HOME",
    "CONNECT",
    "CONTACTS_GRANT",
    "NO_KEY",
    "NOT_HERE",
    "OK",
    "RECONNECT",
    "TASKS_GRANT",
    "WHATSAPP_BY_NAME",
    "Availability",
    "notes",
]
