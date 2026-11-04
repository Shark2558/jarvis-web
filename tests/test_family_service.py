# tests/test_family_service.py -- R1 D15: registering family calendars (verify, limits, store).
from __future__ import annotations

import asyncio

import pytest
from r1d_fakes import OWNER, FamilyCalendars, connector

from jarvis.family.service import FamilyError, FamilyService
from jarvis.family.store import FamilyStore
from jarvis.storage.docs import MemoryDocs

ANJALI = "anjali@gmail.com"


async def service(fake: FamilyCalendars, docs: MemoryDocs | None = None) -> FamilyService:
    conn = await connector(fake.client())
    return FamilyService(conn, FamilyStore(docs or MemoryDocs()), default_tz="Asia/Kolkata")


async def test_adding_a_shared_calendar_verifies_it_and_stores_the_role() -> None:
    fake = FamilyCalendars(roles={ANJALI: "reader"})
    svc = await service(fake)
    m = await svc.add(OWNER, "  Anjali ", " Anjali@Gmail.com ")
    assert (m.name, m.calendar_id, m.access) == ("Anjali", ANJALI, "reader")
    assert m.id.startswith("fam_") and len(m.id) == 16
    assert [x.id for x in await svc.members(OWNER)] == [m.id]
    assert fake.sent("GET", "/calendarList/anjali%40gmail.com") or fake.sent("GET", ANJALI)


async def test_a_calendar_not_in_the_list_but_readable_is_taken_as_reader() -> None:
    fake = FamilyCalendars(shared_only={ANJALI})
    m = await (await service(fake)).add(OWNER, "Anjali", ANJALI)
    assert m.access == "reader" and not m.can_write


async def test_a_calendar_that_is_not_shared_is_refused_with_the_how_to() -> None:
    svc = await service(FamilyCalendars())
    with pytest.raises(FamilyError) as e:
        await svc.add(OWNER, "Anjali", ANJALI)
    assert e.value.reason == "not_shared" and e.value.status == 422
    assert "Share with specific people" in e.value.detail
    assert await svc.members(OWNER) == []


@pytest.mark.parametrize(
    "cid",
    ["", "anjali", "https://calendar.google.com/x", "a b@c.com", "../x@y.com", "a@b", "x" * 300],
)
async def test_bad_calendar_ids_never_reach_google(cid: str) -> None:
    fake = FamilyCalendars(roles={ANJALI: "reader"})
    with pytest.raises(FamilyError) as e:
        await (await service(fake)).add(OWNER, "Anjali", cid)
    assert e.value.reason == "invalid" and fake.requests == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, None, 5])
async def test_bad_names_are_refused(name: object) -> None:
    svc = await service(FamilyCalendars(roles={ANJALI: "reader"}))
    with pytest.raises(FamilyError) as e:
        await svc.add(OWNER, name, ANJALI)
    assert e.value.reason == "invalid"


async def test_group_calendar_ids_are_accepted() -> None:
    cid = "c_1a2b3c4d5e6f@group.calendar.google.com"
    m = await (await service(FamilyCalendars(roles={cid: "writer"}))).add(OWNER, "Family", cid)
    assert m.access == "writer" and m.can_write


async def test_at_most_eight_members_and_no_duplicates() -> None:
    ids = {f"p{i}@gmail.com": "reader" for i in range(9)}
    svc = await service(FamilyCalendars(roles=ids))
    for i in range(8):
        await svc.add(OWNER, f"P{i}", f"p{i}@gmail.com")
    with pytest.raises(FamilyError) as full:
        await svc.add(OWNER, "P8", "p8@gmail.com")
    assert full.value.reason == "full" and full.value.status == 409
    await svc.remove(OWNER, (await svc.members(OWNER))[0].id)
    with pytest.raises(FamilyError) as dup2:
        await svc.add(OWNER, "Someone", "p1@gmail.com")
    assert dup2.value.reason == "duplicate" and dup2.value.status == 409
    with pytest.raises(FamilyError) as dup3:
        await svc.add(OWNER, "P2", "p8@gmail.com")  # the same name in any case
    assert dup3.value.reason == "duplicate"


async def test_racing_adds_take_only_free_places() -> None:
    ids = {f"p{i}@gmail.com": "reader" for i in range(10)}
    svc = await service(FamilyCalendars(roles=ids))
    results = await asyncio.gather(
        *(svc.add(OWNER, f"P{i}", f"p{i}@gmail.com") for i in range(10)), return_exceptions=True
    )
    assert sum(1 for r in results if not isinstance(r, Exception)) == 8
    assert len(await svc.members(OWNER)) == 8


async def test_remove_and_unknown_member() -> None:
    svc = await service(FamilyCalendars(roles={ANJALI: "reader"}))
    m = await svc.add(OWNER, "Anjali", ANJALI)
    assert await svc.remove(OWNER, m.id) is True
    assert await svc.remove(OWNER, m.id) is False
    assert await svc.members(OWNER) == []


async def test_members_are_per_owner() -> None:
    docs = MemoryDocs()
    svc = await service(FamilyCalendars(roles={ANJALI: "reader"}), docs)
    await svc.add(OWNER, "Anjali", ANJALI)
    assert await svc.members("someone_else") == []


async def test_google_trouble_is_unavailable_not_not_shared() -> None:
    fake = FamilyCalendars(fail={f"GET /calendar/v3/users/me/calendarList/{ANJALI}": 500})
    with pytest.raises(FamilyError) as e:
        await (await service(fake)).add(OWNER, "Anjali", ANJALI)
    assert e.value.reason == "unavailable" and e.value.status == 503
    assert "fake" not in e.value.detail


async def test_an_unreadable_stored_member_is_ignored_not_fatal() -> None:
    docs = MemoryDocs()
    from jarvis.storage.docs import Set

    await docs.write([Set(f"jarvis_family_calendars/{OWNER}", {"members": [{"junk": 1}]})])
    assert await FamilyStore(docs).members(OWNER) == []
