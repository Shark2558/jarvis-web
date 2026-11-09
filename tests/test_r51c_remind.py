# tests/test_r51c_remind.py -- R5.1 D8 (docs/plans/r5-1-observations.md): "Set a reminder" from the
# systems-check pop-up. POST /v1/health/remind {key, when} builds the text from the FIXED label and
# consequence and runs `reminder_add` through the gateway (owner-trusted, no model call); Google
# not connected -> refused with no call; a key that is not a current concern -> 422.
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, Request
from health_fakes import UID, Clock, fixed
from httpx import ASGITransport, AsyncClient
from r51c_fakes import GatewayFake, GoogleFake, VitalsFake, board, view

from jarvis.health.api import RUN_PER_MINUTE, health_router
from jarvis.health.remind import CONSOLE_SESSION, RemindDeps, when_at
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.gateway import GatewayOutcome, GatewayResult

IST = ZoneInfo("Asia/Kolkata")
NOON = datetime(2026, 11, 10, 12, 41, 30, tzinfo=IST)
NIGHT = datetime(2026, 11, 10, 18, 0, 0, tzinfo=IST)
TEXT = "Fix Telegram: alerts and Telegram chat won't reach you"


# ---- when ----------------------------------------------------------------------------------------
def test_in_one_hour_is_to_the_minute() -> None:
    at, said = when_at("1h", NOON)
    assert at.isoformat() == "2026-11-10T13:41:00+05:30" and said == "today, 13:41"


def test_this_evening_is_six_pm_today_or_tomorrow_once_past() -> None:
    at, said = when_at("evening", NOON)
    assert at.isoformat() == "2026-11-10T18:00:00+05:30" and said == "this evening, 18:00"
    at, said = when_at("evening", NIGHT)
    assert at.isoformat() == "2026-11-11T18:00:00+05:30" and said == "tomorrow evening, 18:00"


def test_tomorrow_is_ten_am() -> None:
    at, said = when_at("tomorrow", NOON)
    assert at.isoformat() == "2026-11-11T10:00:00+05:30" and said == "tomorrow, 10:00"


def test_an_hour_past_eleven_pm_is_tomorrow() -> None:
    late = datetime(2026, 11, 10, 23, 30, tzinfo=IST)
    assert when_at("1h", late)[1] == "tomorrow, 00:30"


# ---- the route -----------------------------------------------------------------------------------
class World:
    def __init__(
        self,
        *,
        gateway: GatewayFake | None = None,
        google: GoogleFake | None = None,
        vitals: Any = None,
        down: str = "telegram",
        default_deps: bool = False,
    ) -> None:
        self.gateway = gateway if gateway is not None else GatewayFake()
        self.google = google if google is not None else GoogleFake()
        self.svc = HealthService(
            [fixed("redis", "Redis", "ok"), fixed(down, down, "down")],
            HealthStore(MemoryDocs(), prefix="jarvis_"),
            vitals=vitals,
            clock=Clock(),
        )
        self.app = FastAPI()

        def deps(_req: Request) -> RemindDeps:
            return RemindDeps(
                gateway=self.gateway, google=self.google, tz="Asia/Kolkata", now=lambda: NOON
            )

        self.app.include_router(
            health_router(self.svc, user=lambda: UID, remind_deps=None if default_deps else deps)
        )

    async def post(self, body: Any, path: str = "/v1/health/remind") -> Any:
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://t") as c:
            return await c.post(path, json=body)


async def checked(w: World) -> World:
    await w.svc.check(UID, force=True)
    return w


async def test_a_reminder_is_set_through_the_gateway_with_fixed_words() -> None:
    w = await checked(World())
    r = await w.post({"key": "telegram", "when": "tomorrow"})
    assert r.status_code == 200
    assert r.json() == {"outcome": "executed", "line": "Reminder set for tomorrow, 10:00."}
    ((call, scope, trust),) = w.gateway.calls
    assert call.name == "reminder_add"
    assert call.arguments == {"text": TEXT, "when": "2026-11-11T10:00:00+05:30"}
    assert scope == f"{UID}:{CONSOLE_SESSION}"
    assert trust == {"outside": False, "spoken": False, "owner_text": None}


async def test_the_open_conversation_scopes_the_call_so_a_card_can_be_approved() -> None:
    pending = GatewayResult(GatewayOutcome.AWAITING_CONFIRMATION, pending=SimpleNamespace(id="ap1"))
    w = await checked(World(gateway=GatewayFake(result=pending)))
    r = await w.post({"key": "telegram", "when": "1h", "session_id": "sess_1-a"})
    assert r.json() == {"outcome": "awaiting_confirmation", "line": "Approve it in Approvals, Sir."}
    assert w.gateway.calls[0][1] == f"{UID}:sess_1-a"
    assert w.gateway.cancelled == []


