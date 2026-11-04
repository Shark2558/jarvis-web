# tests/test_activity_api.py -- R1 B over HTTP and through the real gateway: GET /v1/activity, the
# row a delete leaves with a working Undo (the existing restore route), the "You restored" row, and
# the plain reasons elsewhere. The wiring here is what the integrator (I1) does in setup.py/app.py.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from google_fakes import FakeGoogle, google_tokens
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.activity import ActivityRecorder, ActivityService, ActivityStore
from jarvis.api import create_app
from jarvis.api.activity import install_activity
from jarvis.config import Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway
from jarvis.tools.google_calendar import calendar_tools
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.undo.tools import undo_tools

CAL = "https://www.googleapis.com/calendar/v3"
EVENTS = f"{CAL}/calendars/primary/events"
OWNER = "owner"
ME = {"email": "akash@example.com", "self": True}
DENTIST = {
    "id": "ev0001",
    "summary": "Dentist",
    "start": {"dateTime": "2027-01-15T16:00:00+05:30", "timeZone": "Asia/Kolkata"},
    "end": {"dateTime": "2027-01-15T16:30:00+05:30", "timeZone": "Asia/Kolkata"},
    "organizer": ME,
}
H = {"X-Requested-With": "JARVIS"}
EVENT = {"summary": "Lunch", "start": "2027-01-15T13:00:00", "end": "2027-01-15T14:00:00"}


class Rig:
    def __init__(self, c: AsyncClient, app: Any, fake: FakeGoogle, provider: MockProvider) -> None:
        self.c, self.app, self.fake, self.provider = c, app, fake, provider

    async def chat(self, calls: list[ToolCall], text: str = "Done, Sir.") -> dict[str, Any]:
        self.provider.script_tool_calls(calls, text)
        r = await self.c.post("/v1/chat", json={"message": "go"})
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]

    async def delete_dentist(self) -> dict[str, Any]:
        ok = httpx.Response(200, json=DENTIST)
        gone = httpx.Response(200, json={"id": "ev0001", "status": "cancelled"})
        self.fake.on("GET", f"{EVENTS}/ev0001", ok, ok, gone)
        self.fake.on("DELETE", f"{EVENTS}/ev0001", httpx.Response(204))
        call = ToolCall(id="d1", name="calendar_delete_event", arguments={"event_id": "ev0001"})
        return await self.chat([call])

    async def today(self) -> list[dict[str, Any]]:
        r = await self.c.get("/v1/activity?day=today")
        assert r.status_code == 200, r.text
        return r.json()["items"]  # type: ignore[no-any-return]


@pytest.fixture
async def rig(settings: Settings) -> AsyncIterator[Rig]:
    fake = FakeGoogle()
    fake.on("GET", f"{CAL}/users/me/calendarList/primary", httpx.Response(200, json={}))
    tokens = MemoryTokenStore()
    await tokens.put(OWNER, google_tokens(expires_at=4_000_000_000.0))
    conn = GoogleConnector(tokens, client_id="c", client_secret=SecretStr("s"), http=fake.client())
    undo = UndoBin(DeletedStore(MemoryDocs()))
    reg = ToolRegistry()
    for t in calendar_tools(conn, undo=undo) + undo_tools(undo):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    docs = MemoryDocs()
    store = ActivityStore(docs)
    gw.observers = [ActivityRecorder(store, reg, timezone=settings.user_timezone)]
    provider = MockProvider()
    s = settings.model_copy(update={"tools_enabled": True})
    app = create_app(s, provider=provider, store=InMemorySessionStore(), gateway=gw, undo=undo)
    install_activity(app)
    async with app.router.lifespan_context(app):
        app.state.activity = ActivityService(store, undo, timezone=s.user_timezone)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield Rig(c, app, fake, provider)


