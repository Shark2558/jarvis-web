# tests/test_tasks_undo.py — slice 11 D1/D2 for to-dos: deleting the owner's own to-do keeps a
# copy (with its subtasks) first and runs without a card; one assigned from Docs / Chat, or one
# whose subtasks can't all be read, stays R3; restore puts it back in the same list — under its
# parent and after its previous sibling when they still exist — with notes, due date and status,
# and brings back the subtasks that went with it (whether or not Google deleted them too).
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from tasks_fakes import FakeTasks, tasks_connector

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.permissions.store import PermissionsStore
from jarvis.storage.docs import MemoryDocs, Set
from jarvis.tools.audit import AuditLog
from jarvis.tools.external import FENCE_END
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.google_tasks import tasks_tools
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust
from jarvis.tools.task_marks import OutsideTasks
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.undo.tools import undo_tools

UID = "u_owner"
SCOPE = f"{UID}:sess_1"
NOW = datetime(2027, 1, 15, 3, 0, tzinfo=UTC)


class FailingDocs(MemoryDocs):
    async def write(self, ops: Any) -> None:
        raise RuntimeError("store down")


def _fake(**kw: Any) -> FakeTasks:
    fake = FakeTasks(lists=[{"id": "L1", "title": "My Tasks"}, {"id": "L2", "title": "Work"}], **kw)
    fake.add("L2", "First", id="t_first", position="00000000000000000001")
    fake.add(
        "L2",
        "Review RFP",
        id="t_rfp",
        position="00000000000000000002",
        due="2027-01-20",
        notes="Clause 4 needs legal",
    )
    fake.add("L2", "Last", id="t_last", position="00000000000000000003")
    fake.add("L1", "Done thing", id="t_done", status="completed", completed="2027-01-10T00:00:00Z")
    fake.add("L1", "Fix clause 4", id="t_doc", assignmentInfo={"surfaceType": "DOCUMENT"})
    fake.add("L1", "Plan trip", id="t_trip", position="00000000000000000005")
    fake.add("L1", "Book hotel", id="t_hotel", parent="t_trip", position="00000000000000000001")
    fake.add("L1", "Book flight", id="t_fly", parent="t_trip", position="00000000000000000002")
    return fake


class Rig:
    def __init__(self, gw: Gateway, fake: FakeTasks, undo: UndoBin) -> None:
        self.gw, self.fake, self.bin = gw, fake, undo

    async def run(self, name: str, args: dict[str, Any], **kw: Any) -> GatewayResult:
        return await self.gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE, **kw)


async def _rig(fake: FakeTasks | None = None, docs: MemoryDocs | None = None) -> Rig:
    fake = fake or _fake()
    undo = UndoBin(DeletedStore(docs or MemoryDocs()), clock=lambda: NOW)
    reg = ToolRegistry()
    conn = await tasks_connector(fake)
    for t in tasks_tools(conn, default_tz="Asia/Kolkata", clock=lambda: NOW, undo=undo):
        reg.register(t)
    for t in undo_tools(undo):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    return Rig(gw, fake, undo)


async def _gateway_for(rig: Rig) -> Gateway:
    """A fresh connector over the rig's fake (after a test swapped its handler)."""
    conn = await tasks_connector(rig.fake)
    reg = ToolRegistry()
    tools = tasks_tools(conn, default_tz="Asia/Kolkata", clock=lambda: NOW, undo=rig.bin)
    for t in tools + undo_tools(rig.bin):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def test_with_a_bin_task_delete_is_declared_r2_and_undoable() -> None:
    rig = await _rig()
    tool = rig.gw.registry.get("task_delete")
    assert tool is not None and tool.risk is ActionRisk.REVERSIBLE and tool.undoable
    assert "Recently deleted" in tool.description


