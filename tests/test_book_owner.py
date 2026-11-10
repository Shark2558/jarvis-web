# tests/test_book_owner.py -- R6 D16 Book settings and D9's code-download tickets (builder B):
# defaults, partial updates checked before anything is written, stored junk read as defaults field
# by field; tickets that live 60 s, work once, belong to one owner and are stored only as an HMAC
# on their own collection (the R2 UnlockStore pattern).
from __future__ import annotations

import datetime as dt

import pytest
from book_seal_fakes import NOW, OTHER, UID, ring
from pydantic import ValidationError

from jarvis.buildbook.owner import (
    BookSettings,
    BookSettingsPatch,
    BookSettingsStore,
    BookTickets,
    SettingsRejected,
)
from jarvis.buildbook.ports import BookError
from jarvis.storage.docs import MemoryDocs
from jarvis.vault.unlock import MAX_TICKETS, TICKET_S, TicketGone, UnlockStore

RID = "3f2a1c9"


# ---- settings --------------------------------------------------------------------------------


async def test_settings_default_to_the_safe_choices() -> None:
    s = await BookSettingsStore(MemoryDocs()).get(UID)
    assert s == BookSettings()
    assert (s.creator_name, s.show_voice, s.talk_on, s.allow_training_brain) == (
        "",
        "cloud",
        True,
        False,
    )


async def test_a_partial_update_keeps_the_rest_and_persists() -> None:
    docs = MemoryDocs()
    store = BookSettingsStore(docs)
    got = await store.update(UID, BookSettingsPatch(creator_name="  Akash   Das ", talk_on=False))
    assert got.creator_name == "Akash Das" and got.talk_on is False and got.show_voice == "cloud"
    got = await store.update(UID, BookSettingsPatch(show_voice="browser"))
    assert got.creator_name == "Akash Das" and got.show_voice == "browser"
    assert await BookSettingsStore(docs).get(UID) == got
    assert await BookSettingsStore(docs).get(OTHER) == BookSettings()
    assert set(docs._data[f"jarvis_book_settings/{UID}"]) >= {
        "creator_name",
        "show_voice",
        "talk_on",
        "allow_training_brain",
    }


async def test_an_empty_name_clears_it() -> None:
    store = BookSettingsStore(MemoryDocs())
    await store.update(UID, BookSettingsPatch(creator_name="Akash"))
    assert (await store.update(UID, BookSettingsPatch(creator_name="   "))).creator_name == ""


@pytest.mark.parametrize(
    "name", ["x" * 41, "<script>", "Akash‮Das!", "1234", "a@b.c", "line\nbreak?" * 5]
)
async def test_a_bad_creator_name_is_refused_and_nothing_is_written(name: str) -> None:
    docs = MemoryDocs()
    with pytest.raises(SettingsRejected) as err:
        await BookSettingsStore(docs).update(UID, BookSettingsPatch(creator_name=name))
    assert name not in str(err.value) and docs.sets == 0
    assert isinstance(err.value, BookError)


def test_the_patch_takes_strict_types_and_known_fields_only() -> None:
    with pytest.raises(ValidationError):
        BookSettingsPatch.model_validate({"talk_on": "yes"})
    with pytest.raises(ValidationError):
        BookSettingsPatch.model_validate({"show_voice": "robot"})
    with pytest.raises(ValidationError):
        BookSettingsPatch.model_validate({"guest_sees_email": True})


async def test_stored_junk_reads_as_defaults_field_by_field() -> None:
    docs = MemoryDocs()
    docs._data[f"jarvis_book_settings/{UID}"] = {
        "creator_name": "<b>x</b>" * 9,
        "show_voice": "robot",
        "talk_on": "no",
        "allow_training_brain": True,
    }
    s = await BookSettingsStore(docs).get(UID)
    assert s == BookSettings(allow_training_brain=True)


async def test_settings_never_fall_back_silently_when_storage_fails() -> None:
    class Down(MemoryDocs):
        async def get(self, path: str) -> dict[str, object] | None:
            raise RuntimeError("down")

    store = BookSettingsStore(Down())
    with pytest.raises(BookError):
        await store.get(UID)
    # the talk lane's safe read: defaults (no training brain), never an exception
    assert await store.get_or_default(UID) == BookSettings()


# ---- download tickets ------------------------------------------------------------------------


def tickets(docs: MemoryDocs, clock: dict[str, dt.datetime]) -> BookTickets:
    return BookTickets(docs, ring(), clock=lambda: clock["now"])


async def test_a_ticket_works_once_for_its_owner_and_release() -> None:
    docs, clock = MemoryDocs(), {"now": NOW}
    t = tickets(docs, clock)
    got = await t.issue(UID, RID)
    assert got.expires_in_s == TICKET_S == 60 and len(got.ticket) >= 40
    with pytest.raises(TicketGone):
        await t.take(OTHER, got.ticket)
    taken = await t.take(UID, got.ticket)
    assert (taken.item, taken.fid) == (RID, "source")
    with pytest.raises(TicketGone):
        await t.take(UID, got.ticket)


async def test_a_ticket_expires_after_sixty_seconds() -> None:
    docs, clock = MemoryDocs(), {"now": NOW}
    t = tickets(docs, clock)
    got = await t.issue(UID, RID)
    clock["now"] = NOW + dt.timedelta(seconds=61)
    with pytest.raises(TicketGone):
        await t.take(UID, got.ticket)


async def test_tickets_live_on_their_own_collection_as_an_hmac_only() -> None:
    docs, clock = MemoryDocs(), {"now": NOW}
    t = tickets(docs, clock)
    got = await t.issue(UID, RID)
    assert list(docs._data) == [f"jarvis_book_tickets/{UID}"]
    assert got.ticket not in str(docs._data)
    # a vault (R2) ticket is not a book ticket, and the other way round
    vault = UnlockStore(docs, ring(), clock=lambda: clock["now"])
    grant = await vault.grant(UID)
    vt = await vault.ticket(UID, grant.token, "v_000000000001", "f_000000000001")
    with pytest.raises(TicketGone):
        await t.take(UID, vt.ticket)
    with pytest.raises(TicketGone):
        await vault.take(UID, got.ticket)


async def test_at_most_five_live_tickets_the_oldest_go() -> None:
    docs, clock = MemoryDocs(), {"now": NOW}
    t = tickets(docs, clock)
    issued = [await t.issue(UID, RID) for _ in range(MAX_TICKETS + 1)]
    with pytest.raises(TicketGone):
        await t.take(UID, issued[0].ticket)
    assert (await t.take(UID, issued[-1].ticket)).item == RID


async def test_a_book_ticket_store_grants_no_vault_unlock() -> None:
    t = tickets(MemoryDocs(), {"now": NOW})
    with pytest.raises(PermissionError):
        await t.grant(UID)
    with pytest.raises(PermissionError):
        await t.ticket(UID, "x" * 43, RID, "source")
