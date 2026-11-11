# tests/test_r11_d_blocks.py -- R11 Part D (plan D15, item 16): cooking and washing-up blocks.
# `calendar_kitchen_blocks` is R2 with `ask_when` always: whatever his rows say, it is an approval
# card through the gateway first, and only the approved card writes his primary calendar.
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from google_fakes import FakeGoogle
from r11_fakes import NOON_IST, UID
from r11_fakes_d import connector

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.helpers.kitchen.blocks import TOOL, blocks_tool, card_text
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

CAL = "https://www.googleapis.com/calendar/v3"
EVENTS = f"{CAL}/calendars/primary/events"
SCOPE = f"{UID}:sess_k"


def _made(summary: str) -> httpx.Response:
    me = {"email": "owner@example.com", "self": True}
    return httpx.Response(
        200,
        json={
            "id": f"ev{summary.lower().replace('-', '')}",
            "summary": summary,
            "start": {"dateTime": "2026-11-11T19:00:00+05:30"},
            "end": {"dateTime": "2026-11-11T19:45:00+05:30"},
            "organizer": me,
            "creator": me,
        },
    )


async def _gateway(*, allow: bool = True) -> tuple[Gateway, FakeGoogle]:
    fake = FakeGoogle()
    fake.on(
        "GET",
        f"{CAL}/users/me/calendarList/primary",
        httpx.Response(200, json={"timeZone": "Asia/Kolkata"}),
    )
    fake.on("POST", EVENTS, _made("Cooking"), _made("Washing-up"))
    conn = await connector(fake.client())
    reg = ToolRegistry()
    reg.register(blocks_tool(conn, tz="Asia/Kolkata", now=lambda: NOON_IST))
    rules = [PolicyRule(tool_pattern="calendar_*", effect=Effect.ALLOW)] if allow else []
    return Gateway(
        registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog()
    ), fake


async def _run(gw: Gateway, args: dict[str, Any], **kw: Any) -> GatewayResult:
    return await gw.execute(ToolCall(id="k", name=TOOL, arguments=args), scope=SCOPE, **kw)


def _posts(fake: FakeGoogle) -> list[dict[str, Any]]:
    return [json.loads(r.content) for r in fake.sent("POST", "/calendars/primary/events")]


async def test_the_tool_is_r2_and_always_asks() -> None:
    gw, _ = await _gateway()
    tool = gw.registry.get(TOOL)
    assert tool is not None and tool.risk is ActionRisk.REVERSIBLE and tool.agent == "google"
    assert tool.asks({}) and tool.asks({"only": "cooking"})


async def test_even_with_his_allow_it_is_a_card_and_nothing_is_written_before_approval() -> None:
    gw, fake = await _gateway(allow=True)
    out = await _run(gw, {})
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending is not None
    assert out.pending.summary == (
        "Add to your calendar, repeating every day from tomorrow: Cooking 19:00-19:45 and "
        "Washing-up 20:30-20:45. Only you are on them."
    )
    assert _posts(fake) == []


async def test_the_approved_card_adds_two_repeating_events_only_he_is_on() -> None:
    gw, fake = await _gateway()
    card = await _run(gw, {})
    assert card.pending is not None
    done = await _run(gw, {}, confirmation_id=card.pending.id)
    assert done.outcome is GatewayOutcome.EXECUTED, done.error
    cooking, washing = _posts(fake)
    assert cooking["summary"] == "Cooking" and washing["summary"] == "Washing-up"
    assert cooking["start"] == {"dateTime": "2026-11-11T19:00:00+05:30", "timeZone": "Asia/Kolkata"}
    assert cooking["end"]["dateTime"] == "2026-11-11T19:45:00+05:30"
    assert washing["start"]["dateTime"] == "2026-11-11T20:30:00+05:30"
    assert cooking["recurrence"] == ["RRULE:FREQ=DAILY"] and "attendees" not in cooking
    assert all(r.url.params["sendUpdates"] == "none" for r in fake.sent("POST", "/events"))
    assert done.result["message"].startswith("Added to your calendar, Sir: Cooking 19:00-19:45")


