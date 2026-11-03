# tests/test_drive_roots.py — slice 12 D1: the owner's chosen Drive folders (drive_roots/{uid} on
# the Docs port, ≤ 20, each with the address that switched it on) and the parents check every read
# passes (walk `parents`, cached 60 s, ≤ 12 levels, to a confirmed root; anything else "not in your
# chosen folders"; fail closed). Storage trouble on a change is RootsUnreadable (503), by type only.
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from drive_fakes import DOC, FakeDrive, StaticTokens

import jarvis.drive.guard as guard_mod
from jarvis.drive.client import DriveClient
from jarvis.drive.guard import CACHE_TTL_S, MAX_DEPTH, ParentsGuard, WalkBudget
from jarvis.drive.ports import MAX_ROOTS, DriveError, NotInRoots, RootsUnreadable
from jarvis.drive.roots import Root, RootsStore
from jarvis.storage.docs import DocTx, MemoryDocs, Set

OWNER = "akash@example.com"
UID = "u_owner"
NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


# ---- the roots store -------------------------------------------------------------------------


async def test_roots_round_trip_and_are_per_owner() -> None:
    docs = MemoryDocs()
    store = RootsStore(docs, now=lambda: NOW)
    assert await store.load(UID) == []
    await store.confirm(UID, "root1", "Registry", email=OWNER)
    await store.confirm(UID, "root2", "Minutes", email="Akash@Example.com")
    got = await store.load(UID)
    assert [(r.id, r.name, r.confirmed_at, r.email) for r in got] == [
        ("root1", "Registry", NOW, OWNER),
        ("root2", "Minutes", NOW, OWNER),
    ]
    assert await store.load("u_other") == []
    assert await docs.get(f"jarvis_drive_roots/{UID}") is not None


async def test_confirming_twice_keeps_one_and_removing_drops_it() -> None:
    store = RootsStore(MemoryDocs(), now=lambda: NOW)
    await store.confirm(UID, "root1", "Registry", email=OWNER)
    await store.confirm(UID, "root1", "Registry renamed", email=OWNER)
    assert [(r.id, r.name) for r in await store.load(UID)] == [("root1", "Registry renamed")]
    await store.remove(UID, "root1")
    await store.remove(UID, "root1")  # idempotent
    assert await store.load(UID) == []


async def test_at_most_twenty_roots() -> None:
    store = RootsStore(MemoryDocs(), now=lambda: NOW)
    for i in range(MAX_ROOTS):
        await store.confirm(UID, f"r{i}", f"Folder {i}", email=OWNER)
    with pytest.raises(ValueError, match=str(MAX_ROOTS)):
        await store.confirm(UID, "r_extra", "One too many", email=OWNER)
    assert len(await store.load(UID)) == MAX_ROOTS


@pytest.mark.parametrize("email", ["", "not-an-address", "a@b@c", "x" * 330 + "@example.com"])
async def test_a_root_needs_a_plausible_owner_address(email: str) -> None:
    with pytest.raises(ValueError):
        await RootsStore(MemoryDocs()).confirm(UID, "root1", "Registry", email=email)


async def test_a_root_stored_before_addresses_loads_without_one() -> None:
    docs = MemoryDocs()
    doc = {"roots": [{"id": "r1", "name": "n", "confirmed_at": "2026-11-03T06:00:00+00:00"}]}
    await docs.write([Set(f"jarvis_drive_roots/{UID}", doc)])
    (root,) = await RootsStore(docs).load(UID)
    assert root.email is None  # such a root is OFF until switched on again (jarvis.drive.live)


class _BrokenTx(MemoryDocs):
    """Storage that fails inside a change (Firestore down, contention, a bad write)."""

    async def transaction(self, fn: Callable[[DocTx], Awaitable[Any]]) -> Any:
        raise RuntimeError("firestore said something with folder-id-123")


