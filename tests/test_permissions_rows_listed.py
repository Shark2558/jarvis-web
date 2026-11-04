# tests/test_permissions_rows_listed.py -- R1 B (plan D9, evals "permissions"): GET /v1/permissions
# lists EVERY group in every owner state, each with `available` and `note`. The WhatsApp row is
# present in all 8 states (Google off/on x Contacts granted or not x row Never or not) plus
# "rules unreadable", and an old client that ignores the new fields still gets the old ones.
from __future__ import annotations

import itertools
from collections.abc import AsyncIterator
from typing import Any

import pytest
from google_fakes import google_tokens
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.integrations.google import CONTACTS_SCOPE, GoogleConnector
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.groups import GROUPS

H = {"X-Requested-With": "JARVIS"}
OWNER = "owner"


async def _client(
    settings: Settings, *, google: bool, contacts: bool, never: bool
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        if google:
            tokens = MemoryTokenStore()
            scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
            if contacts:
                scopes.append(CONTACTS_SCOPE)
            await tokens.put(OWNER, google_tokens(expires_at=4_000_000_000.0, scopes=scopes))
            app.state.google = GoogleConnector(tokens, client_id="c", client_secret=SecretStr("s"))
        else:
            app.state.google = None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            if never:
                r = await c.put("/v1/permissions", json={"groups": {"whatsapp": "deny"}}, headers=H)
                assert r.status_code == 200, r.text
            yield c


STATES = list(itertools.product([False, True], [False, True], [False, True]))


@pytest.mark.parametrize(("google", "contacts", "never"), STATES)
async def test_the_whatsapp_row_is_listed_in_every_owner_state(
    settings: Settings, google: bool, contacts: bool, never: bool
) -> None:
    async for c in _client(settings, google=google, contacts=contacts, never=never):
        body = (await c.get("/v1/permissions")).json()
        ids = [g["id"] for g in body["groups"]]
        assert ids == [g.id for g in GROUPS]
        wa = next(g for g in body["groups"] if g["id"] == "whatsapp")
        assert wa["label"] == "Write WhatsApp drafts" and wa["choices"] == ["allow", "ask", "deny"]
        assert wa["effect"] == ("deny" if never else "allow")
        assert wa["available"] is True
        assert (wa["note"] == "") is (google and contacts)


async def test_every_group_carries_available_and_note(settings: Settings) -> None:
    async for c in _client(settings, google=False, contacts=False, never=False):
        body = (await c.get("/v1/permissions")).json()
        for g in body["groups"]:
            assert isinstance(g["available"], bool) and isinstance(g["note"], str)
        cal = next(g for g in body["groups"] if g["id"] == "calendar_read")
        assert cal["available"] is False and cal["note"]


async def test_hand_edited_stored_rules_still_list_every_row(settings: Settings) -> None:
    """Rules in storage the page can't make sense of (unknown group, unknown effect) read as the
    defaults: all rows are still listed, the WhatsApp row included."""
    from jarvis.storage.docs import Set

    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        docs = app.state.permissions.store._d
        bad = {"user_id": OWNER, "groups": {"whatsapp": "limit", "zzz": "allow", "web": 7}}
        await docs.write([Set("jarvis_permissions/owner", bad)])
        app.state.permissions.store._cache.clear()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            body = (await c.get("/v1/permissions")).json()
            assert [g["id"] for g in body["groups"]] == [g.id for g in GROUPS]
            wa = next(g for g in body["groups"] if g["id"] == "whatsapp")
            assert wa["effect"] == "allow"


async def test_a_failing_availability_check_never_hides_rows(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jarvis.api.permissions as api

    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("availability exploded")

    monkeypatch.setattr(api, "availability_notes", boom)
    async for c in _client(settings, google=False, contacts=False, never=False):
        body = (await c.get("/v1/permissions")).json()
        assert [g["id"] for g in body["groups"]] == [g.id for g in GROUPS]
        assert all(g["available"] is True and g["note"] == "" for g in body["groups"])


async def test_notes_are_computed_on_get_only_not_on_every_change(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jarvis.api.permissions as api

    calls: list[str] = []
    real = api.availability_notes

    async def counting(*a: Any, **k: Any) -> Any:
        calls.append("x")
        return await real(*a, **k)

    monkeypatch.setattr(api, "availability_notes", counting)
    async for c in _client(settings, google=False, contacts=False, never=False):
        await c.get("/v1/permissions")
        assert len(calls) == 1
        r = await c.put("/v1/permissions", json={"groups": {"web": "deny"}}, headers=H)
        assert r.status_code == 200
        assert len(calls) == 1  # a change does not ask Google again