async def test_deleting_my_own_todo_runs_without_a_card_and_restores_in_place() -> None:
    rig = await _rig()
    out = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert await rig.gw.pending() == [] and len(rig.fake.changes("delete")) == 1
    r = out.result
    assert r["deleted"] is True and r["kind"] == "task" and r["undo_id"].startswith("del_")
    assert "Review RFP" in r["title"] and FENCE_END.search(r["title"])
    assert "undo" in r["note"].lower()
    back = await rig.run("deleted_restore", {"undo_id": r["undo_id"]})
    assert back.outcome is GatewayOutcome.EXECUTED and back.result["restored"] is True
    [ins] = rig.fake.changes("insert")
    assert ins.list_id == "L2"  # the same list
    assert ins.body["title"] == "Review RFP" and ins.body["notes"] == "Clause 4 needs legal"
    assert ins.body["due"].startswith("2027-01-20")
    assert ins.params == {"previous": "t_first"}  # after its previous sibling, which still exists
    assert rig.fake.task("L2", back.result["id"]) is not None
    again = await rig.run("deleted_restore", {"undo_id": r["undo_id"]})
    assert again.result["status"] == "already_restored" and len(rig.fake.changes("insert")) == 1


async def test_the_copy_records_whether_the_owner_wrote_the_todo() -> None:
    fake = _fake()
    fake.add("L1", "Reply to Priya", id="t_mail", links=[{"type": "email", "link": "https://x"}])
    fake.add("L1", "Parent", id="t_par", position="00000000000000000009")
    fake.add("L1", "From mail", id="t_kid", parent="t_par", links=[{"type": "email"}])
    rig = await _rig(fake)
    mine = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    mail = await rig.run("task_delete", {"task_id": "L1:t_mail"})
    mixed = await rig.run("task_delete", {"task_id": "L1:t_par"})  # a subtask came from a mail
    flags = {i.id: i.owner_authored for i in await rig.bin.recent(UID)}
    assert flags[mine.result["undo_id"]] is True
    assert flags[mail.result["undo_id"]] is False
    assert flags[mixed.result["undo_id"]] is False


async def test_a_done_todo_comes_back_done() -> None:
    rig = await _rig()
    out = await rig.run("task_delete", {"task_id": "L1:t_done"})
    await rig.run("deleted_restore", {"undo_id": out.result["undo_id"]})
    [ins] = rig.fake.changes("insert")
    assert ins.body["status"] == "completed" and ins.body["completed"].startswith("2027-01-10")


async def test_a_subtask_comes_back_under_its_parent_while_the_parent_exists() -> None:
    rig = await _rig()
    out = await rig.run("task_delete", {"task_id": "L1:t_fly"})
    await rig.run("deleted_restore", {"undo_id": out.result["undo_id"]})
    [ins] = rig.fake.changes("insert")
    assert ins.params == {"parent": "t_trip", "previous": "t_hotel"}


async def test_a_subtask_whose_parent_is_gone_comes_back_at_the_top_level() -> None:
    rig = await _rig()
    out = await rig.run("task_delete", {"task_id": "L1:t_fly"})
    rig.fake.tasks["L1"] = [t for t in rig.fake.tasks["L1"] if t["id"] not in {"t_trip", "t_hotel"}]
    back = await rig.run("deleted_restore", {"undo_id": out.result["undo_id"]})
    assert back.result["restored"] is True
    [ins] = rig.fake.changes("insert")
    assert ins.params == {}


@pytest.mark.parametrize("cascade", [True, False])
async def test_a_parent_comes_back_with_its_subtasks_either_way_google_behaves(
    cascade: bool,
) -> None:
    rig = await _rig(_fake(cascade=cascade))
    held = await rig.run("task_delete", {"task_id": "L1:t_trip"})
    assert held.outcome is GatewayOutcome.EXECUTED, held.error
    item = await rig.bin.get(UID, held.result["undo_id"])
    assert item is not None and [c["id"] for c in item.snapshot["children"]] == ["t_hotel", "t_fly"]
    assert held.result["subtasks"] == 2
    back = await rig.run("deleted_restore", {"undo_id": held.result["undo_id"]})
    assert back.result["restored"] is True
    new_parent = back.result["id"]
    kids = [t for t in rig.fake.tasks["L1"] if t.get("parent") == new_parent]
    assert sorted(t["title"] for t in kids) == ["Book flight", "Book hotel"]
    if cascade:  # Google took them: recreated in order under the new parent
        ins = rig.fake.changes("insert")
        assert [m.body["title"] for m in ins] == ["Plan trip", "Book hotel", "Book flight"]
        assert ins[2].params == {"parent": new_parent, "previous": ins[1].task_id}
    else:  # Google kept them: moved back under the new parent, never duplicated
        assert [m.task_id for m in rig.fake.changes("move")] == ["t_hotel", "t_fly"]
        assert len(rig.fake.changes("insert")) == 1


