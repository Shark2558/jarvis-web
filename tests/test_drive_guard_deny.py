# tests/test_drive_guard_deny.py -- R2 D9: the DigiLocker inbox is a folder Drive tools can never
# read. `ParentsGuard.check(file_id, roots, deny=...)` refuses any file whose ancestors include a
# denied id (and the denied folder itself), even when a chosen root is also an ancestor.
from __future__ import annotations

import pytest
from drive_fakes import FakeDrive, StaticTokens

from jarvis.drive.client import DriveClient
from jarvis.drive.guard import ParentsGuard, WalkBudget
from jarvis.drive.ports import NotInRoots

OWNER = "akash@example.com"


def _tree() -> FakeDrive:
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER)
    d.file("ok1", "Minutes", "root1", "fine")
    d.folder("inbox", "Vault inbox", "root1")  # an inbox that sits below a chosen root
    d.file("pan", "PAN card", "inbox", "ABCDE1234F")
    d.folder("deep", "Deeper", "inbox")
    d.file("deepfile", "Deep", "deep", "secret")
    d.folder("rootless", "Elsewhere", shared_by=OWNER)
    d.file("loose", "Loose", "rootless", "x")
    return d


def _guard(d: FakeDrive) -> ParentsGuard:
    return ParentsGuard(DriveClient(StaticTokens(), http=d.client()))


async def test_without_deny_the_existing_behaviour_is_unchanged() -> None:
    g = _guard(_tree())
    assert (await g.check("ok1", {"root1"})).id == "ok1"
    assert (await g.check("pan", {"root1"})).id == "pan"  # the old guard let it through


@pytest.mark.parametrize("fid", ["pan", "deepfile", "inbox", "deep"])
async def test_a_file_inside_the_denied_folder_is_refused_even_under_a_root(fid: str) -> None:
    g = _guard(_tree())
    with pytest.raises(NotInRoots):
        await g.check(fid, {"root1"}, deny=("inbox",))


async def test_other_files_still_pass_with_a_deny_list() -> None:
    g = _guard(_tree())
    assert (await g.check("ok1", {"root1"}, deny=("inbox",))).id == "ok1"
    assert (await g.check("loose", {"rootless"}, deny=("inbox",))).id == "loose"


async def test_still_owner_shared_roots_only_and_walks_parents() -> None:
    g = _guard(_tree())
    with pytest.raises(NotInRoots):
        await g.check("loose", {"root1"}, deny=("inbox",))  # not under a chosen root
    with pytest.raises(NotInRoots):
        await g.check("ok1", set(), deny=("inbox",))  # no roots: refused


async def test_a_walk_cut_short_with_a_deny_list_fails_closed() -> None:
    d = FakeDrive()
    d.folder("root1", "R", shared_by=OWNER)
    parent = "root1"
    for i in range(14):  # deeper than MAX_DEPTH
        d.folder(f"f{i}", f"F{i}", parent)
        parent = f"f{i}"
    d.file("bottom", "B", parent, "x")
    g = _guard(d)
    with pytest.raises(NotInRoots):
        await g.check("bottom", {"root1"}, deny=("inbox",))


async def test_inside_honours_deny_for_a_search_walk() -> None:
    g = _guard(_tree())
    pan = await g.client.get("pan")
    ok = await g.client.get("ok1")
    assert not await g.inside(pan, {"root1"}, WalkBudget(20), deny=("inbox",))
    assert await g.inside(ok, {"root1"}, WalkBudget(20), deny=("inbox",))


async def test_denied_ids_are_matched_exactly() -> None:
    g = _guard(_tree())
    assert (await g.check("ok1", {"root1"}, deny=("inbo", "root"))).id == "ok1"
