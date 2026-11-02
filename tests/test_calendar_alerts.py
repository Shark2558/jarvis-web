# tests/test_calendar_alerts.py — slice 11 B (D4): pop-up alerts on events (`reminders_minutes`),
# the reminder tag, and free time that ignores reminders (against the in-memory slice 6 Google).
# Written before the implementation.
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from google_fakes import GOOGLE_UID, FakeGoogle, google_tokens
from pydantic import SecretStr

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.calendar_alerts import (
    REMINDER_FILTER,
    alert_minutes,
    alerts_label,
    event_alerts,
    is_reminder,
    minutes_label,
    reminder_text,
)
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.google_calendar import calendar_tools
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reminders import reminder_tools

CAL = "https://www.googleapis.com/calendar/v3"
EVENTS = f"{CAL}/calendars/primary/events"
TZ_URL = f"{CAL}/users/me/calendarList/primary"
SCOPE = f"{GOOGLE_UID}:sess_1"
ROOT = Path(__file__).resolve().parents[1]


def _slice6_fake() -> Any:
    """evals/slice6/fake_google.py — the in-memory Calendar the eval harnesses use."""
    name = "slice6_fake_google"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "evals" / "slice6" / "fake_google.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod  # dataclasses resolve annotations through sys.modules
        spec.loader.exec_module(mod)
    return sys.modules[name].FakeGoogleServer.from_fixture(
        str(ROOT / "evals" / "slice6" / "fixture_calendar.json")
    )


# ---- pure helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("minutes", "label"),
    [
        (0, "at the time"),
        (1, "1 minute before"),
        (30, "30 minutes before"),
        (60, "1 hour before"),
        (90, "90 minutes before"),
        (120, "2 hours before"),
        (1440, "1 day before"),
        (2880, "2 days before"),
        (10080, "1 week before"),
        (40320, "4 weeks before"),
    ],
)
def test_minutes_label_reads_naturally(minutes: int, label: str) -> None:
    assert minutes_label(minutes) == label


def test_alert_minutes_validates_dedupes_and_sorts() -> None:
    assert alert_minutes([30, 10, 30]) == [10, 30]
    assert alert_minutes([]) == []
    assert alerts_label([10, 60]) == "10 minutes before, 1 hour before"
    assert alerts_label([]) == "no alerts"
    for bad in ([1, 2, 3, 4, 5, 6], [-1], [40_321], ["30"], [True], "30", None, [1.5]):
        with pytest.raises(ValueError, match="reminders_minutes"):
            alert_minutes(bad)


def test_the_reminder_tag_and_text() -> None:
    tagged = {"extendedProperties": {"private": {"jarvis": "reminder"}}, "summary": "⏰ call"}
    assert is_reminder(tagged) and reminder_text(tagged["summary"]) == "call"
    assert reminder_text("call") == "call" and reminder_text(None) == ""
    assert not is_reminder({"extendedProperties": {"shared": {"jarvis": "reminder"}}})
    assert not is_reminder({"extendedProperties": {"private": {"jarvis": "other"}}})
    assert not is_reminder({"extendedProperties": "junk"}) and not is_reminder({})
    assert REMINDER_FILTER == "jarvis=reminder"


def test_event_alerts_describes_what_an_event_has_now() -> None:
    assert event_alerts({}) == "calendar default"
    assert event_alerts({"reminders": {"useDefault": True}}) == "calendar default"
    assert event_alerts({"reminders": {"useDefault": False}}) == "no alerts"
    both = {
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "email", "minutes": 60}, {"method": "popup", "minutes": 10}],
        }
    }
    assert event_alerts(both) == "10 minutes before, 1 hour before (email)"


# ---- reminders_minutes on the event tools -------------------------------------------------------


@pytest.fixture
def gw(connected: GoogleConnector, fake_google: FakeGoogle) -> Gateway:
    fake_google.on("GET", TZ_URL, httpx.Response(200, json={"timeZone": "Asia/Kolkata"}))
    reg = ToolRegistry()
    for t in calendar_tools(connected):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def _run(gw: Gateway, name: str, args: dict[str, Any], **kw: Any) -> GatewayResult:
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE, **kw)


def _event(eid: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": eid,
        "summary": "Budget review",
        "start": {"dateTime": "2027-01-15T15:00:00+05:30"},
        "end": {"dateTime": "2027-01-15T16:00:00+05:30"},
        "organizer": {"email": "akash@example.com"},
        **extra,
    }


SLOT = {"start": "2027-01-15T15:00:00", "end": "2027-01-15T16:00:00"}
POPUPS = {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]}


async def test_create_with_alerts_stays_r2_and_sends_popup_overrides(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("POST", EVENTS, httpx.Response(200, json=_event("evnew1")))
    args = {"summary": "Focus", **SLOT, "reminders_minutes": [30, 10, 30]}
    out = await _run(gw, "calendar_create_event", args)
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    body = json.loads(fake_google.sent("POST", "/calendars/primary/events")[0].content)
    assert body["reminders"] == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": 10}, {"method": "popup", "minutes": 30}],
    }
    tool = gw.registry.get("calendar_create_event")
    assert tool is not None and tool.effective_risk(args) is ActionRisk.REVERSIBLE
    assert "reminders_minutes" in tool.input_schema["properties"]


