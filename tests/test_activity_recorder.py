# tests/test_activity_recorder.py -- R1 B: the gateway observer that writes Activity rows (plan D7).
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jarvis.activity.recorder import ActivityRecorder
from jarvis.activity.store import ActivityStore
from jarvis.core import channel
from jarvis.core.guardrails import ActionRisk
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditEntry
from jarvis.tools.base import Tool
from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.tools.observers import GatewayEvent, notify
from jarvis.tools.registry import ToolRegistry

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)  # 15:30 in Asia/Kolkata, same day
R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE


async def _noop(**_: object) -> dict[str, object]:
    return {}


def reg() -> ToolRegistry:
    r = ToolRegistry()
    for name, risk, tpl in [
        ("task_add", R2, "Add a to-do: {title}"),
        ("calendar_delete_event", R2, "Delete an event"),
        ("web_search", R1, "Search the web for {query}"),
        ("gmail_send", R3, "Send an email to {to}"),
    ]:
        r.register(
            Tool(
                name=name,
                description="d",
                input_schema={"type": "object", "properties": {}},
                risk=risk,
                run=_noop,
                summary_template=tpl,
            )
        )
    return r


def entry(seq: int = 7) -> AuditEntry:
    return AuditEntry(
        seq=seq,
        at=NOW,
        trace_id="trace-1",
        agent="core",
        tool="x",
        risk=R2,
        outcome="executed",
        args_hash="h",
        prev_hash="p",
    )


def event(outcome: str, tool: str = "task_add", **kw: Any) -> GatewayEvent:
    base: dict[str, Any] = {
        "outcome": outcome,
        "tool": tool,
        "agent": "core",
        "risk": R2,
        "args": {"title": "milk"},
        "scope": "owner:sess-1",
        "entry": entry(),
        "result": GatewayResult(GatewayOutcome.EXECUTED, result={"ok": True}),
    }
    return GatewayEvent(**{**base, **kw})


def rig() -> tuple[ActivityRecorder, ActivityStore]:
    st = ActivityStore(MemoryDocs())
    return ActivityRecorder(st, reg(), timezone="Asia/Kolkata", clock=lambda: NOW), st


async def test_an_executed_write_becomes_a_done_row_with_its_audit_seq() -> None:
    rec, st = rig()
    await rec.on_event(event("executed"))
    [row] = await st.day("owner", "20261105")
    assert row.outcome == "done" and row.kind == "write" and row.words == "Add a to-do: milk"
    assert row.audit_seq == 7 and row.trace_id == "trace-1" and row.session_id == "sess-1"
    assert row.channel == "console" and row.offline is False and row.undo_id is None


async def test_every_outcome_maps_to_a_row_outcome() -> None:
    rec, st = rig()
    for o in ("executed", "error", "awaiting_confirmation", "denied", "declined"):
        await rec.on_event(event(o, result=None))
    rows = await st.day("owner", "20261105")
    assert sorted(r.outcome for r in rows) == ["declined", "done", "failed", "refused", "waiting"]


async def test_a_delete_with_an_undo_id_keeps_it() -> None:
    rec, st = rig()
    uid = "del_" + "a" * 20
    res = GatewayResult(GatewayOutcome.EXECUTED, result={"undo_id": uid, "kind": "event"})
    await rec.on_event(event("executed", "calendar_delete_event", result=res))
    [row] = await st.day("owner", "20261105")
    assert row.kind == "delete" and row.undo_id == uid


async def test_an_undo_id_from_a_failed_or_malformed_result_is_ignored() -> None:
    rec, st = rig()
    bad = GatewayResult(GatewayOutcome.EXECUTED, result={"undo_id": "../x", "kind": "event"})
    await rec.on_event(event("executed", "calendar_delete_event", result=bad))
    await rec.on_event(event("error", "calendar_delete_event", result=None))
    assert all(r.undo_id is None for r in await st.day("owner", "20261105"))


async def test_a_read_does_not_store_the_query() -> None:
    rec, st = rig()
    await rec.on_event(
        event("executed", "web_search", risk=R1, args={"query": "my secret illness"})
    )
    [row] = await st.day("owner", "20261105")
    assert row.words == "Searched the web" and "illness" not in row.model_dump_json()


async def test_channel_and_offline_come_from_the_turn() -> None:
    rec, st = rig()
    with channel.telegram_turn():
        channel.reset_offline()
        channel.mark_offline()
        await rec.on_event(event("executed"))
    channel.reset_offline()
    [row] = await st.day("owner", "20261105")
    assert row.channel == "telegram" and row.offline is True


async def test_a_scope_less_event_is_not_recorded() -> None:
    rec, st = rig()
    await rec.on_event(event("executed", scope=None))
    await rec.on_event(event("executed", scope="a/b:s"))
    assert await st.day("owner", "20261105") == []


async def test_declined_events_use_the_pending_scope_and_have_no_result() -> None:
    rec, st = rig()
    await rec.on_event(event("declined", "gmail_send", risk=R3, result=None, args={"to": "a@b"}))
    [row] = await st.day("owner", "20261105")
    assert row.outcome == "declined" and row.words == "You declined: Send an email to a@b"


async def test_a_store_failure_never_raises() -> None:
    class Down(MemoryDocs):
        async def write(self, ops: Any) -> None:
            raise RuntimeError("firestore down")

    rec = ActivityRecorder(ActivityStore(Down()), reg(), clock=lambda: NOW)
    await rec.on_event(event("executed"))  # no exception
    await notify([rec], event("executed"))


async def test_the_day_key_is_the_owners_local_day() -> None:
    late = datetime(2026, 11, 5, 20, 0, tzinfo=UTC)  # 01:30 on the 6th in India
    st = ActivityStore(MemoryDocs())
    rec = ActivityRecorder(st, reg(), timezone="Asia/Kolkata", clock=lambda: late)
    await rec.on_event(event("executed"))
    assert len(await st.day("owner", "20261106")) == 1
    assert await st.day("owner", "20261105") == []


async def test_a_card_and_the_call_it_became_share_a_call_key() -> None:
    rec, st = rig()
    await rec.on_event(event("awaiting_confirmation", result=None))
    await rec.on_event(event("executed"))
    rows = await st.day("owner", "20261105")
    assert len(rows) == 2 and len({r.call_key for r in rows}) == 1 and rows[0].call_key