async def test_chosen_days_repeat_weekly_from_the_first_of_them() -> None:
    gw, fake = await _gateway()
    args = {"days": "fri, mon", "only": "cooking", "cooking_at": "18:30", "cooking_minutes": "60"}
    card = await _run(gw, args)
    assert card.pending is not None and "every Mon and Fri" in card.pending.summary
    await _run(gw, args, confirmation_id=card.pending.id)
    (only,) = _posts(fake)
    assert only["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,FR"]
    assert only["start"]["dateTime"] == "2026-11-13T18:30:00+05:30"  # Friday, the first of them
    assert only["end"]["dateTime"] == "2026-11-13T19:30:00+05:30"


async def test_bad_arguments_fail_before_any_card() -> None:
    gw, fake = await _gateway()
    for bad in (
        {"cooking_at": "25:00"},
        {"cooking_minutes": 2},
        {"days": "someday"},
        {"only": "lunch"},
        {"start": "2020-01-01"},
    ):
        out = await _run(gw, bad)
        assert out.outcome is GatewayOutcome.ERROR, bad
    assert fake.requests == []


async def test_a_card_proposed_after_reading_outside_content_writes_marked_outside() -> None:
    gw, fake = await _gateway()
    with context_trust(untrusted=True):
        card = await _run(gw, {"only": "washing_up"})
    assert card.pending is not None
    await _run(gw, {"only": "washing_up"}, confirmation_id=card.pending.id)
    (body,) = _posts(fake)
    assert body["extendedProperties"]["private"]  # tools.provenance.mark_outside


def test_the_card_text_is_written_by_code_from_the_arguments() -> None:
    assert card_text({"only": "washing_up", "start": "2026-12-01", "days": "sat,sun"}) == (
        "Add to your calendar, repeating every Sat and Sun from 1 Dec 2026: "
        "Washing-up 20:30-20:45. Only you are on them."
    )


async def test_a_second_block_that_fails_is_said_and_logged(caplog: Any) -> None:  # code L1
    fake = FakeGoogle()
    tz = httpx.Response(200, json={"timeZone": "Asia/Kolkata"})
    fake.on("GET", f"{CAL}/users/me/calendarList/primary", tz)
    fake.on("POST", EVENTS, _made("Cooking"), httpx.Response(500, json={"error": {}}))
    reg = ToolRegistry()
    reg.register(
        blocks_tool(await connector(fake.client()), tz="Asia/Kolkata", now=lambda: NOON_IST)
    )
    rules = [PolicyRule(tool_pattern="calendar_*", effect=Effect.ALLOW)]
    gw = Gateway(registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog())
    card = await _run(gw, {})
    assert card.pending is not None
    with caplog.at_level(logging.WARNING):
        done = await _run(gw, {}, confirmation_id=card.pending.id)
    assert "Washing-up couldn't be added just now" in done.result["message"]
    got = [r for r in caplog.records if r.getMessage() == "a kitchen block wasn't added"]
    assert got and getattr(got[0], "error", None) in ("GoogleAPIError", "GoogleUncertain")


async def test_a_start_that_is_past_in_the_calendars_zone_moves_to_its_today() -> None:  # L2
    late = datetime(2026, 11, 10, 23, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # 11 Nov in Kiritimati
    fake = FakeGoogle()
    tz = httpx.Response(200, json={"timeZone": "Pacific/Kiritimati"})
    fake.on("GET", f"{CAL}/users/me/calendarList/primary", tz)
    fake.on("POST", EVENTS, _made("Cooking"))
    reg = ToolRegistry()
    reg.register(blocks_tool(await connector(fake.client()), tz="Asia/Kolkata", now=lambda: late))
    rules = [PolicyRule(tool_pattern="calendar_*", effect=Effect.ALLOW)]
    gw = Gateway(registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog())
    args = {"only": "cooking", "start": "2026-11-10"}  # today in his configured zone
    card = await _run(gw, args)
    assert card.pending is not None
    await _run(gw, args, confirmation_id=card.pending.id)
    (only,) = _posts(fake)
    assert only["start"]["dateTime"].startswith("2026-11-11T19:00")