async def test_card_for_an_undoable_delete_in_a_tainted_round_says_it_can_be_undone() -> None:
    rig = await _rig()
    with context_trust(untrusted=True):
        out = await rig.run("task_delete", {"task_id": "L1:t_trip"})
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending is not None
    card = out.pending.summary
    assert out.pending.tool_risk is ActionRisk.REVERSIBLE
    assert "cannot be undone" not in card and "Recently deleted" in card
    assert "2 subtasks" in card and "come back" in card
    assert rig.fake.changes("delete") == []


async def test_a_todo_assigned_from_docs_stays_r3_and_is_not_kept() -> None:
    rig = await _rig()
    held = await rig.run("task_delete", {"task_id": "L1:t_doc"})
    assert held.outcome is GatewayOutcome.AWAITING_CONFIRMATION and held.pending is not None
    assert held.pending.tool_risk is ActionRisk.IRREVERSIBLE
    assert "cannot be undone" in held.pending.summary
    done = await rig.run("task_delete", {"task_id": "L1:t_doc"}, confirmation_id=held.pending.id)
    assert done.outcome is GatewayOutcome.EXECUTED and "undo_id" not in done.result
    assert await rig.bin.recent(UID) == []


async def test_subtasks_that_cannot_all_be_read_make_the_delete_r3() -> None:
    fake = _fake()
    for i in range(301):  # more than the 3 pages JARVIS reads per list
        fake.add("L1", f"filler {i}", id=f"f{i:04d}")
    rig = await _rig(fake)
    held = await rig.run("task_delete", {"task_id": "L1:t_trip"})
    assert held.outcome is GatewayOutcome.AWAITING_CONFIRMATION and held.pending is not None
    assert held.pending.tool_risk is ActionRisk.IRREVERSIBLE


async def test_snapshot_store_down_means_the_todo_is_not_deleted() -> None:
    rig = await _rig(docs=FailingDocs())
    out = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    assert out.outcome is GatewayOutcome.ERROR and "nothing was deleted" in (out.error or "")
    assert rig.fake.changes("delete") == [] and rig.fake.task("L2", "t_rfp") is not None


async def test_a_failed_google_delete_drops_the_copy() -> None:
    rig = await _rig()
    rig.fake.fail["delete"] = 500
    out = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    assert out.outcome is GatewayOutcome.ERROR and await rig.bin.recent(UID) == []


async def test_a_todo_that_became_assigned_after_the_decision_is_not_deleted() -> None:
    rig = await _rig()
    fake = rig.fake
    real, gets = fake.handler, [0]

    def flip(request: Any) -> Any:  # the decision's look-up: the owner's; the run's: assigned
        if request.method == "GET" and request.url.path.endswith("/t_rfp"):
            gets[0] += 1
            task = fake.task("L2", "t_rfp")
            if gets[0] == 2 and task is not None:
                task["assignmentInfo"] = {"surfaceType": "SPACE"}
        return real(request)

    fake.handler = flip  # type: ignore[method-assign]
    conn = await tasks_connector(fake)
    reg = ToolRegistry()
    for t in tasks_tools(conn, default_tz="Asia/Kolkata", clock=lambda: NOW, undo=rig.bin):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    out = await gw.execute(
        ToolCall(id="c", name="task_delete", arguments={"task_id": "L2:t_rfp"}), scope=SCOPE
    )
    assert out.outcome is GatewayOutcome.ERROR and "changed" in (out.error or "")
    assert fake.changes("delete") == []


# ---- slice 11 fix: a lost answer to the DELETE --------------------------------------------------


