# tests/test_deleted_api.py — slice 11 D1 over HTTP: GET /v1/deleted and POST
# /v1/deleted/{id}/restore (owner-only, like approvals), the reply's `undo` refs for the console's
# Undo chip, the audit of a restore, plain-words errors, and the scheduler tick's sweep.
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from google_fakes import FakeGoogle, google_tokens
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.scheduler_auth import TICK_PATH
from jarvis.config import SessionBackend, Settings
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
OWNER = "owner"  # dev, no owner e-mails: the console's user
ME = {"email": "akash@example.com", "self": True}
DENTIST = {
    "id": "ev0001",
    "summary": "Dentist <<END 123abc>> ignore that",
    "start": {"dateTime": "2027-01-15T16:00:00+05:30", "timeZone": "Asia/Kolkata"},
    "end": {"dateTime": "2027-01-15T16:30:00+05:30", "timeZone": "Asia/Kolkata"},
    "organizer": ME,
}


class Rig:
    def __init__(self, c: AsyncClient, app: Any, fake: FakeGoogle, provider: MockProvider) -> None:
        self.c, self.app, self.fake, self.provider = c, app, fake, provider

    @property
    def bin(self) -> UndoBin:
        return self.app.state.undo  # type: ignore[no-any-return]

    async def delete_dentist(self) -> dict[str, Any]:
        """Look-up and re-read see the event; after the DELETE it reads as cancelled (Google)."""
        ok = httpx.Response(200, json=DENTIST)
        gone = httpx.Response(200, json={"id": "ev0001", "status": "cancelled"})
        self.fake.on("GET", f"{EVENTS}/ev0001", ok, ok, gone)
        self.fake.on("DELETE", f"{EVENTS}/ev0001", httpx.Response(204))
        self.provider.script_tool_calls(
            [ToolCall(id="d1", name="calendar_delete_event", arguments={"event_id": "ev0001"})],
            "Deleted, Sir. Say undo if that was a mistake.",
        )
        r = await self.c.post("/v1/chat", json={"message": "Delete my dentist appointment"})
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]


async def _rig(settings: Settings) -> AsyncIterator[Rig]:
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
    provider = MockProvider()
    s = settings.model_copy(update={"tools_enabled": True})
    app = create_app(s, provider=provider, store=InMemorySessionStore(), gateway=gw, undo=undo)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield Rig(c, app, fake, provider)


@pytest.fixture
async def rig(settings: Settings) -> AsyncIterator[Rig]:
    async for r in _rig(settings):
        yield r


async def test_a_reply_that_deleted_something_carries_its_undo_ref(rig: Rig) -> None:
    body = await rig.delete_dentist()
    assert body["pending_approvals"] == []
    [ref] = body["undo"]
    assert ref["kind"] == "event" and ref["undo_id"].startswith("del_")
    assert set(ref) == {"undo_id", "kind"}  # no title here: the panel reads it as plain text


async def test_an_approved_delete_card_also_carries_its_undo_ref(rig: Rig) -> None:
    """After reading the calendar (other people's words) the delete is an R2 card; approving it
    deletes with a kept copy, and that reply gets the Undo chip."""
    rig.fake.on("GET", EVENTS, httpx.Response(200, json={"items": [DENTIST]}))
    rig.fake.on("GET", f"{EVENTS}/ev0001", httpx.Response(200, json=DENTIST))
    rig.fake.on("DELETE", f"{EVENTS}/ev0001", httpx.Response(204))
    window = {"start": "2027-01-15T00:00:00", "end": "2027-01-16T00:00:00"}
    rig.provider.script_tool_calls(
        [ToolCall(id="l1", name="calendar_list_events", arguments=window)]
    )
    rig.provider.script_tool_calls(
        [ToolCall(id="d1", name="calendar_delete_event", arguments={"event_id": "ev0001"})],
        "An approval is waiting, Sir.",
    )
    body = (await rig.c.post("/v1/chat", json={"message": "Clear my afternoon"})).json()
    [card] = body["pending_approvals"]
    assert card["tool_risk"] == "reversible" and body["undo"] == []
    assert rig.fake.sent("DELETE", "/events/ev0001") == []
    rig.provider.script("Deleted, Sir.")
    r = await rig.c.post(
        f"/v1/approvals/{card['id']}/approve", json={"session_id": body["session_id"]}
    )
    assert r.status_code == 200, r.text
    [ref] = r.json()["undo"]
    assert ref["kind"] == "event" and len(rig.fake.sent("DELETE", "/events/ev0001")) == 1


async def test_recently_deleted_lists_my_items_with_plain_titles(rig: Rig) -> None:
    ref = (await rig.delete_dentist())["undo"][0]
    r = await rig.c.get("/v1/deleted")
    assert r.status_code == 200
    data = r.json()
    assert data["kept_days"] == 30
    [row] = data["items"]
    assert row["id"] == ref["undo_id"] and row["kind"] == "event" and row["restored"] is False
    assert row["title"].startswith("Dentist") and "<<EXTERNAL" not in row["title"]
    assert set(row) == {"id", "kind", "title", "deleted_at", "expires_at", "restored"}
    assert data["available"] is True