async def test_create_without_alerts_keeps_the_calendar_default(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("POST", EVENTS, httpx.Response(200, json=_event("evnew2")))
    out = await _run(gw, "calendar_create_event", {"summary": "Focus", **SLOT})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert "reminders" not in json.loads(fake_google.sent("POST", "/events")[0].content)


async def test_an_empty_alert_list_means_no_alerts(gw: Gateway, fake_google: FakeGoogle) -> None:
    fake_google.on("POST", EVENTS, httpx.Response(200, json=_event("evnew3")))
    out = await _run(gw, "calendar_create_event", {"summary": "x", **SLOT, "reminders_minutes": []})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    body = json.loads(fake_google.sent("POST", "/events")[0].content)
    assert body["reminders"] == {"useDefault": False, "overrides": []}


async def test_invite_card_shows_the_alerts(gw: Gateway, fake_google: FakeGoogle) -> None:
    args = {
        "summary": "Sync",
        **SLOT,
        "attendees": ["priya@example.com"],
        "reminders_minutes": [10, 60],
    }
    out = await _run(gw, "calendar_create_event", args)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending is not None
    assert "Alerts: 10 minutes before, 1 hour before" in out.pending.summary.split("\n")


@pytest.mark.parametrize("bad", [[1, 2, 3, 4, 5, 6], [-1], [40_321], ["30"], [True], 30])
async def test_bad_alerts_are_refused_before_google(
    gw: Gateway, fake_google: FakeGoogle, bad: Any
) -> None:
    for name, args in (
        ("calendar_create_event", {"summary": "x", **SLOT, "reminders_minutes": bad}),
        ("calendar_update_event", {"event_id": "evsolo1", "reminders_minutes": bad}),
    ):
        out = await _run(gw, name, args)
        assert out.outcome is GatewayOutcome.ERROR and "reminders_minutes" in (out.error or "")
    assert fake_google.requests == []


async def test_alert_on_my_own_meeting_is_r2_and_patches_only_the_alerts(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("GET", f"{EVENTS}/evsolo1", httpx.Response(200, json=_event("evsolo1")))
    fake_google.on(
        "PATCH", f"{EVENTS}/evsolo1", httpx.Response(200, json=_event("evsolo1", reminders=POPUPS))
    )
    out = await _run(
        gw, "calendar_update_event", {"event_id": "evsolo1", "reminders_minutes": [30]}
    )
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    body = json.loads(fake_google.sent("PATCH", "/events/evsolo1")[0].content)
    assert body == {"reminders": POPUPS}


async def test_alert_on_a_meeting_with_guests_stays_r3_and_the_card_shows_the_change(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    shared = _event(
        "evshared1",
        attendees=[{"email": "akash@example.com", "self": True}, {"email": "fin@example.com"}],
    )
    fake_google.on("GET", f"{EVENTS}/evshared1", httpx.Response(200, json=shared))
    out = await _run(
        gw, "calendar_update_event", {"event_id": "evshared1", "reminders_minutes": [30]}
    )
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending is not None
    assert out.pending.tool_risk is ActionRisk.IRREVERSIBLE
    assert "• alerts: calendar default → 30 minutes before" in out.pending.summary.split("\n")
    assert fake_google.sent("PATCH", "/events/evshared1") == []


# ---- free time ignores reminders (the in-memory Google models freeBusy's transparency) ----------


async def _fake_gw(server: Any) -> Gateway:
    store = MemoryTokenStore()
    await store.put(GOOGLE_UID, google_tokens(expires_at=4_000_000_000.0))
    conn = GoogleConnector(store, client_id="c", client_secret=SecretStr("s"), http=server.client())
    reg = ToolRegistry()
    now = datetime(2027, 1, 15, 3, 0, tzinfo=UTC)  # 08:30 in India
    for t in calendar_tools(conn) + reminder_tools(conn, clock=lambda: now):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


FREE = {
    "start": "2027-01-15T12:00:00",
    "end": "2027-01-15T18:00:00",
    "duration_min": 60,
    "working_hours": "09:00-18:00",
}


@pytest.mark.parametrize(
    ("transparent", "slots"),
    [
        (True, [("12:00", "18:00")]),
        (False, [("12:00", "15:00"), ("15:05", "18:00")]),  # control: an opaque one would block
    ],
)
async def test_free_slots_are_unaffected_by_a_reminder(
    transparent: bool, slots: list[tuple[str, str]]
) -> None:
    server = _slice6_fake()
    gw = await _fake_gw(server)
    made = await _run(gw, "reminder_add", {"text": "call Ravi", "when": "2027-01-15T15:00:00"})
    assert made.outcome is GatewayOutcome.EXECUTED, made.error
    if not transparent:
        server.events[made.result["id"]]["transparency"] = "opaque"
    out = await _run(gw, "calendar_free_slots", FREE)
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    got = [(s["start"][11:16], s["end"][11:16]) for s in out.result["slots"]]
    assert got == slots


async def test_reminders_list_returns_only_tagged_events_from_the_fake() -> None:
    server = _slice6_fake()
    gw = await _fake_gw(server)
    made = await _run(gw, "reminder_add", {"text": "call Ravi", "when": "2027-01-15T17:00:00"})
    assert made.outcome is GatewayOutcome.EXECUTED, made.error
    out = await _run(gw, "reminders_list", {})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert [r["id"] for r in out.result["reminders"]] == [made.result["id"]]
    listed = await _run(
        gw,
        "calendar_list_events",
        {"start": "2027-01-15T00:00:00", "end": "2027-01-16T00:00:00"},
    )
    assert len(listed.result["events"]) > 1  # the fixture's own events are there, untagged
