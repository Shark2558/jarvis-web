# tests/test_tasks_hardening.py — slice 10 C security-review fixes for the to-do tools:
# M2 (overflowing dates), M3 (assigned tasks are others' business; subtasks on delete),
# L6 (an overall deadline), L7 (the Tasks API switched off in the project).
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr
from tasks_fakes import FakeTasks, link

from jarvis.core.guardrails import ConfirmationGate
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.base import ToolCall
from jarvis.tools import google_tasks
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.google_tasks import tasks_tools
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.tasks_api import parse_due

SCOPE = "u_owner:sess_1"
NOW = datetime(2027, 1, 15, 3, 0, tzinfo=UTC)
DOC = {"surfaceType": "DOCUMENT"}


async def _gw(fake: FakeTasks, handler: Any = None) -> Gateway:
    store = MemoryTokenStore()
    await store.put("u_owner", link())
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler or fake.handler))
    conn = GoogleConnector(store, client_id="c", client_secret=SecretStr("s"), http=client)
    reg = ToolRegistry()
    for t in tasks_tools(conn, default_tz="Asia/Kolkata", clock=lambda: NOW):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def _run(gw: Gateway, name: str, args: dict[str, Any]) -> GatewayResult:
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)


def _fake() -> FakeTasks:
    fake = FakeTasks()
    fake.add("L1", "Call plumber", id="t_mine", due="2027-01-15")
    fake.add("L1", "Fix clause 4", id="t_doc", due="2027-01-16", assignmentInfo=DOC)
    fake.add("L1", "Plan offsite", id="t_parent")
    fake.add("L1", "Book venue", id="t_child1", parent="t_parent")
    fake.add("L1", "Send invites", id="t_child2", parent="t_parent")
    return fake


# ---- M2: a date that cannot be converted is a plain error, never an escaping exception ----------


@pytest.mark.parametrize(
    "value",
    ["0001-01-01T00:00:01+10:00", "9999-12-31T23:59:59-10:00", "0001-01-01T05:00:00"],
)
def test_dates_at_the_edge_of_time_are_a_plain_value_error(value: str) -> None:
    with pytest.raises(ValueError):
        parse_due(value, ZoneInfo("Pacific/Kiritimati"))


async def test_an_overflowing_due_date_is_refused_through_the_gateway() -> None:
    fake = _fake()
    gw = await _gw(fake)
    for name, args in (
        ("task_add", {"title": "x", "due": "0001-01-01T00:00:01+10:00"}),
        ("tasks_list", {"due_before": "9999-12-31T23:59:59-10:00"}),
    ):
        out = await _run(gw, name, args)
        assert out.outcome is GatewayOutcome.ERROR and "due" in str(out.error)
    assert fake.mutations == []


# ---- M3: an assigned task is visible to the people in its Doc / Chat space ----------------------


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("task_complete", {"task_id": "L1:t_doc"}),
        ("task_update", {"task_id": "L1:t_doc", "title": "Clause 4 done"}),
    ],
)
async def test_changing_an_assigned_task_waits_for_the_owner(
    name: str, args: dict[str, Any]
) -> None:
    fake = _fake()
    out = await _run(await _gw(fake), name, args)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending is not None
    assert "Assigned from a Google Doc or Chat space" in out.pending.summary
    assert "people there can see" in out.pending.summary
    assert fake.mutations == []


async def test_changing_the_owners_own_task_still_runs_straight_away() -> None:
    fake = _fake()
    out = await _run(await _gw(fake), "task_complete", {"task_id": "L1:t_mine"})
    assert out.outcome is GatewayOutcome.EXECUTED and fake.changes("complete")


async def test_deleting_a_task_with_subtasks_says_they_may_go_too() -> None:
    fake = _fake()
    held = await _run(await _gw(fake), "task_delete", {"task_id": "L1:t_parent"})
    assert held.pending is not None
    card = held.pending.summary
    assert "2 subtasks" in card and "may be deleted with it" in card
    plain = await _run(await _gw(fake), "task_delete", {"task_id": "L1:t_mine"})
    assert plain.pending is not None and "subtask" not in plain.pending.summary


async def test_the_subtask_check_failing_proposes_nothing() -> None:
    fake = _fake()
    fake.fail["tasks"] = 500
    out = await _run(await _gw(fake), "task_delete", {"task_id": "L1:t_parent"})
    assert out.outcome is GatewayOutcome.ERROR and "nothing was proposed" in str(out.error)


# ---- L6: an overall deadline on the list ---------------------------------------------------------


async def test_a_slow_google_is_cut_off_by_the_list_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake()
    monkeypatch.setattr(google_tasks, "LIST_DEADLINE_S", 0.2)

    async def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tasks"):
            await asyncio.sleep(5)
        return fake.handler(request)

    gw = await _gw(fake, slow)
    started = asyncio.get_running_loop().time()
    out = await _run(gw, "tasks_list", {})
    assert asyncio.get_running_loop().time() - started < 2
    assert out.outcome is GatewayOutcome.ERROR and "too long" in str(out.error)


# ---- L7: the Tasks API switched off in the Cloud project -------------------------------------


async def test_the_tasks_api_switched_off_says_so_plainly() -> None:
    fake = _fake()
    disabled = {
        "error": {
            "code": 403,
            "message": "Google Tasks API has not been used in project 123 or it is disabled.",
            "status": "PERMISSION_DENIED",
            "errors": [{"reason": "accessNotConfigured", "domain": "usageLimits"}],
            "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED"}
            ],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/tasks/"):
            fake.requests.append(request)
            return httpx.Response(403, json=disabled)
        return fake.handler(request)

    gw = await _gw(fake, handler)
    out = await _run(gw, "tasks_list", {})
    assert out.outcome is GatewayOutcome.ERROR
    msg = str(out.error)
    assert "to-do service is not switched on for your JARVIS project yet" in msg
    assert "reconnect" not in msg.lower() and "project 123" not in msg  # no vendor text
    held = await _run(gw, "task_delete", {"task_id": "L1:t_mine"})
    assert "not switched on" in str(held.error) and await gw.pending() == []


async def test_the_connector_tells_a_switched_off_api_from_a_missing_scope() -> None:
    from jarvis.integrations.google import SERVICE_OFF_MSG, GoogleAPIError, GoogleServiceDisabled

    def handler(request: httpx.Request) -> httpx.Response:
        reason = "SERVICE_DISABLED" if request.url.path == "/off" else "forbidden"
        body = {"error": {"message": "secret vendor words", "details": [{"reason": reason}]}}
        return httpx.Response(403, json=body)

    store = MemoryTokenStore()
    await store.put("u_owner", link())
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    conn = GoogleConnector(store, client_id="c", client_secret=SecretStr("s"), http=client)
    with pytest.raises(GoogleServiceDisabled) as off:
        await conn.request("u_owner", "GET", "https://x.googleapis.com/off")
    assert str(off.value) == SERVICE_OFF_MSG and "vendor" not in str(off.value)
    with pytest.raises(GoogleAPIError) as denied:
        await conn.request("u_owner", "GET", "https://x.googleapis.com/on")
    assert not isinstance(denied.value, GoogleServiceDisabled)
    assert "missing permission" in str(denied.value)


async def test_a_plain_permission_403_still_says_permission() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/tasks/"):
            body = {"error": {"code": 403, "errors": [{"reason": "insufficientPermissions"}]}}
            return httpx.Response(403, json=body)
        return _fake().handler(request)

    out = await _run(await _gw(_fake(), handler), "tasks_list", {})
    assert "missing permission" in str(out.error) and "not switched on" not in str(out.error)