async def test_a_delete_shows_up_with_undo_and_undo_restores_it(rig: Rig) -> None:
    await rig.delete_dentist()
    [row] = await rig.today()
    assert row["outcome"] == "done" and row["channel"] == "console" and row["offline"] is False
    assert row["undo"]["state"] == "available" and row["undo"]["id"].startswith("del_")
    assert row["undo_note"] == ""
    rig.fake.on("POST", EVENTS, httpx.Response(200, json={**DENTIST, "id": "new0001"}))
    r = await rig.c.post(f"/v1/deleted/{row['undo']['id']}/restore", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "restored"
    rows = await rig.today()
    states = {x["words"]: x for x in rows}
    restored = [x for x in rows if x["words"].startswith("You restored the event")]
    assert len(restored) == 1 and "Dentist" in restored[0]["words"]
    deleted = next(x for k, x in states.items() if not k.startswith("You restored"))
    assert deleted["undo"]["state"] == "restored"


async def test_a_second_restore_click_adds_no_second_restored_row(rig: Rig) -> None:
    await rig.delete_dentist()
    [row] = await rig.today()
    rig.fake.on("POST", EVENTS, httpx.Response(200, json={**DENTIST, "id": "new0001"}))
    path = f"/v1/deleted/{row['undo']['id']}/restore"
    await rig.c.post(path, headers=H)
    await rig.c.post(path, headers=H)
    rows = await rig.today()
    assert len([x for x in rows if x["words"].startswith("You restored")]) == 1


async def test_an_event_add_has_no_undo_and_says_why(rig: Rig) -> None:
    rig.fake.on("POST", EVENTS, httpx.Response(200, json=DENTIST))
    rig.provider.script_tool_calls(
        [ToolCall(id="r1", name="calendar_create_event", arguments=EVENT)],
        "ok",
    )
    await rig.c.post("/v1/chat", json={"message": "remind me"})
    rows = await rig.today()
    adds = [r for r in rows if r["undo"] is None and r["outcome"] == "done"]
    assert adds and all("Can't be undone from here" in r["undo_note"] for r in adds)


async def test_a_calendar_read_shows_no_query_text(rig: Rig) -> None:
    rig.fake.on("GET", EVENTS, httpx.Response(200, json={"items": []}))
    window = {"start": "2027-01-15T00:00:00", "end": "2027-01-16T00:00:00", "query": "oncologist"}
    await rig.chat([ToolCall(id="l1", name="calendar_list_events", arguments=window)])
    rows = await rig.today()
    assert [r["words"] for r in rows] == ["Looked at your calendar"]
    assert "oncologist" not in (await rig.c.get("/v1/activity")).text


async def test_the_response_shape_and_unknown_day(rig: Rig) -> None:
    r = await rig.c.get("/v1/activity")
    body = r.json()
    assert set(body) == {"day", "items", "verified", "available"}
    assert body["day"] == "today" and body["available"] is True and body["verified"] is True
    assert (await rig.c.get("/v1/activity?day=tomorrow")).status_code == 422
    assert (await rig.c.get("/v1/activity?day=yesterday")).json()["items"] == []


async def test_a_broken_activity_store_never_fails_the_tool_call(rig: Rig) -> None:
    class Down(MemoryDocs):
        async def write(self, ops: Any) -> None:
            raise RuntimeError("firestore down")

    gw = rig.app.state.gateway
    gw.observers[0].store = ActivityStore(Down())
    body = await rig.delete_dentist()
    assert body["undo"] and body["undo"][0]["kind"] == "event"  # the delete itself still worked


async def test_without_a_service_the_view_says_unavailable(settings: Settings) -> None:
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    install_activity(app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            body = (await c.get("/v1/activity")).json()
            assert body["available"] is False and body["items"] == []


async def test_the_route_needs_the_owner(settings: Settings) -> None:
    s = settings.model_copy(update={"api_token": SecretStr("cli-token")})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    install_activity(app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/v1/activity")).status_code == 401