@pytest.mark.parametrize("soft", [False, True])
async def test_a_delete_whose_answer_was_lost_is_checked_and_kept(soft: bool) -> None:
    """Google deleted it but answered 503: reading it again finds it gone (404, or — as Google
    may — still readable with `deleted: true`), so the copy stays and the delete is done."""
    fake = _fake(soft_delete=soft)
    fake.lost["delete"] = 503
    rig = await _rig(fake)
    out = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert out.result["deleted"] is True
    assert [i.id for i in await rig.bin.recent(UID)] == [out.result["undo_id"]]
    if soft:
        task = rig.fake.task("L2", "t_rfp")
        assert task is not None and task["deleted"] is True


async def test_a_delete_nobody_can_confirm_keeps_the_copy_and_restore_checks_first() -> None:
    fake = _fake()
    fake.fail["delete"] = 503
    fake.after_delete["get"] = 503  # reading it again fails too
    rig = await _rig(fake)
    out = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert out.result["deleted"] == "unconfirmed" and "check Recently deleted" in out.result["note"]
    assert len(await rig.bin.recent(UID)) == 1
    fake.after_delete.clear()  # it was never deleted: a restore says so and makes nothing
    back = await rig.run("deleted_restore", {"undo_id": out.result["undo_id"]})
    assert back.result["restored"] is False and back.result["status"] == "still_there"
    assert rig.fake.changes("insert") == []


async def test_an_approved_r2_card_refuses_a_todo_that_became_assigned_meanwhile() -> None:
    rig = await _rig()
    real, gets = rig.fake.handler, [0]

    def flip(request: Any) -> Any:  # card look-up, approval look-up: the owner's; the run's: not
        if request.method == "GET" and request.url.path.endswith("/t_rfp"):
            gets[0] += 1
            task = rig.fake.task("L2", "t_rfp")
            if gets[0] == 3 and task is not None:
                task["assignmentInfo"] = {"surfaceType": "SPACE"}
        return real(request)

    rig.fake.handler = flip  # type: ignore[method-assign]
    rig = Rig(await _gateway_for(rig), rig.fake, rig.bin)
    with context_trust(untrusted=True):
        card = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    assert card.pending is not None and card.pending.tool_risk is ActionRisk.REVERSIBLE
    ok = await rig.run("task_delete", {"task_id": "L2:t_rfp"}, confirmation_id=card.pending.id)
    assert ok.outcome is GatewayOutcome.ERROR and "changed" in (ok.error or "")
    assert rig.fake.changes("delete") == []


async def test_a_todo_with_an_assigned_subtask_stays_r3() -> None:
    fake = _fake()
    hotel = fake.task("L1", "t_hotel")
    assert hotel is not None
    hotel["assignmentInfo"] = {"surfaceType": "DOCUMENT"}
    rig = await _rig(fake)
    held = await rig.run("task_delete", {"task_id": "L1:t_trip"})
    assert held.outcome is GatewayOutcome.AWAITING_CONFIRMATION and held.pending is not None
    assert held.pending.tool_risk is ActionRisk.IRREVERSIBLE


async def test_a_restore_whose_previous_sibling_is_refused_retries_without_it() -> None:
    rig = await _rig()
    out = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    first = rig.fake.task("L2", "t_first")
    assert first is not None
    first["parent"] = "t_last"  # moved meanwhile: no longer a sibling, Google answers 400
    back = await rig.run("deleted_restore", {"undo_id": out.result["undo_id"]})
    assert back.outcome is GatewayOutcome.EXECUTED, back.error
    assert back.result["restored"] is True
    [ins] = rig.fake.changes("insert")
    assert ins.params == {}  # the second try, without `previous`
    bad = [r for r in rig.fake.requests if r.method == "POST" and "previous" in r.url.params]
    assert len(bad) == 1


async def test_a_stored_never_on_deleting_todos_still_blocks_an_own_todo_delete() -> None:
    """Slice 11 fix HIGH-1: Never on the old "Delete to-dos" row keeps meaning never."""
    rig = await _rig()
    docs = MemoryDocs()
    legacy = {"user_id": UID, "groups": {"todo_delete": "deny"}}
    await docs.write([Set(f"jarvis_permissions/{UID}", legacy)])
    rig.gw.rules = PermissionsStore(docs)
    out = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    assert out.outcome is GatewayOutcome.DENIED and "switched off" in (out.error or "")
    assert rig.fake.changes("delete") == [] and await rig.bin.recent(UID) == []


