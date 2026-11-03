# tests/test_drive_live_roots.py — slice 12 D1 review F3: a switched-on folder is re-checked on
# every tool call (cached ≤ 60 s per instance): still visible to JARVIS, not in the trash, and still
# the owner's own by the same test as the Use switch, against the address stored when the owner
# switched it on. A sharingUser that is someone else fails it (an editor re-shared it after the
# owner un-shared). A root that fails is OFF for every tool but is kept; the console says so.
from __future__ import annotations

import pytest
from drive_fakes import TXT, FakeDrive, StaticTokens

from jarvis.drive.client import DriveClient
from jarvis.drive.live import ROOT_CHECK_TTL_S
from jarvis.drive.ports import NotInRoots
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.storage.docs import MemoryDocs, Set

OWNER = "akash@example.com"
EDITOR = "colleague@example.com"
UID = "u_owner"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _drive() -> FakeDrive:
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER)
    d.file("doc1", "Steering notes", "root1", "budget is four crore", mime=TXT)
    d.folder("root2", "Board", shared_by=OWNER)
    d.file("doc2", "Board notes", "root2", "board words", mime=TXT)
    return d


async def _confirmed(
    d: FakeDrive, clock: Clock, *ids: str, docs: MemoryDocs | None = None
) -> DriveService:
    client = DriveClient(StaticTokens(), http=d.client())
    svc = DriveService(client, RootsStore(docs or MemoryDocs()), clock=clock)
    for fid in ids:
        await svc.set_use(UID, OWNER, fid, True)
    return svc


def _gets(d: FakeDrive, fid: str) -> int:
    return len([r for r in d.requests if r.url.path == f"/drive/v3/files/{fid}"])


def test_the_root_check_lasts_at_most_a_minute() -> None:
    assert 0 < ROOT_CHECK_TTL_S <= 60


async def test_the_confirming_owners_address_is_stored_with_the_root() -> None:
    d, clock = _drive(), Clock()
    svc = await _confirmed(d, clock)
    await svc.set_use(UID, " Akash@Example.com", "root1", True)
    (root,) = await svc.roots.load(UID)
    assert (root.id, root.email) == ("root1", OWNER)


async def test_unshared_by_the_owner_but_reshared_by_an_editor_is_off_within_a_minute() -> None:
    d, clock = _drive(), Clock()
    svc = await _confirmed(d, clock, "root1")
    assert [i["id"] for i in (await svc.list_folder(UID, "root1"))["items"]] == ["doc1"]
    # the owner removes JARVIS; an editor the owner invited had also shared it with JARVIS
    d.items["root1"].shared_by = EDITOR
    d.items["root1"].owner = OWNER
    clock.now += ROOT_CHECK_TTL_S + 1
    with pytest.raises(NotInRoots):
        await svc.list_folder(UID, "root1")
    with pytest.raises(NotInRoots):
        await svc.read(UID, "doc1")
    assert (await svc.search(UID, "budget"))["results"] == []
    out = await svc.folders(UID)
    assert out["folders"] == [] and "Integrations" in out["note"]
    assert [r.id for r in await svc.roots.load(UID)] == ["root1"]  # kept, not deleted


async def test_the_owner_sharing_it_again_brings_it_back() -> None:
    d, clock = _drive(), Clock()
    svc = await _confirmed(d, clock, "root1")
    d.items["root1"].shared_by = None  # un-shared: JARVIS can't see it at all
    clock.now += ROOT_CHECK_TTL_S + 1
    with pytest.raises(NotInRoots):
        await svc.list_folder(UID, "root1")
    d.items["root1"].shared_by = OWNER
    clock.now += ROOT_CHECK_TTL_S + 1
    assert (await svc.list_folder(UID, "root1"))["items"]


async def test_a_trashed_root_is_off_for_every_tool_and_kept() -> None:
    d, clock = _drive(), Clock()
    svc = await _confirmed(d, clock, "root1", "root2")
    d.items["root1"].trashed = True
    clock.now += ROOT_CHECK_TTL_S + 1
    with pytest.raises(NotInRoots):
        await svc.list_folder(UID, "root1")
    assert (await svc.list_folder(UID, "root2"))["items"]
    assert [f["id"] for f in (await svc.folders(UID))["folders"]] == ["root2"]
    assert {r.id for r in await svc.roots.load(UID)} == {"root1", "root2"}


async def test_the_check_is_cached_per_instance_for_at_most_a_minute() -> None:
    d, clock = _drive(), Clock()
    svc = await _confirmed(d, clock, "root1", "root2")
    before = _gets(d, "root2")
    await svc.list_folder(UID, "root1")
    clock.now += ROOT_CHECK_TTL_S - 1
    await svc.list_folder(UID, "root1")
    assert _gets(d, "root2") == before  # root2 is re-checked from the cache
    clock.now += 2
    await svc.list_folder(UID, "root1")
    assert _gets(d, "root2") == before + 1


async def test_without_sharing_user_the_owners_own_root_stays_on() -> None:
    d, clock = _drive(), Clock()
    d.sharing_user = False
    svc = await _confirmed(d, clock, "root1")
    clock.now += ROOT_CHECK_TTL_S + 1
    assert (await svc.list_folder(UID, "root1"))["items"]


async def test_the_view_tells_the_truth_at_once_and_the_tools_follow() -> None:
    d, clock = _drive(), Clock()
    svc = await _confirmed(d, clock, "root1", "root2")
    d.items["root1"].shared_by = EDITOR
    d.items["root1"].owner = OWNER
    view = await svc.view(UID, OWNER)  # no wait: the owner's screen asks Drive now
    state = {f["id"]: (f["confirmed"], f["readable"]) for f in view["folders"]}
    assert state["root1"] == (True, False) and state["root2"] == (True, True)
    with pytest.raises(NotInRoots):  # ... and the tools learnt it from that check
        await svc.list_folder(UID, "root1")


async def test_switching_off_in_jarvis_stops_access_at_once() -> None:
    d, clock = _drive(), Clock()
    svc = await _confirmed(d, clock, "root1")
    await svc.list_folder(UID, "root1")
    await svc.set_use(UID, OWNER, "root1", False)
    with pytest.raises(NotInRoots):
        await svc.list_folder(UID, "root1")


async def test_a_root_stored_without_an_address_is_off() -> None:
    docs = MemoryDocs()
    await docs.write(
        [
            Set(
                f"jarvis_drive_roots/{UID}",
                {"roots": [{"id": "root1", "name": "R", "confirmed_at": "2026-11-03T06:00:00"}]},
            )
        ]
    )
    d, clock = _drive(), Clock()
    svc = await _confirmed(d, clock, docs=docs)
    with pytest.raises(NotInRoots):
        await svc.list_folder(UID, "root1")
    view = await svc.view(UID, OWNER)
    assert [
        (f["id"], f["confirmed"], f["readable"]) for f in view["folders"] if f["confirmed"]
    ] == [("root1", True, False)]