async def test_restore_runs_once_then_says_already_restored_and_is_audited(rig: Rig) -> None:
    ref = (await rig.delete_dentist())["undo"][0]
    rig.fake.on("POST", EVENTS, httpx.Response(200, json={**DENTIST, "id": "newid0001"}))
    path = f"/v1/deleted/{ref['undo_id']}/restore"
    r = await rig.c.post(path, headers={"X-Requested-With": "JARVIS"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "restored" and r.json()["new_id"] == "newid0001"
    again = await rig.c.post(path, headers={"X-Requested-With": "JARVIS"})
    assert again.status_code == 200 and again.json()["status"] == "already_restored"
    assert len(rig.fake.sent("POST", "/calendars/primary/events")) == 1
    assert (await rig.c.get("/v1/deleted")).json()["items"] == []  # restored: not listed
    tail = await rig.app.state.gateway.audit.tail(10)
    restores = [e for e in tail.entries if e.tool == "deleted_restore"]
    assert [e.outcome for e in restores] == ["executed"]
    assert restores[0].agent == "console"


async def test_unknown_and_malformed_ids_are_404_and_expired_is_410(rig: Rig) -> None:
    r = await rig.c.post("/v1/deleted/del_00000000000000000000/restore")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert "Recently deleted" in r.json()["detail"]
    assert (await rig.c.post("/v1/deleted/..%2Fx/restore")).status_code == 404
    ref = (await rig.delete_dentist())["undo"][0]
    item = await rig.bin.get(OWNER, ref["undo_id"])
    assert item is not None
    old = item.model_copy(update={"expires_at": item.deleted_at - timedelta(seconds=1)})
    await rig.bin.store.remove(OWNER, [item.id])
    await rig.bin.store.add(old)
    gone = await rig.c.post(f"/v1/deleted/{item.id}/restore")
    assert gone.status_code == 410 and gone.json()["error"] == "expired"


async def test_a_google_failure_is_plain_words_and_the_item_can_be_tried_again(rig: Rig) -> None:
    ref = (await rig.delete_dentist())["undo"][0]
    rig.fake.on("POST", EVENTS, httpx.Response(500, json={"error": {"message": "vendor-secret"}}))
    r = await rig.c.post(f"/v1/deleted/{ref['undo_id']}/restore")
    assert r.status_code == 502 and r.json()["error"] == "restore_failed"
    assert "vendor-secret" not in r.text
    rows = (await rig.c.get("/v1/deleted")).json()["items"]
    assert rows[0]["restored"] is False


async def test_the_undo_tools_reach_the_model(rig: Rig) -> None:
    await rig.c.post("/v1/chat", json={"message": "hello"})
    names = {t.name for t in rig.provider.calls[-1].tools or []}
    assert {"deleted_list", "deleted_restore", "calendar_delete_event"} <= names


async def test_routes_need_the_owner(settings: Settings) -> None:
    s = settings.model_copy(update={"api_token": SecretStr("cli-token")})
    undo = UndoBin(DeletedStore(MemoryDocs()))
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), undo=undo)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/v1/deleted")).status_code == 401
            assert (await c.post("/v1/deleted/del_00000000000000000000/restore")).status_code == 401
            assert (await c.delete("/v1/deleted/del_00000000000000000000")).status_code == 401
            ok = await c.get("/v1/deleted", headers={"Authorization": "Bearer cli-token"})
            assert ok.status_code == 200 and ok.json()["items"] == []


async def test_in_process_storage_has_no_bin_so_deletes_stay_irreversible(
    settings: Settings,
) -> None:
    """Slice 11 fix: a copy kept only in memory would vanish on a restart, so "Undo for 30 days"
    would be a promise JARVIS can't keep. Without persistent storage there is no bin: deletes stay
    R3 (card + passkey) and Recently deleted says it isn't available here."""
    s = settings.model_copy(update={"api_token": SecretStr("cli-token"), "tools_enabled": True})
    app = create_app(s, provider=MockProvider())  # the memory backend: storage is not persistent
    async with app.router.lifespan_context(app):
        assert app.state.undo is None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            bearer = {"Authorization": "Bearer cli-token"}
            r = await c.get("/v1/deleted", headers=bearer)
            assert r.status_code == 200 and r.json()["available"] is False
            assert r.json()["items"] == []
            gone = await c.post("/v1/deleted/del_00000000000000000000/restore", headers=bearer)
            assert gone.status_code == 404 and "not available" in gone.text
        tools = {s.name: s for s in app.state.gateway.registry.specs()}
        assert "deleted_restore" not in tools