async def test_a_storage_error_on_a_change_is_roots_unreadable_logged_by_type_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    store = RootsStore(_BrokenTx())
    with pytest.raises(RootsUnreadable) as e:
        await store.confirm(UID, "root1", "Registry", email=OWNER)
    with pytest.raises(RootsUnreadable):
        await store.remove(UID, "root1")
    assert "firestore" not in str(e.value) and "folder-id-123" not in caplog.text
    assert any(r.__dict__.get("reason") == "RuntimeError" for r in caplog.records)


async def test_the_full_list_is_still_a_value_error() -> None:
    store = RootsStore(MemoryDocs(), now=lambda: NOW)
    for i in range(MAX_ROOTS):
        await store.confirm(UID, f"r{i}", f"Folder {i}", email=OWNER)
    with pytest.raises(ValueError) as e:
        await store.confirm(UID, "r_extra", "One too many", email=OWNER)
    assert not isinstance(e.value, RootsUnreadable)


@pytest.mark.parametrize(
    "doc",
    [
        {"roots": "nope"},
        {"roots": [{"id": "../x", "name": "n", "confirmed_at": "2026-11-03T06:00:00+00:00"}]},
        {"roots": [{"id": "r1", "name": 5, "confirmed_at": "2026-11-03T06:00:00+00:00"}]},
        {"roots": [{"id": "r1", "name": "n", "confirmed_at": "yesterday"}]},
        {
            "roots": [
                {"id": f"r{i}", "name": "n", "confirmed_at": "2026-11-03T06:00:00+00:00"}
                for i in range(MAX_ROOTS + 1)
            ]
        },
        {"nothing": True},
    ],
)
async def test_corrupt_roots_fail_closed(doc: dict) -> None:  # type: ignore[type-arg]
    docs = MemoryDocs()
    await docs.write([Set(f"jarvis_drive_roots/{UID}", doc)])
    with pytest.raises(RootsUnreadable):
        await RootsStore(docs).load(UID)


async def test_storage_errors_fail_closed() -> None:
    class Broken(MemoryDocs):
        async def get(self, path: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("firestore down")

    with pytest.raises(RootsUnreadable):
        await RootsStore(Broken()).load(UID)


@pytest.mark.parametrize("uid", ["", "a/b", "..", "x" * 200])
async def test_bad_owner_ids_are_refused(uid: str) -> None:
    with pytest.raises(ValueError):
        await RootsStore(MemoryDocs()).load(uid)


# ---- the parents check -----------------------------------------------------------------------


def _tree() -> FakeDrive:
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER)
    parent = "root1"
    for i in range(1, 6):  # nested 5 deep
        d.folder(f"n{i}", f"Level {i}", parent)
        parent = f"n{i}"
    d.file("deep", "Deep note", "n5", "deep text")
    d.file("top", "Top note", "root1", "top text")
    d.folder("root2", "Not chosen", shared_by=OWNER)
    d.file("in2", "Other note", "root2", "x")
    return d


async def _no_sleep(_: float) -> None:
    return None


def _guard(d: FakeDrive, roots: set[str], clock: Clock | None = None) -> ParentsGuard:
    client = DriveClient(StaticTokens(), http=d.client(), sleep=_no_sleep)
    return ParentsGuard(client, clock=clock or Clock())


async def test_a_file_in_a_root_and_nested_five_deep_are_allowed() -> None:
    d = _tree()
    g = _guard(d, {"root1"})
    assert (await g.check("top", {"root1"})).id == "top"
    assert (await g.check("deep", {"root1"})).id == "deep"
    assert (await g.check("root1", {"root1"})).id == "root1"  # the root itself


async def test_outside_every_confirmed_root_is_refused() -> None:
    d = _tree()
    g = _guard(d, {"root1"})
    with pytest.raises(NotInRoots):
        await g.check("in2", {"root1"})
    with pytest.raises(NotInRoots):
        await g.check("root2", {"root1"})


async def test_no_confirmed_roots_refuses_everything() -> None:
    d = _tree()
    with pytest.raises(NotInRoots):
        await _guard(d, set()).check("top", set())
    assert d.requests == []  # nothing is even looked up