# ---- slice 11 integration: D8 over the fixer's delete and restore paths -----------------------

GMAIL_LINK = [{"type": "email", "link": "https://mail.google.com/mail/#all/1"}]


async def _marked_rig(fake: FakeTasks) -> tuple[Rig, OutsideTasks]:
    """A rig whose outside to-do set the test can read."""
    marks = OutsideTasks(MemoryDocs(), clock=lambda: NOW)
    undo = UndoBin(DeletedStore(MemoryDocs()), clock=lambda: NOW)
    conn = await tasks_connector(fake)
    reg = ToolRegistry()
    tools = tasks_tools(conn, default_tz="Asia/Kolkata", clock=lambda: NOW, undo=undo, marks=marks)
    for t in [*tools, *undo_tools(undo)]:
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    return Rig(gw, fake, undo), marks


def _unconfirmable() -> FakeTasks:
    """Its DELETE answers 503 and reading the to-do again fails too: "unconfirmed"."""
    fake = _fake()
    fake.add("L2", "Pay vendor", id="t_mail", links=GMAIL_LINK)  # Gmail "Add to Tasks"
    fake.fail["delete"] = 503
    fake.after_delete["get"] = 503
    return fake


@pytest.mark.parametrize(("task_id", "mine"), [("t_rfp", True), ("t_mail", False)])
async def test_an_unconfirmed_todo_delete_is_trusted_only_by_the_kept_copys_flag(
    task_id: str, mine: bool
) -> None:
    rig, _ = await _marked_rig(_unconfirmable())
    out = await rig.run("task_delete", {"task_id": f"L2:{task_id}"})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert out.result["deleted"] == "unconfirmed"
    [kept] = await rig.bin.recent(UID)
    assert kept.owner_authored is mine and out.trusted is mine


async def test_a_restore_that_finds_someone_elses_todo_still_there_marks_nothing() -> None:
    """The still-there check comes before the pending outside mark: nothing made, nothing
    pending (a pending mark would make every recently changed to-do count as outside)."""
    fake = _unconfirmable()
    rig, marks = await _marked_rig(fake)
    out = await rig.run("task_delete", {"task_id": "L2:t_mail"})
    fake.after_delete.clear()  # never deleted
    back = await rig.run("deleted_restore", {"undo_id": out.result["undo_id"]})
    assert back.result["status"] == "still_there" and back.trusted is False
    got = await marks.read(UID)
    assert got is not None and got.ids == frozenset() and got.pending_since is None
    assert rig.fake.changes("insert") == []


async def test_a_restore_of_someone_elses_todo_retrying_without_previous_marks_it() -> None:
    """The fixer's `previous` retry (400) still ends with the new to-do in the outside set."""
    fake = _fake()
    rfp = fake.task("L2", "t_rfp")
    assert rfp is not None
    rfp["links"] = GMAIL_LINK  # Gmail "Add to Tasks": not the owner's own words
    rig, marks = await _marked_rig(fake)
    out = await rig.run("task_delete", {"task_id": "L2:t_rfp"})
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is False, out.error
    first = rig.fake.task("L2", "t_first")
    assert first is not None
    first["parent"] = "t_last"  # moved meanwhile: no longer a sibling, Google answers 400
    back = await rig.run("deleted_restore", {"undo_id": out.result["undo_id"]})
    assert back.outcome is GatewayOutcome.EXECUTED and back.result["restored"] is True
    assert back.trusted is False
    [ins] = rig.fake.changes("insert")
    assert ins.params == {}  # the second try, without `previous`
    got = await marks.read(UID)
    assert got is not None and got.ids == {ins.task_id} and got.pending_since is None


async def test_without_a_bin_task_delete_stays_r3_as_before() -> None:
    conn = await tasks_connector(FakeTasks())
    tool = next(t for t in tasks_tools(conn) if t.name == "task_delete")
    assert tool.risk is ActionRisk.IRREVERSIBLE and not tool.undoable