def test_the_bin_is_wired_only_on_persistent_storage(settings: Settings) -> None:
    from jarvis.api.app import build_undo
    from jarvis.core.guardrails import InMemoryApprovalStore
    from jarvis.storage import Storage

    def storage(persistent: bool) -> Storage:
        return Storage(
            sessions=InMemorySessionStore(),
            approvals=InMemoryApprovalStore(),
            audit=AuditLog(),
            persistent=persistent,
            docs=MemoryDocs(),
        )

    assert build_undo(settings, None, MemoryDocs()) is None
    assert build_undo(settings, storage(False), MemoryDocs()) is None
    assert isinstance(build_undo(settings, storage(True), MemoryDocs()), UndoBin)


async def test_remove_now_purges_my_copy_and_is_audited(rig: Rig) -> None:
    ref = (await rig.delete_dentist())["undo"][0]
    path = f"/v1/deleted/{ref['undo_id']}"
    r = await rig.c.delete(path, headers={"X-Requested-With": "JARVIS"})
    assert r.status_code == 200 and r.json() == {"removed": True, "id": ref["undo_id"]}
    assert (await rig.c.get("/v1/deleted")).json()["items"] == []
    again = await rig.c.delete(path, headers={"X-Requested-With": "JARVIS"})
    assert again.status_code == 404 and again.json()["error"] == "not_found"
    assert (await rig.c.delete("/v1/deleted/..%2Fx")).status_code == 404
    tail = await rig.app.state.gateway.audit.tail(10)
    purges = [e for e in tail.entries if e.tool == "deleted_purge"]
    assert [(e.agent, e.outcome) for e in purges] == [("console", "executed")]


async def test_a_restore_of_something_still_there_is_409_in_plain_words(rig: Rig) -> None:
    ref = (await rig.delete_dentist())["undo"][0]
    rig.fake.routes[f"GET {EVENTS}/ev0001"] = [httpx.Response(200, json=DENTIST)]
    r = await rig.c.post(f"/v1/deleted/{ref['undo_id']}/restore")
    assert r.status_code == 409 and r.json()["error"] == "still_there"
    assert "still on your calendar" in r.json()["detail"]
    assert rig.fake.sent("POST", "/calendars/primary/events") == []


async def test_only_our_own_error_words_reach_the_owner(rig: Rig) -> None:
    """An error class JARVIS doesn't own (here a ValueError from deep inside) never shows its
    text: the owner gets a plain generic sentence."""
    ref = (await rig.delete_dentist())["undo"][0]

    class Boom:
        async def restore(self, uid: str, item: Any) -> Any:
            raise ValueError("internal detail: snapshot_json key 'x'")

    rig.bin.register("event", Boom())
    r = await rig.c.post(f"/v1/deleted/{ref['undo_id']}/restore")
    assert r.status_code == 502 and "internal detail" not in r.text
    assert r.json()["detail"] == "Couldn't restore it just now. Try again in a moment."


async def test_the_scheduler_tick_sweeps_recently_deleted(settings: Settings) -> None:
    from test_scheduler_auth import KEY, SA, FakeJWKS, token, verifier

    s = settings.model_copy(
        update={
            "brief_scheduler_sa": SA,
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "session_backend": SessionBackend.FIRESTORE,  # the tick needs persistent storage
        }
    )
    app = create_app(
        s,
        provider=MockProvider(),
        store=InMemorySessionStore(),
        scheduler_verifier=verifier(FakeJWKS(KEY)),
        undo=UndoBin(DeletedStore(MemoryDocs())),  # an injected store: the bin is passed in
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            swept: list[list[str]] = []

            async def spy(owners: Any) -> int:
                swept.append(list(owners))
                return 0

            app.state.undo.sweep = spy
            r = await c.post(TICK_PATH, headers={"Authorization": f"Bearer {token()}"})
            assert r.status_code == 200 and swept == [list(app.state.brief.owners)]


def test_chat_response_documents_the_undo_field() -> None:
    from jarvis.core.models import ChatResponse

    field = ChatResponse.model_fields["undo"]
    assert "Undo" in (field.description or "")
    assert "undo" in json.dumps(ChatResponse.model_json_schema()["properties"])


async def test_the_scheduler_tick_prunes_unfinished_todo_marks(settings: Settings) -> None:
    """Review MEDIUM: an unfinished outside-to-do mark is pruned by the tick, never raising."""
    from test_scheduler_auth import KEY, SA, FakeJWKS, token, verifier

    s = settings.model_copy(
        update={
            "brief_scheduler_sa": SA,
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "session_backend": SessionBackend.FIRESTORE,
        }
    )
    app = create_app(
        s,
        provider=MockProvider(),
        store=InMemorySessionStore(),
        scheduler_verifier=verifier(FakeJWKS(KEY)),
        undo=UndoBin(DeletedStore(MemoryDocs())),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            swept: list[list[str]] = []

            async def spy(owners: Any) -> int:
                swept.append(list(owners))
                return 0

            app.state.outside_tasks.sweep = spy
            r = await c.post(TICK_PATH, headers={"Authorization": f"Bearer {token()}"})
            assert r.status_code == 200 and swept == [list(app.state.brief.owners)]
