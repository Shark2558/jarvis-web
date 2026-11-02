# src/jarvis/tools/tasks_cards.py
"""Approval-card text for the to-do tools (Layer 4 → 1). Pure functions, no I/O.

A card shows the task's real title and due date (looked up first by the tool's preview), every
change as old → new, and what cannot be undone. Task titles and notes are often someone else's
words (Gmail's "Add to Tasks" copies the email), so every value goes through
`jarvis.tools.card.one_line` / `quoted`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from jarvis.tools.card import one_line, quoted
from jarvis.tools.tasks_api import date_of, show_date

TITLE_LIMIT = 120
LIST_LIMIT = 60
CHANGE_LIMIT = 80
NOTES_LIMIT = 200
DATE_ONLY = "Google Tasks keeps the date only: the time is not kept"
ASSIGNED = "Assigned from Google Docs or Chat: deleting it here also deletes it there."
ASSIGNED_CHANGE = "Assigned from a Google Doc or Chat space: people there can see this change."


def _title(task: dict[str, Any]) -> str:
    return quoted(task.get("title") or "(no title)", TITLE_LIMIT)


def _due(d: date | None, dropped: bool) -> str:
    if d is None:
        return "Due: no date"
    return f"Due: {show_date(d)}" + (f" ({DATE_ONLY})" if dropped else "")


def _list_line(list_title: str | None) -> str:
    return f"List: {quoted(list_title, LIST_LIMIT)}" if list_title else "List: your default list"


def _value(value: Any) -> str:
    return quoted(value, CHANGE_LIMIT) if one_line(value, CHANGE_LIMIT) else "(none)"


def add_card(a: dict[str, Any], *, due: date | None, dropped: bool, list_title: str | None) -> str:
    lines = [f"Add to-do {quoted(a.get('title'), TITLE_LIMIT)}", _list_line(list_title)]
    lines.append(_due(due, dropped))
    if one_line(a.get("notes"), NOTES_LIMIT):
        lines.append(f"Notes: {one_line(a.get('notes'), NOTES_LIMIT)}")
    return "\n".join(lines)


def update_card(task: dict[str, Any], a: dict[str, Any], *, due: date | None, dropped: bool) -> str:
    """`due` is the parsed new date (None = cleared) — used only when 'due' is in `a`."""
    old_due = date_of(task.get("due"))
    lines = [f"Change to-do {_title(task)} (due {show_date(old_due)})", "Changes:"]
    if "title" in a:
        lines.append(f"• title: {_value(task.get('title'))} → {_value(a['title'])}")
    if "due" in a:
        new = show_date(due) + (f" ({DATE_ONLY})" if dropped else "")
        lines.append(f"• due: {show_date(old_due)} → {new}")
    if "notes" in a:
        lines.append(f"• notes: {_value(task.get('notes'))} → {_value(a['notes'])}")
    if task.get("assignmentInfo"):
        lines.append(ASSIGNED_CHANGE)
    return "\n".join(lines)


def complete_card(task: dict[str, Any]) -> str:
    line = f"Mark to-do done: {_title(task)} (due {show_date(date_of(task.get('due')))})"
    return f"{line}\n{ASSIGNED_CHANGE}" if task.get("assignmentInfo") else line


def _subtasks_line(n: int, all_read: bool) -> str | None:
    """Google does not document what happens to subtasks: assume they go with their parent."""
    if n == 0 and all_read:
        return None
    count = f"{'' if all_read else 'at least '}{n} subtask{'' if n == 1 else 's'}"
    if n == 0:  # none in the part JARVIS could read
        return "Its subtasks could not all be checked: any it has may be deleted with it."
    return f"It has {count}: they may be deleted with it (Google does not say)."


def delete_card(
    task: dict[str, Any], list_title: str | None, *, subtasks: tuple[int, bool] = (0, True)
) -> str:
    lines = [
        f"Delete to-do {_title(task)} — cannot be undone",
        _due(date_of(task.get("due")), False),
    ]
    if list_title:
        lines.append(_list_line(list_title))
    if (children := _subtasks_line(*subtasks)) is not None:
        lines.append(children)
    if task.get("assignmentInfo"):
        lines.append(ASSIGNED)
    return "\n".join(lines)


__all__ = ["DATE_ONLY", "add_card", "complete_card", "delete_card", "update_card"]
