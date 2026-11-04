# src/jarvis/activity/words.py
"""Plain words for one Activity row (R1 plan D7/D8). Pure, no I/O.

A write reads as the tool's own card text (`Tool.summary`, one clean line). A read reads as a
fixed verb with NO query text ("Searched your email"). Anything that did not run gets a short
prefix. `undo_note` is the reason a row has no Undo button (plan D8 table).
"""

from __future__ import annotations

from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.tools.card import one_line
from jarvis.tools.registry import ToolRegistry

WORDS_LIMIT = 300
NAME_LIMIT = 64

# (past tense, imperative) by exact tool name, then by prefix (first match wins)
_READS_EXACT: dict[str, tuple[str, str]] = {
    "get_calendar": ("Looked at your calendar", "Look at your calendar"),
    "list_tasks": ("Looked at your to-do list", "Look at your to-do list"),
    "gmail_track_packages": ("Checked your parcels", "Check your parcels"),
    "deleted_list": ("Looked at Recently deleted", "Look at Recently deleted"),
    "memory_search": ("Looked in your memory", "Look in your memory"),
    "contacts_search": ("Looked up your contacts", "Look up your contacts"),
}
_READS_PREFIX: tuple[tuple[str, tuple[str, str]], ...] = (
    ("calendar_", ("Looked at your calendar", "Look at your calendar")),
    ("reminders_", ("Looked at your reminders", "Look at your reminders")),
    ("tasks_", ("Looked at your to-do list", "Look at your to-do list")),
    ("grocery_", ("Looked at your grocery list", "Look at your grocery list")),
    ("family_", ("Looked at family calendars", "Look at family calendars")),
    ("gmail_", ("Searched your email", "Search your email")),
    ("web_", ("Searched the web", "Search the web")),
    ("drive_", ("Looked in your Drive", "Look in your Drive")),
    ("doc_", ("Looked in your documents", "Look in your documents")),
    ("docs_", ("Looked in your documents", "Look in your documents")),
    ("maps_", ("Looked at Maps", "Look at Maps")),
    ("youtube_", ("Looked at YouTube", "Look at YouTube")),
    ("contacts_", ("Looked up your contacts", "Look up your contacts")),
    ("memory_", ("Looked in your memory", "Look in your memory")),
)
_READ_FALLBACK = ("Looked something up", "Look something up")

PREFIXES = {
    "waiting": "Waiting for your OK: ",
    "refused": "Blocked by your settings: ",
    "failed": "Didn't work: ",
    "declined": "You declined: ",
}
_UNFINISHED_NOTE = {
    "waiting": "Nothing has happened yet",
    "refused": "Nothing was done",
    "declined": "Nothing was done",
    "failed": "Didn't complete",
}

NOTE_WRITE = "Can't be undone from here \u2014 ask JARVIS to change or delete it"
NOTE_DRAFT = "In Gmail Drafts \u2014 delete it there if you don't want it"
NOTE_WHATSAPP = "Nothing was sent"
NOTE_SENT = "Sent \u2014 can't be undone"
NOTE_MEMORY = "Remove it in Memory"
NOTE_RESTORE = "Delete it again if you didn't want it back"
NOTE_DELETE_NO_BIN = "Not kept in Recently deleted \u2014 can't be undone"


def _read_words(tool: str) -> tuple[str, str]:
    if tool in _READS_EXACT:
        return _READS_EXACT[tool]
    for prefix, words in _READS_PREFIX:
        if tool.startswith(prefix):
            return words
    return _READ_FALLBACK


def kind_of(tool: str, risk: ActionRisk) -> str:
    """read | write | delete | send | draft | restore, from what the tool is and can do."""
    if tool == "deleted_restore":
        return "restore"
    if "delete" in tool or tool in {"memory_forget"} or tool.startswith("grocery_remove"):
        return "delete"
    if tool in {"gmail_send", "send_message"}:
        return "send"
    if tool == "gmail_create_draft" or tool.startswith("whatsapp_"):
        return "draft"
    return "read" if risk is ActionRisk.READ_ONLY else "write"


def describe(
    tool: str, args: dict[str, Any], risk: ActionRisk, outcome: str, registry: ToolRegistry
) -> tuple[str, str]:
    """(kind, words) for one call. `outcome` is a row outcome (done, waiting, ...)."""
    kind = kind_of(tool, risk)
    known = registry.get(tool)
    if kind == "read":
        past, imperative = _read_words(tool)
        base = past if outcome == "done" else imperative
    elif known is not None:
        base = known.summary(args)
    else:
        base = f"Use {one_line(tool, NAME_LIMIT)}"
    prefix = PREFIXES.get(outcome, "")
    return kind, one_line(prefix + base, WORDS_LIMIT)


def undo_note(tool: str, kind: str, outcome: str, *, has_bin_copy: bool = False) -> str:
    """Why this row has no Undo button ('' for a read, or a delete whose copy is in the bin)."""
    if outcome != "done":
        return _UNFINISHED_NOTE.get(outcome, "")
    if kind == "read" or has_bin_copy:
        return ""
    if kind == "restore":
        return NOTE_RESTORE
    if kind == "send":
        return NOTE_SENT
    if kind == "draft":
        return NOTE_WHATSAPP if tool.startswith("whatsapp_") else NOTE_DRAFT
    if kind == "delete":
        return NOTE_DELETE_NO_BIN
    if tool.startswith("memory_"):
        return NOTE_MEMORY
    return NOTE_WRITE


__all__ = ["describe", "kind_of", "undo_note"]
