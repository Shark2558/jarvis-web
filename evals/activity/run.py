# evals/activity/run.py
"""R1 B eval harness -- Activity with one-tap Undo (plan D7/D8), mock only, no network, no model.

Usage:
    python evals/activity/run.py            # mock (CI)
    python evals/activity/run.py --mock     # same (run_all_mock passes it)
    python evals/activity/run.py --only a07,a09

The REAL Gateway, audit, Recently deleted bin, ActivityRecorder (as the gateway's observer) and
ActivityService, with small scripted tools. Each case builds a fresh rig and checks what the owner
would see in the Activity view.
Cases (gate: 100 %): executed / waiting / refused / declined rows with the right words; reads show
no query text; another owner's rows never shown; Undo restores a delete (row -> Restored, plus a
"You restored" row); an expired or purged item has no button; an undo id from a tool that is not a
bin delete gets no button; an add or a send gets the right reason; a waiting row goes once the card
is approved; reads are grouped; a failing store never fails the tool call.
Negative controls (each MUST make the suite fail): (A) the observer switched off -> no rows;
(B) every undo id treated as restorable -> expired / unknown / non-bin ids get a button.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jarvis.activity import ActivityRecorder, ActivityService, ActivityStore
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, PendingAction
from jarvis.llm.base import ToolCall
from jarvis.logging import configure_logging
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.undo.models import DeletedItem
from jarvis.undo.service import Restored, UndoBin
from jarvis.undo.store import DeletedStore

HERE = Path(__file__).parent
R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
ME, OTHER = "owner", "someone_else"
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
FAKE_UNDO = "del_" + "9" * 20


class Restorer:
    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Restored:
        return Restored(new_id="new1")


class Rig:
    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self.undo = UndoBin(DeletedStore(MemoryDocs()), clock=lambda: NOW)
        self.undo.register("event", Restorer())
        self.store = ActivityStore(MemoryDocs())
        self.reg = ToolRegistry()
        for t in self._tools():
            self.reg.register(t)
        self.gw = Gateway(
            registry=self.reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog()
        )
        self.gw.observers = [ActivityRecorder(self.store, self.reg, clock=lambda: NOW)]
        self.svc = ActivityService(self.store, self.undo, clock=lambda: NOW)

    def _tools(self) -> list[Tool]:
        undo = self.undo

        async def search(args: dict[str, Any]) -> dict[str, Any]:
            return {"hits": []}

        async def add(args: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        async def fake_add(args: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "undo_id": FAKE_UNDO, "kind": "event"}  # not a bin delete

        async def send(args: dict[str, Any]) -> dict[str, Any]:
            return {"sent": True}

        async def delete(args: dict[str, Any]) -> dict[str, Any]:
            item = await undo.keep("owner", "event", args["title"], {"summary": args["title"]})
            return {"deleted": True, "undo_id": item.id, "kind": "event"}

        def tool(name: str, risk: ActionRisk, run: Any, tpl: str) -> Tool:
            schema = {"type": "object", "properties": {"title": {}, "query": {}, "to": {}}}
            return Tool(name, "d", schema, risk, run, summary_template=tpl)

        return [
            tool("gmail_search", R1, search, "Search mail for {query}"),
            tool("task_add", R2, add, "Add a to-do: {title}"),
            tool("buggy_add", R2, fake_add, "Add an event: {title}"),
            tool("gmail_send", R3, send, "Send an email to {to}"),
            tool("calendar_delete_event", R2, delete, "Delete the event {title}"),
        ]

    async def call(self, name: str, uid: str = ME, **args: Any) -> Any:
        return await self.gw.execute(
            ToolCall(id="c", name=name, arguments=args), scope=f"{uid}:sess1"
        )

    async def rows(self, uid: str = ME) -> list[Any]:
        return (await self.svc.view(uid, "today")).items


Check = Callable[[bool, str], None]
CASES: dict[str, tuple[str, Callable[[Check], Awaitable[None]]]] = {}


def case(cid: str, why: str) -> Callable[[Callable[[Check], Awaitable[None]]], Any]:
    def deco(fn: Callable[[Check], Awaitable[None]]) -> Callable[[Check], Awaitable[None]]:
        CASES[cid] = (why, fn)
        return fn

    return deco


@case("a01", "an executed write is a done row in the tool's own words")
async def a01(ck: Check) -> None:
    rig = Rig()
    await rig.call("task_add", title="milk")
    [r] = await rig.rows()
    ck(r.outcome == "done" and r.words == "Add a to-do: milk", f"row {r.words!r} {r.outcome}")
    ck(r.undo is None and "Can't be undone from here" in r.undo_note, "no undo, a reason")


@case("a02", "a card waiting for approval is a waiting row")
async def a02(ck: Check) -> None:
    rig = Rig()
    await rig.call("gmail_send", to="a@b.com")
    [r] = await rig.rows()
    ck(r.outcome == "waiting" and r.words.startswith("Waiting for your OK: "), r.words)
    ck(r.undo_note == "Nothing has happened yet", r.undo_note)


@case("a03", "a call the owner's rules refuse is a refused row")
async def a03(ck: Check) -> None:
    deny = PolicyRule(tool_pattern="task_*", effect=Effect.DENY, source="owner:x", reason="no")
    rig = Rig([deny])
    await rig.call("task_add", title="milk")
    [r] = await rig.rows()
    ck(r.outcome == "refused" and r.words.startswith("Blocked by your settings"), r.words)


@case("a04", "a declined card is a declined row")
async def a04(ck: Check) -> None:
    rig = Rig()
    res = await rig.call("gmail_send", to="a@b.com")
    action: PendingAction = res.pending
    entry = await rig.gw.audit.append(
        agent="core", tool="gmail_send", risk=R3, outcome="declined", args=action.arguments
    )
    await rig.gw.observe_declined(action, entry)
    outcomes = sorted(r.outcome for r in await rig.rows())
    ck(outcomes == ["declined"], f"{outcomes}")  # the waiting row is gone once it is decided


@case("a05", "a read shows a fixed verb and never the query")
async def a05(ck: Check) -> None:
    rig = Rig()
    await rig.call("gmail_search", query="my oncologist results")
    [r] = await rig.rows()
    ck(r.words == "Searched your email", r.words)
    ck("oncologist" not in (await rig.svc.view(ME)).model_dump_json(), "query text leaked")


@case("a06", "another owner's rows are never shown")
async def a06(ck: Check) -> None:
    rig = Rig()
    await rig.call("task_add", uid=OTHER, title="secret")
    ck(await rig.rows(ME) == [], "owner saw someone else's row")
    ck(len(await rig.rows(OTHER)) == 1, "the other owner lost their row")


@case("a07", "a delete gets Undo; Undo restores it, the row reads Restored, a restore row appears")
async def a07(ck: Check) -> None:
    rig = Rig()
    await rig.call("calendar_delete_event", title="Dentist")
    [r] = await rig.rows()
    ck(r.undo is not None and r.undo.state == "available", "no Undo on a bin delete")
    if r.undo is None:
        return
    out = await rig.undo.restore(ME, r.undo.id)
    await rig.svc.record_restore(ME, out, session_id=None)
    rows = await rig.rows()
    states = [x.undo.state for x in rows if x.undo]
    ck(states == ["restored"], f"states {states}")
    ck(any(x.words.startswith("You restored the event") for x in rows), "no restore row")


@case("a08", "an expired bin item has no button and says why")
async def a08(ck: Check) -> None:
    rig = Rig()
    await rig.call("calendar_delete_event", title="Dentist")
    [r] = await rig.rows()
    item = await rig.undo.store.get(ME, r.undo.id)  # type: ignore[union-attr]
    assert item is not None
    old = item.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    await rig.undo.store.remove(ME, [item.id])
    await rig.undo.store.add(old)
    [r2] = await rig.rows()
    ck(r2.undo is not None and r2.undo.state == "expired", f"{r2.undo}")
    ck("Recently deleted" in r2.undo_note, r2.undo_note)


@case("a09", "an undo id that is not in the bin (a non-bin tool's result) gets no button")
async def a09(ck: Check) -> None:
    rig = Rig()
    await rig.call("buggy_add", title="x")
    [r] = await rig.rows()
    ck(r.undo is None, f"button for a non-delete: {r.undo}")
    await rig.call("calendar_delete_event", title="Dentist")
    rows = await rig.rows()
    ck(sum(1 for x in rows if x.undo and x.undo.state == "available") == 1, "wrong button count")


@case("a10", "a purged bin item has no button")
async def a10(ck: Check) -> None:
    rig = Rig()
    await rig.call("calendar_delete_event", title="Dentist")
    [r] = await rig.rows()
    await rig.undo.purge(ME, r.undo.id)  # type: ignore[union-attr]
    [r2] = await rig.rows()
    ck(r2.undo is not None and r2.undo.state == "gone", f"{r2.undo}")


@case("a11", "an approved send says it can't be undone; the waiting row is gone")
async def a11(ck: Check) -> None:
    rig = Rig()
    first = await rig.call("gmail_send", to="a@b.com")
    done = await rig.gw.execute(
        ToolCall(id="c", name="gmail_send", arguments={"to": "a@b.com"}),
        scope=f"{ME}:sess1",
        confirmation_id=first.pending.id,
    )
    ck(done.outcome is GatewayOutcome.EXECUTED, "the approved send did not run")
    rows = await rig.rows()
    ck(len(rows) == 1 and rows[0].outcome == "done", f"{[(x.outcome, x.words) for x in rows]}")
    ck("Sent" in rows[0].undo_note and "can't be undone" in rows[0].undo_note, rows[0].undo_note)


@case("a12", "reads of one tool in one request are grouped")
async def a12(ck: Check) -> None:
    rig = Rig()
    for q in ("a", "b", "c"):
        await rig.call("gmail_search", query=q)
    rows = await rig.rows()
    ck(
        len(rows) == 1 and rows[0].words == "Searched your email \u00b7 3 times",
        f"{[x.words for x in rows]}",
    )


@case("a13", "a failing Activity store never fails the tool call")
async def a13(ck: Check) -> None:
    rig = Rig()

    class Down(MemoryDocs):
        async def write(self, ops: Any) -> None:
            raise RuntimeError("down")

    rig.gw.observers[0].store = ActivityStore(Down())  # type: ignore[attr-defined]
    res = await rig.call("task_add", title="milk")
    ck(res.outcome is GatewayOutcome.EXECUTED, "the tool call failed with the store")


@case("a14", "hostile words are one clean line")
async def a14(ck: Check) -> None:
    rig = Rig()
    await rig.call("task_add", title="x\n\u202e<script>alert(1)</script>" + "y" * 500)
    [r] = await rig.rows()
    ck("\n" not in r.words and "\u202e" not in r.words and len(r.words) <= 300, "unclean words")


@contextmanager
def control_observer_off() -> Any:
    original = Rig.__init__

    def rig_init(self: Rig, rules: list[PolicyRule] | None = None) -> None:
        original(self, rules)
        self.gw.observers = []

    Rig.__init__ = rig_init  # type: ignore[method-assign]
    try:
        yield
    finally:
        Rig.__init__ = original  # type: ignore[method-assign]


@contextmanager
def control_every_undo_id_restorable() -> Any:
    original = ActivityService._undo_state

    async def always(self: ActivityService, uid: str, undo_id: str) -> str:
        return "available"

    ActivityService._undo_state = always  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        ActivityService._undo_state = original  # type: ignore[method-assign]


async def run_case(cid: str) -> dict[str, Any]:
    why, fn = CASES[cid]
    failures: list[str] = []

    def ck(ok: bool, msg: str) -> None:
        if not ok:
            failures.append(msg)

    try:
        await fn(ck)
    except Exception as exc:  # noqa: BLE001 - a crash is a failure of that case
        failures.append(f"crashed: {type(exc).__name__}: {exc}")
    return {"id": cid, "why": why, "passed": not failures, "failures": failures}


async def run_all(ids: list[str]) -> list[dict[str, Any]]:
    return [await run_case(c) for c in ids]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="default; kept for run_all_mock")
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    args = ap.parse_args()
    configure_logging("CRITICAL", False)
    ids = [c for c in CASES if not args.only or c in args.only.split(",")]
    results = await run_all(ids)
    print("\nACTIVITY (plain words, Undo only where the bin can restore)")
    for r in results:
        why = f"  <- {'; '.join(r['failures'])}" if r["failures"] else ""
        print(f"  {r['id']:4} {'PASS' if r['passed'] else 'FAIL'}  {r['why']}{why}")
    rate = sum(r["passed"] for r in results) / len(results) if results else 0.0
    controls: dict[str, int] = {}
    with control_observer_off():
        controls["observer_off"] = sum(not r["passed"] for r in await run_all(ids))
    with control_every_undo_id_restorable():
        controls["every_undo_id_restorable"] = sum(not r["passed"] for r in await run_all(ids))
    blind = not args.only and (
        controls["observer_off"] < 8 or controls["every_undo_id_restorable"] < 2
    )
    gate = rate == 1 and len(results) >= (14 if not args.only else 1) and not blind
    print(f"activity: {rate:.0%} ({len(results)} cases, gate 100%) -> {'PASS' if gate else 'FAIL'}")
    for name, n in controls.items():
        print(f"  negative control ({name}): {n} case(s) fail")
    report = {
        "mode": "mock",
        "gate": gate,
        "suites": {
            "activity": {
                "pass_rate": rate,
                "cases": len(results),
                "negative_controls": controls,
                "gate": gate,
                "results": results,
            }
        },
    }
    (HERE / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nGATE:", "PASS" if gate else "FAIL")
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
