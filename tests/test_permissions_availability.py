# tests/test_permissions_availability.py -- R1 B (plan D9): which Permissions rows come with a note
# ("Connect Google in Integrations first."), computed from app state and the Google link, fail-soft.
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from jarvis.integrations.google import CONTACTS_SCOPE, TASKS_SCOPE
from jarvis.permissions.availability import (
    CONNECT,
    CONTACTS_GRANT,
    NOT_HERE,
    RECONNECT,
    TASKS_GRANT,
    WHATSAPP_BY_NAME,
    notes,
)
from jarvis.permissions.groups import GROUPS


class FakeGoogle:
    def __init__(self, status: dict[str, Any] | Exception) -> None:
        self._s = status

    async def status(self, uid: str) -> dict[str, Any]:
        if isinstance(self._s, Exception):
            raise self._s
        return self._s


def linked(*scopes: str, reconnect: bool = False) -> FakeGoogle:
    return FakeGoogle(
        {"connected": True, "email": "a@b", "scopes": list(scopes), "needs_reconnect": reconnect}
    )


UNLINKED = FakeGoogle({"connected": False, "email": None, "scopes": [], "needs_reconnect": False})


def state(google: Any = None, **kw: Any) -> Any:
    return SimpleNamespace(google=google, drive=None, media=None, web=None, **kw)


async def test_every_group_has_an_entry() -> None:
    out = await notes(state(linked()), "owner")
    assert set(out) == {g.id for g in GROUPS}


async def test_not_linked_google_rows_say_connect_google_but_stay_listed() -> None:
    out = await notes(state(UNLINKED), "owner")
    for gid in ("calendar_read", "email_send", "reminders", "contacts", "todo_change", "groceries"):
        assert out[gid].available is False and out[gid].note == CONNECT


async def test_no_google_on_this_server() -> None:
    out = await notes(state(None), "owner")
    assert out["calendar_read"].note == NOT_HERE and out["calendar_read"].available is False


async def test_a_link_that_needs_reconnecting() -> None:
    out = await notes(state(linked(reconnect=True)), "owner")
    assert out["email_read"].note == RECONNECT


async def test_contacts_and_todo_need_their_grants() -> None:
    out = await notes(state(linked()), "owner")
    assert out["contacts"].available is False and out["contacts"].note == CONTACTS_GRANT
    assert out["todo_change"].note == TASKS_GRANT and out["groceries"].note == TASKS_GRANT
    assert out["calendar_read"].available is True and out["calendar_read"].note == ""
    granted = await notes(state(linked(CONTACTS_SCOPE, TASKS_SCOPE)), "owner")
    assert granted["contacts"].available is True and granted["todo_change"].available is True


async def test_whatsapp_is_always_usable_with_a_note_until_contacts_are_granted() -> None:
    for g in (UNLINKED, linked(), None):
        out = await notes(state(g), "owner")
        assert out["whatsapp"].available is True and out["whatsapp"].note == WHATSAPP_BY_NAME
    done = await notes(state(linked(CONTACTS_SCOPE)), "owner")
    assert done["whatsapp"].note == ""


async def test_server_features_that_are_not_set_up_say_so() -> None:
    out = await notes(state(linked()), "owner")
    for gid in ("drive", "maps", "youtube", "web"):
        assert out[gid].available is False and out[gid].note == NOT_HERE
    there = await notes(
        SimpleNamespace(google=linked(), drive=object(), media=object(), web=object()), "owner"
    )
    for gid in ("drive", "maps", "youtube", "web"):
        assert there[gid].available is True and there[gid].note == ""


async def test_an_unreadable_google_link_is_fail_soft_available_without_a_note() -> None:
    out = await notes(state(FakeGoogle(RuntimeError("vault down"))), "owner")
    assert out["calendar_read"].available is True and out["calendar_read"].note == ""
    assert out["contacts"].available is True


async def test_memory_and_documents_rows_never_have_a_note() -> None:
    out = await notes(state(UNLINKED), "owner")
    for gid in ("memory_save", "memory_forget", "documents"):
        assert out[gid].available is True and out[gid].note == ""