async def test_a_card_with_no_conversation_to_approve_it_in_is_withdrawn() -> None:
    pending = GatewayResult(GatewayOutcome.AWAITING_CONFIRMATION, pending=SimpleNamespace(id="ap2"))
    w = await checked(World(gateway=GatewayFake(result=pending)))
    r = await w.post({"key": "telegram", "when": "evening"})
    assert r.json()["outcome"] == "refused"
    assert "ask first" in r.json()["line"].lower()
    assert w.gateway.cancelled == ["ap2"]


@pytest.mark.parametrize("google", [GoogleFake(connected=False), None])
async def test_google_not_connected_is_refused_with_no_tool_call(google: GoogleFake | None) -> None:
    w = await checked(World(google=google or GoogleFake()))
    if google is None:
        w.google = None  # type: ignore[assignment]
    r = await w.post({"key": "telegram", "when": "1h"})
    assert r.json() == {"outcome": "refused", "line": "Connect Google first, Sir."}
    assert w.gateway.calls == []


async def test_google_status_that_cannot_be_read_is_refused_with_no_call() -> None:
    w = await checked(World(google=GoogleFake(exc=RuntimeError("token sk-1"))))
    r = await w.post({"key": "telegram", "when": "1h"})
    assert r.json()["outcome"] == "refused" and "sk-" not in r.text
    assert w.gateway.calls == []


async def test_no_gateway_is_refused() -> None:
    w = await checked(World())
    w.gateway = None  # type: ignore[assignment]
    r = await w.post({"key": "telegram", "when": "1h"})
    assert r.json() == {"outcome": "refused", "line": "Reminders aren't available right now, Sir."}


NOT_ALLOWED, NOT_SET = "That isn't allowed right now, Sir.", "That reminder couldn't be set, Sir."


@pytest.mark.parametrize(
    ("result", "line"),
    [
        (GatewayResult(GatewayOutcome.DENIED, error="policy:never"), NOT_ALLOWED),
        (GatewayResult(GatewayOutcome.ERROR, error="Google 500 sk-x"), NOT_SET),
        (GatewayResult(GatewayOutcome.EXECUTED, result={"refused": True, "message": "x"}), NOT_SET),
    ],
)
async def test_other_outcomes_are_refused_in_fixed_words(result: GatewayResult, line: str) -> None:
    w = await checked(World(gateway=GatewayFake(result=result)))
    r = await w.post({"key": "telegram", "when": "1h"})
    assert r.json() == {"outcome": "refused", "line": line}
    assert "sk-" not in r.text and "policy" not in r.text


async def test_a_key_that_is_not_a_current_concern_is_422_with_no_call() -> None:
    w = await checked(World())
    assert (await w.post({"key": "redis", "when": "1h"})).status_code == 422  # it is fine
    assert (await w.post({"key": "nonsense", "when": "1h"})).status_code == 422
    assert w.gateway.calls == []


async def test_before_any_check_every_key_is_unknown() -> None:
    w = World()
    assert (await w.post({"key": "telegram", "when": "1h"})).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"key": "telegram", "when": "next week"},
        {"key": "telegram"},
        {"key": "Telegram!", "when": "1h"},
        {"key": "telegram", "when": "1h", "session_id": "a:b"},
        {"key": "telegram", "when": "1h", "text": "pay the bill"},
    ],
)
async def test_bad_bodies_are_422(body: dict[str, Any]) -> None:
    w = await checked(World())
    assert (await w.post(body)).status_code == 422
    assert w.gateway.calls == []


async def test_a_vitals_concern_can_be_reminded_too() -> None:
    hot = view("github", "GitHub token", "amber", reason="expires in 3 days")
    w = await checked(World(vitals=VitalsFake(board(hot))))
    r = await w.post({"key": "vitals.github", "when": "evening"})
    assert r.json() == {"outcome": "executed", "line": "Reminder set for this evening, 18:00."}
    assert w.gateway.calls[0][0].arguments["text"] == (
        "Fix GitHub token: the service using it stops working"
    )


async def test_remind_shares_the_run_budget() -> None:
    w = await checked(World())
    for _ in range(RUN_PER_MINUTE):
        assert (await w.post({"key": "telegram", "when": "1h"})).status_code == 200
    assert (await w.post({"key": "telegram", "when": "1h"})).status_code == 429


async def test_by_default_the_route_finds_the_gateway_google_and_zone_on_the_app() -> None:
    w = await checked(World(default_deps=True))
    w.app.state.gateway = w.gateway
    w.app.state.google = w.google
    w.app.state.settings = SimpleNamespace(user_timezone="Asia/Kolkata")
    r = await w.post({"key": "telegram", "when": "tomorrow"})
    assert r.json()["outcome"] == "executed"
    assert w.gateway.calls[0][0].arguments["when"].endswith("T10:00:00+05:30")


async def test_by_default_with_nothing_on_the_app_it_is_refused() -> None:
    w = await checked(World(default_deps=True))
    r = await w.post({"key": "telegram", "when": "tomorrow"})
    assert r.json()["outcome"] == "refused"