async def test_trashed_items_are_refused() -> None:
    d = _tree()
    d.items["top"].trashed = True
    with pytest.raises(NotInRoots):
        await _guard(d, {"root1"}).check("top", {"root1"})


async def test_an_item_moved_out_is_refused_once_the_cache_expires() -> None:
    d, clock = _tree(), Clock()
    g = _guard(d, {"root1"}, clock)
    await g.check("deep", {"root1"})
    d.move("n3", "root2")  # the branch moves to a folder the owner didn't choose
    clock.now += 61
    with pytest.raises(NotInRoots):
        await g.check("deep", {"root1"})


def test_folder_metadata_is_cached_for_a_minute_at_most() -> None:
    assert 0 < CACHE_TTL_S <= 60


async def test_parents_are_cached_for_a_minute() -> None:
    d, clock = _tree(), Clock()
    g = _guard(d, {"root1"}, clock)
    await g.check("deep", {"root1"})
    first = len(d.requests)
    clock.now += 59
    await g.check("deep", {"root1"})
    # the item itself is fetched fresh (trashed / moved shows at once); every ancestor is cached
    assert len(d.requests) == first + 1


async def test_whether_a_folder_is_cached_is_asked_publicly() -> None:
    d, clock = _tree(), Clock()
    g = _guard(d, {"root1"}, clock)
    assert g.is_cached("n4") is False
    await g.check("deep", {"root1"})
    assert g.is_cached("n4") is True
    clock.now += 61
    assert g.is_cached("n4") is False
    budget = WalkBudget(5)
    assert not hasattr(budget, "cached")  # the budget no longer reaches into the guard


def test_there_is_no_global_switch_for_the_parents_check() -> None:
    assert not hasattr(guard_mod, "PARENTS_CHECK")


async def test_deeper_than_twelve_levels_is_refused() -> None:
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER)
    parent = "root1"
    for i in range(MAX_DEPTH + 2):
        d.folder(f"x{i}", f"L{i}", parent)
        parent = f"x{i}"
    d.file("abyss", "Too deep", parent, "x")
    with pytest.raises(NotInRoots):
        await _guard(d, {"root1"}).check("abyss", {"root1"})


async def test_a_parent_cycle_is_refused_not_looped() -> None:
    d = FakeDrive()
    d.folder("a", "A", "b", shared_by=OWNER)
    d.folder("b", "B", "a")
    d.file("f", "F", "a", "x")
    with pytest.raises(NotInRoots):
        await _guard(d, {"root1"}).check("f", {"root1"})


async def test_a_lookup_error_fails_closed() -> None:
    d = _tree()
    d.fail["n3"] = 500
    with pytest.raises((NotInRoots, DriveError)):
        await _guard(d, {"root1"}).check("deep", {"root1"})


async def test_a_file_with_two_parents_needs_only_one_confirmed_path() -> None:
    d = _tree()
    d.items["in2"].parents = ["root2", "root1"]
    assert (await _guard(d, {"root1"}).check("in2", {"root1"})).id == "in2"


async def test_root_shared_by_someone_else_never_confirms_its_children() -> None:
    """The guard only follows confirmed roots; the sharer check happens when confirming."""
    d = _tree()
    d.folder("evil", "Shared by a stranger", shared_by="x@evil.example")
    d.file("ev1", "Bait", "evil", "x")
    with pytest.raises(NotInRoots):
        await _guard(d, {"root1"}).check("ev1", {"root1"})


async def test_unknown_mime_files_pass_the_guard_but_reading_decides() -> None:
    d = _tree()
    d.file("odd", "Odd", "root1", b"x", mime="application/x-odd")
    assert (await _guard(d, {"root1"}).check("odd", {"root1"})).mime == "application/x-odd"
    assert DOC  # imported for parity with other tests


async def test_root_dataclass_is_frozen() -> None:
    r = Root("r1", "n", NOW)
    with pytest.raises(AttributeError):
        r.name = "x"  # type: ignore[misc]
