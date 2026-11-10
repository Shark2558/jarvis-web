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


# ---- when ---------------------------------------------------------------------------------------
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


def test_exactly_six_pm_goes_to_tomorrow_evening_and_a_second_before_stays_today() -> None:
    at, said = when_at("evening", datetime(2026, 11, 10, 18, 0, 0, tzinfo=IST))
    assert said == "tomorrow evening, 18:00" and at.day == 11
    at, said = when_at("evening", datetime(2026, 11, 10, 17, 59, 59, tzinfo=IST))
    assert said == "this evening, 18:00" and at.day == 10


def test_an_hour_from_23_59_30_is_tomorrow_00_59() -> None:
    at, said = when_at("1h", datetime(2026, 11, 10, 23, 59, 30, tzinfo=IST))
    assert said == "tomorrow, 00:59" and at.isoformat() == "2026-11-11T00:59:00+05:30"


# ---- the route ----------------------------------------------------------------------------------
class SessionsFake:
    """`.get(session_id)` of the session store: a session that has an owner, else None."""

    def __init__(self, owners: dict[str, str]) -> None:
        self.owners = owners

    async def get(self, session_id: str) -> Any:
        owner = self.owners.get(session_id)
        return None if owner is None else SimpleNamespace(user_id=owner)


class World:
    def __init__(
        self,
        *,
        gateway: GatewayFake | None = None,
        google: GoogleFake | None = None,
        vitals: Any = None,
        down: str = "telegram",
        default_deps: bool = False,
        sessions: Any = "default",
    ) -> None:
        self.gateway = gateway if gateway is not None else GatewayFake()
        self.google = google if google is not None else GoogleFake()
        self.sessions = SessionsFake({"sess_1-a": UID}) if sessions == "default" else sessions
        self.svc = HealthService(
            [fixed("redis", "Redis", "ok"), fixed(down, down, "down")],
            HealthStore(MemoryDocs(), prefix="jarvis_"),
            vitals=vitals,
            clock=Clock(),
        )
        self.app = FastAPI()

        def deps(_req: Request) -> RemindDeps:
            return RemindDeps(
                gateway=self.gateway,
                google=self.google,
                tz="Asia/Kolkata",
                now=lambda: NOON,
                sessions=self.sessions,
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


async def test_an_automatic_vitals_item_is_reminded_in_fixed_words_owner_trusted() -> None:
    hot = view("github_token", "Owner-typed lure: call 1800 555 0100", "amber", reason="expires")
    w = await checked(World(vitals=VitalsFake(board(hot))))
    r = await w.post({"key": "vitals.github_token", "when": "evening"})
    assert r.json() == {"outcome": "executed", "line": "Reminder set for this evening, 18:00."}
    (call, _scope, trust) = w.gateway.calls[0]
    assert call.arguments["text"] == "Fix the GitHub token: JARVIS can't read your GitHub"
    assert "1800" not in call.arguments["text"] and trust["outside"] is False


@pytest.mark.parametrize(
    ("pid", "text"),
    [
        ("quota_stt", "Fix a Vitals quota: that feature stops until it resets"),
        ("allowance_voice", "Fix a free allowance: voice costs rupees once it runs out"),
    ],
)
async def test_quota_and_allowance_items_use_fixed_words_too(pid: str, text: str) -> None:
    hot = view(pid, "Anything the label says", "amber", reason="x")
    w = await checked(World(vitals=VitalsFake(board(hot))))
    await w.post({"key": f"vitals.{pid}", "when": "1h"})
    assert w.gateway.calls[0][0].arguments["text"] == text
    assert w.gateway.calls[0][2]["outside"] is False


async def test_an_owner_typed_vitals_item_never_runs_owner_trusted() -> None:
    """A manual item's label can be laundered text (a model turn that read the web wrote it):
    the call runs in an untrusted context so the gateway asks for approval."""
    lure = view("renew_x", "Call 1800 555 0100 to renew", "amber", reason="expires")
    pending = GatewayResult(GatewayOutcome.AWAITING_CONFIRMATION, pending=SimpleNamespace(id="ap3"))
    w = await checked(World(vitals=VitalsFake(board(lure)), gateway=GatewayFake(result=pending)))
    r = await w.post({"key": "vitals.renew_x", "when": "1h", "session_id": "sess_1-a"})
    assert r.json()["outcome"] == "awaiting_confirmation"
    (_call, _scope, trust) = w.gateway.calls[0]
    assert trust["outside"] is True and trust["owner_text"] is None


# ---- a session the owner really has -------------------------------------------------------------
async def test_the_literal_console_session_counts_as_no_conversation() -> None:
    pending = GatewayResult(GatewayOutcome.AWAITING_CONFIRMATION, pending=SimpleNamespace(id="ap4"))
    w = await checked(
        World(gateway=GatewayFake(result=pending), sessions=SessionsFake({CONSOLE_SESSION: UID}))
    )
    r = await w.post({"key": "telegram", "when": "1h", "session_id": CONSOLE_SESSION})
    assert r.json()["outcome"] == "refused" and "ask first" in r.json()["line"].lower()
    assert w.gateway.cancelled == ["ap4"]
    assert w.gateway.calls[0][1] == f"{UID}:{CONSOLE_SESSION}"


@pytest.mark.parametrize("owners", [{}, {"sess_1-a": "u_someone_else"}, None])
async def test_a_session_that_is_not_the_owners_counts_as_no_conversation(
    owners: dict[str, str] | None,
) -> None:
    pending = GatewayResult(GatewayOutcome.AWAITING_CONFIRMATION, pending=SimpleNamespace(id="ap5"))
    sessions = None if owners is None else SessionsFake(owners)
    w = await checked(World(gateway=GatewayFake(result=pending), sessions=sessions))
    r = await w.post({"key": "telegram", "when": "1h", "session_id": "sess_1-a"})
    assert r.json()["outcome"] == "refused"
    assert w.gateway.calls[0][1] == f"{UID}:{CONSOLE_SESSION}"
    assert w.gateway.cancelled == ["ap5"]


# ---- the same reminder twice --------------------------------------------------------------------
async def test_an_identical_reminder_within_ten_minutes_is_already_set_with_no_second_call() -> (
    None
):
    w = await checked(World())
    first = await w.post({"key": "telegram", "when": "1h"})
    second = await w.post({"key": "telegram", "when": "1h"})
    assert first.json()["outcome"] == "executed"
    assert second.json() == {"outcome": "executed", "line": "Already set, Sir."}
    assert len(w.gateway.calls) == 1
    other_time = await w.post({"key": "telegram", "when": "evening"})
    assert other_time.json()["line"].startswith("Reminder set")
    assert len(w.gateway.calls) == 2


async def test_a_refused_reminder_can_be_tried_again_and_the_memo_expires() -> None:
    from jarvis.health.remind import RemindMemo

    now = [1000.0]
    memo = RemindMemo(clock=lambda: now[0])
    assert memo.claim("u", "telegram", "1h") is True
    assert memo.claim("u", "telegram", "1h") is False
    memo.release("u", "telegram", "1h")  # it failed: try again
    assert memo.claim("u", "telegram", "1h") is True
    now[0] += 601
    assert memo.claim("u", "telegram", "1h") is True  # ten minutes later
    assert memo.claim("u2", "telegram", "1h") is True  # another owner


async def test_a_refused_call_does_not_block_the_retry() -> None:
    w = await checked(World(google=GoogleFake(connected=False)))
    await w.post({"key": "telegram", "when": "1h"})
    w.google.connected = True
    r = await w.post({"key": "telegram", "when": "1h"})
    assert r.json()["outcome"] == "executed"


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
