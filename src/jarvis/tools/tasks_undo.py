# src/jarvis/tools/tasks_undo.py
"""Undo-able to-do deletes (slice 11 D1/D2; Layer 5/6): which can be undone, the copy kept
before one, and how a to-do comes back.

Risk of a delete: R2 — undo-able — for the owner's own to-do; R3 for one assigned from a Google
Doc or Chat space (deleting it here deletes it there too, for other people) and for one whose
subtasks JARVIS can't all read (more than the list pages it reads: it couldn't keep them all).

Subtasks: Google's Tasks docs don't say what deleting a parent does to its subtasks (checked
2026-11-02: tasks.delete only "Deletes the specified task from the task list"), so the copy keeps
them all (every descendant, in list order). A restore then recreates the ones that are gone under
the new parent, and moves the ones Google kept back under it — right either way, never twice.

The copy holds the to-do's title, notes, due, status and completed, its list, its parent and its
previous sibling (by `position`); a restore inserts it into the same list, under the parent and
after the sibling when they still exist (a gone parent → the top level).

Plan D8: the kept copy records whether the to-do and every subtask kept with it were the owner's
own (`provenance.is_owner_authored_task` plus his outside to-dos, `tools.task_marks`); the delete
result is trusted by that flag, and a restore of one that was not marks every to-do it makes, so
recreating it never launders a Gmail to-do (whose `links` Google won't recreate) into his own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleAPIError
from jarvis.logging import get_logger
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.provenance import vouch
from jarvis.tools.task_marks import OutsideSet, OutsideTasks, owner_authored_task
from jarvis.tools.tasks_api import TaskRef, TasksClient, valid_list_id, valid_task_id
from jarvis.undo.service import Restored, UndoBin
from jarvis.undo.tools import deleted_result

log = get_logger(__name__)

SOURCE = "to-do list"
FIELDS = ("title", "notes", "due", "status", "completed")
CHANGED = (
    "That to-do changed since it was checked (it can no longer be undone), so nothing was "
    "deleted. Look it up again and ask the owner."
)
WHY_ASSIGNED = "it was assigned from Google Docs or Chat"
WHY_UNREAD = "its subtasks could not all be checked"


def owner_authored(task: dict[str, Any], marks: OutsideSet | None) -> bool:
    """The owner's own words: plan D8's one rule (`provenance.is_owner_authored_task` plus the
    owner's outside to-dos, `tools.task_marks`; an unreadable set → not his own)."""
    return owner_authored_task(task, marks)


def delete_risk(task: dict[str, Any], *, all_read: bool) -> tuple[ActionRisk, str]:
    if task.get("assignmentInfo"):
        return ActionRisk.IRREVERSIBLE, WHY_ASSIGNED
    if not all_read:
        return ActionRisk.IRREVERSIBLE, WHY_UNREAD
    return ActionRisk.REVERSIBLE, ""


def _fields(task: dict[str, Any]) -> dict[str, Any]:
    return {k: task[k] for k in FIELDS if isinstance(task.get(k), str)}


def _pos(task: dict[str, Any]) -> str:
    return str(task.get("position") or "")


def descendants(items: Sequence[dict[str, Any]], root: str) -> list[dict[str, Any]]:
    """Every task under `root`, parents before their children, siblings in list order."""
    out: list[dict[str, Any]] = []

    def walk(parent: str, depth: int) -> None:
        kids = sorted((t for t in items if t.get("parent") == parent), key=_pos)
        for kid in kids:
            if depth < 10 and kid.get("id") != root:  # Google nests one level; never loop
                out.append(kid)
                walk(str(kid["id"]), depth + 1)

    walk(root, 0)
    return out


def previous_sibling(items: Sequence[dict[str, Any]], task: dict[str, Any]) -> str | None:
    """The sibling just before `task` (same parent, by position), when positions are known."""
    mine = _pos(task)
    if not mine:
        return None
    before = [
        t
        for t in items
        if t.get("parent") == task.get("parent") and t.get("id") != task.get("id")
        and _pos(t) and _pos(t) < mine
    ]  # fmt: skip
    return str(max(before, key=_pos)["id"]) if before else None


def task_snapshot(
    ref: TaskRef, task: dict[str, Any], items: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "list_id": ref.list_id,
        "id": ref.task_id,
        "task": _fields(task),
        "parent": task.get("parent"),
        "previous": previous_sibling(items, task),
        "children": [
            {"id": c["id"], "parent": c.get("parent"), "task": _fields(c)}
            for c in descendants(items, ref.task_id)
        ],
    }


@dataclass(frozen=True)
class Family:
    """A to-do just before its delete: itself, every task in its list, all of them read?"""

    task: dict[str, Any]
    items: list[dict[str, Any]]
    all_read: bool

    @property
    def subtasks(self) -> int:
        return len(descendants(self.items, str(self.task.get("id") or "")))


async def family(
    client: TasksClient, uid: str, ref: TaskRef, task: dict[str, Any] | None = None
) -> Family:
    """The to-do (read now unless given) and its list, read within the client's page budget."""
    task = task if task is not None else await client.get(uid, ref)
    page = await client.read(uid, ref.list_id, due_through=None, completed=True)
    return Family(task, page.items, not page.more)


async def delete_kept(
    client: TasksClient, undo: UndoBin, ref: TaskRef, marks: OutsideSet | None
) -> Any:
    """Delete the to-do (re-read now): undo-able → copy kept FIRST (none kept → nothing
    deleted); not undo-able → only when the owner approved it. `marks`: the owner's outside
    to-dos as read now (D8); the result is vouched for by the kept copy's flag."""
    ctx = require_tool_context()
    fam = await family(client, ctx.user_id, ref)
    risk, _ = delete_risk(fam.task, all_read=fam.all_read)
    if risk is ActionRisk.IRREVERSIBLE:
        if not ctx.confirmed:
            raise RuntimeError(CHANGED)
        await client.delete(ctx.user_id, ref)
        return {"deleted": True, "id": ref.composite}
    snap = task_snapshot(ref, fam.task, fam.items)
    title = one_line(fam.task.get("title"), 1024) or "(no title)"
    # owner-authored only when the to-do AND every subtask kept with it are (a restore and a
    # listing carry all of them)
    family_ = [fam.task, *descendants(fam.items, ref.task_id)]
    mine = all(owner_authored(t, marks) for t in family_)
    item = await undo.keep(ctx.user_id, "task", title, snap, owner_authored=mine)
    try:
        await client.delete(ctx.user_id, ref)
    except Exception:
        await undo.discard(ctx.user_id, item.id)  # not deleted: no "undo" for it
        raise
    extra = {"subtasks": len(snap["children"])} if snap["children"] else {}
    return vouch(deleted_result(item, source=SOURCE, **extra), item.owner_authored)


def _id_or_none(value: Any) -> str | None:
    return value if valid_task_id(value) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class TaskRestorer:
    client: TasksClient
    marks: OutsideTasks

    async def restore(
        self, uid: str, snapshot: dict[str, Any], *, outside: bool = False
    ) -> Restored:
        """`outside`: the kept to-do was not the owner's own (D8): a pending mark is stored before
        anything is made (none → nothing restored), and every id the restore makes or moves back
        replaces it after."""
        list_id, root = str(snapshot.get("list_id") or ""), _id_or_none(snapshot.get("id"))
        if not valid_list_id(list_id) or root is None:
            raise GoogleAPIError("The kept copy is unreadable, so the to-do can't be restored.")
        await self.client.require(uid)
        token = await self.marks.begin(uid) if outside else None
        parent = await self._still(uid, list_id, snapshot.get("parent"))
        # a sibling is only "previous" at the same level: a gone parent → the top level, alone
        had_parent = snapshot.get("parent") is not None
        previous = None if had_parent and parent is None else snapshot.get("previous")
        previous = await self._still(uid, list_id, previous)
        body = _fields(_dict(snapshot.get("task")))
        made = await self.client.insert(uid, list_id, body, parent=parent, previous=previous)
        new_id = str(made["id"])
        children = snapshot.get("children")
        kids = list(children) if isinstance(children, list) else []
        ids = {root: new_id}  # filled by _children: every to-do this restore made or moved
        note = await self._children(uid, list_id, ids, kids)
        if token is not None:
            await self.marks.finish(uid, token, ids.values())
        return Restored(new_id=new_id, note=note)

    async def _still(self, uid: str, list_id: str, task_id: Any) -> str | None:
        tid = _id_or_none(task_id)
        if tid is None:
            return None
        return tid if await self.client.exists(uid, TaskRef(list_id, tid)) else None

    async def _children(
        self, uid: str, list_id: str, ids: dict[str, str], children: list[Any]
    ) -> str:
        """Each kept subtask: recreated when gone, moved back under its new parent when Google
        kept it. A failure is counted and said, never undoes the parent's restore."""
        last: dict[str, str] = {}
        back = failed = 0
        for c in children:
            cid = _id_or_none(c.get("id")) if isinstance(c, dict) else None
            old_parent = _id_or_none(c.get("parent")) if isinstance(c, dict) else None
            if cid is None or old_parent is None:
                failed += 1
                continue
            parent = ids.get(old_parent, old_parent)
            try:
                ids[cid] = await self._child(uid, list_id, c, cid, parent, last.get(parent))
                last[parent] = ids[cid]
                back += 1
            except (GoogleAPIError, ValueError) as exc:
                log.warning("subtask not restored", extra={"error": type(exc).__name__})
                failed += 1
        return _children_note(back, failed)

    async def _child(
        self,
        uid: str,
        list_id: str,
        c: dict[str, Any],
        cid: str,
        parent: str,
        previous: str | None,
    ) -> str:
        ref = TaskRef(list_id, cid)
        if await self.client.exists(uid, ref):
            if parent != c.get("parent"):
                await self.client.move(uid, ref, parent=parent, previous=previous)
            return cid
        body = _fields(_dict(c.get("task")))
        made = await self.client.insert(uid, list_id, body, parent=parent, previous=previous)
        return str(made["id"])


def _children_note(back: int, failed: int) -> str:
    parts = []
    if back:
        parts.append(f"Its {back} subtask{'' if back == 1 else 's'} came back with it.")
    if failed:
        parts.append(f"{failed} subtask{' was' if failed == 1 else 's were'} not brought back.")
    return " ".join(parts)


__all__ = [
    "Family",
    "TaskRestorer",
    "delete_kept",
    "delete_risk",
    "descendants",
    "family",
    "owner_authored",
    "previous_sibling",
    "task_snapshot",
]
