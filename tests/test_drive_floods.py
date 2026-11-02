# tests/test_drive_floods.py — slice 12 D1 review F2: anyone can share things with JARVIS's
# address, so a stranger's shares must never break search, the folder list or the Use switch.
# - Use on asks Drive for THAT folder (no 500-folder listing): a folder, not trashed, the same id,
#   and the owner's own (sharingUser = the owner's verified address; without sharingUser, the owner
#   is among `owners`; a sharingUser that is someone else never passes).
# - The list asks first for folders the owner OWNS (strangers can't make those), then a bounded
#   page-by-page list matched on the sharer; everyone else's shares are only a count.
# - One unreadable or failing search hit is "not shown"; the search goes on (still fail closed).
# In every case the owner can still switch on, and find, their own folder.
from __future__ import annotations

import pytest
from drive_fakes import TXT, FakeDrive, StaticTokens

from jarvis.drive.client import DriveClient
from jarvis.drive.ports import DriveUnavailable, NotInRoots
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveRejected, DriveService
from jarvis.storage.docs import MemoryDocs

OWNER = "akash@example.com"
STRANGER = "stranger@evil.example"
EDITOR = "colleague@example.com"
UID = "u_owner"
HUGE = 45_000  # characters in a hostile name (Drive's maximum is unverified)


async def _no_sleep(_: float) -> None:
    return None


def _svc(d: FakeDrive) -> DriveService:
    client = DriveClient(StaticTokens(), http=d.client(), sleep=_no_sleep)
    return DriveService(client, RootsStore(MemoryDocs()))


def _mine(d: FakeDrive, name: str = "Registry") -> None:
    d.folder("mine", name, shared_by=OWNER)
    d.file("mydoc", "Steering notes", "mine", "the budget is four crore", mime=TXT)


async def _owner_can_switch_on_and_find_it(svc: DriveService) -> dict:  # type: ignore[type-arg]
    view = await svc.view(UID, OWNER)
    assert "mine" in [f["id"] for f in view["folders"]], "the owner's folder is not offered"
    await svc.set_use(UID, OWNER, "mine", True)
    listed = await svc.list_folder(UID, "mine")
    assert [i["id"] for i in listed["items"]] == ["mydoc"]
    found = await svc.search(UID, "budget")
    assert "mydoc" in [h["id"] for h in found["results"]], "the owner's file is not found"
    return view


# ---- the Use switch: Drive is asked for the folder itself (b) ---------------------------------


async def test_use_on_asks_drive_for_that_folder_not_a_listing() -> None:
    d = FakeDrive()
    _mine(d)
    svc = _svc(d)
    await svc.set_use(UID, OWNER, "mine", True)
    assert [r.url.path for r in d.requests] == ["/drive/v3/files/mine"]


@pytest.mark.parametrize(
    ("setup", "code", "status"),
    [
        ("stranger", "not_offered", 403),
        ("editor_shared", "not_offered", 403),
        ("not_shared", "not_offered", 409),
        ("trashed", "not_offered", 409),
        ("a_file", "not_a_folder", 422),
        ("no_sharer_not_owner", "not_offered", 403),
    ],
)
async def test_use_on_is_refused_unless_it_is_the_owners_own_live_folder(
    setup: str, code: str, status: int
) -> None:
    d = FakeDrive()
    if setup == "stranger":
        d.folder("x", "Registry", shared_by=STRANGER)
    elif setup == "editor_shared":  # the owner's folder, but shared with JARVIS by someone else
        d.folder("x", "Registry", shared_by=EDITOR, owner=OWNER)
    elif setup == "not_shared":
        d.folder("x", "Registry")
    elif setup == "trashed":
        d.folder("x", "Registry", shared_by=OWNER, trashed=True)
    elif setup == "a_file":
        d.file("x", "Registry", None, "x", shared_by=OWNER)
    else:  # no sharingUser (consumer accounts?) and the owner is not among the owners
        d.sharing_user = False
        d.folder("x", "Registry", shared_by=STRANGER)
    svc = _svc(d)
    with pytest.raises(DriveRejected) as e:
        await svc.set_use(UID, OWNER, "x", True)
    assert (e.value.code, e.value.status) == (code, status)
    assert "stranger" not in str(e.value) and "colleague" not in str(e.value)
    assert await svc.roots.load(UID) == []


async def test_without_sharing_user_the_owners_own_folder_can_still_be_switched_on() -> None:
    """Nobody has verified that Drive sends sharingUser for consumer accounts: the owners
    fallback keeps the switch usable."""
    d = FakeDrive()
    d.sharing_user = False
    _mine(d)
    await _owner_can_switch_on_and_find_it(_svc(d))


async def test_the_owners_address_is_compared_case_insensitively() -> None:
    d = FakeDrive()
    _mine(d)
    svc = _svc(d)
    await svc.set_use(UID, "  Akash@Example.com ", "mine", True)
    assert [r.id for r in await svc.roots.load(UID)] == ["mine"]


# ---- the list: flood-proof (c, d) ----------------------------------------------------------------


async def test_a_long_named_share_breaks_nothing() -> None:
    d = FakeDrive()
    d.folder("long", "x" * 301, shared_by=STRANGER)
    _mine(d, name="y" * 301)  # the owner's own folder with a very long name too
    view = await _owner_can_switch_on_and_find_it(_svc(d))
    (mine,) = [f for f in view["folders"] if f["id"] == "mine"]
    assert 0 < len(mine["name"]) <= 300
    assert view["others"] == 1


async def test_seventy_huge_names_cannot_hide_the_owners_folder() -> None:
    d = FakeDrive()
    for i in range(70):  # ~3 MB in one 100-entry page: over the 2 MB answer cap
        d.folder(f"huge{i}", f"{i} " + "N" * HUGE, shared_by=STRANGER)
    _mine(d)
    view = await _owner_can_switch_on_and_find_it(_svc(d))
    assert view["others"] == 70
    assert "N" * 400 not in str(view)


async def test_more_than_five_hundred_shares_cannot_hide_the_owners_folder() -> None:
    d = FakeDrive()
    for i in range(600):
        d.folder(f"spam{i}", f"Spam {i}", shared_by=STRANGER)
    _mine(d)
    svc = _svc(d)
    view = await _owner_can_switch_on_and_find_it(svc)
    assert 0 < view["others"] <= 100 and view["others_more"] is True
    lists = [r for r in d.requests if r.url.path == "/drive/v3/files"]
    assert lists and all(int(r.url.params["pageSize"]) <= 25 for r in lists)


async def test_seventy_huge_named_matching_files_cannot_break_the_search() -> None:
    d = FakeDrive()
    d.folder("evil", "Shared by a stranger", shared_by=STRANGER)
    for i in range(70):  # 50 hits a page used to be ~2.2 MB: over the cap
        d.file(f"big{i}", f"budget {i} " + "N" * HUGE, "evil", "budget", mime=TXT)
    _mine(d)
    await _owner_can_switch_on_and_find_it(_svc(d))


async def test_a_failing_strangers_list_still_shows_the_owners_folders() -> None:
    d = FakeDrive()
    d.folder("bad", "Bad", shared_by=STRANGER)
    _mine(d)
    d.fail["shared"] = 500  # the unfiltered list (the one strangers can flood) fails
    view = await _owner_can_switch_on_and_find_it(_svc(d))
    assert view["others_more"] is True


async def test_a_folder_the_owner_shares_but_does_not_own_is_still_offered() -> None:
    """Sharer-matched: e.g. a colleague's folder the owner may share; bounded, after the owned."""
    d = FakeDrive()
    d.folder("mine", "Team folder", shared_by=OWNER, owner=EDITOR)
    d.file("mydoc", "Steering notes", "mine", "the budget is four crore", mime=TXT)
    await _owner_can_switch_on_and_find_it(_svc(d))


async def test_others_are_only_a_count() -> None:
    d = FakeDrive()
    d.folder("evil", "Free money", shared_by=STRANGER)
    d.folder("ed", "Shared on by an editor", shared_by=EDITOR, owner=OWNER)
    _mine(d)
    view = await _svc(d).view(UID, OWNER)
    assert view["others"] == 2 and isinstance(view["others"], int)
    assert (
        "Free money" not in str(view) and "editor" not in str(view) and "stranger" not in str(view)
    )


# ---- search: one bad hit is "not shown" (a) ------------------------------------------------------


async def test_fifty_decoy_hits_in_separate_subfolders_cannot_hide_the_owners_file() -> None:
    d = FakeDrive()
    d.folder("evil", "Shared by a stranger", shared_by=STRANGER)
    for i in range(50):  # Drive returns these first
        d.folder(f"sub{i}", f"Sub {i}", "evil")
        d.file(f"decoy{i}", f"budget {i}", f"sub{i}", "budget budget", mime=TXT)
    _mine(d)
    svc = await _confirmed(d)
    out = await svc.search(UID, "budget")
    assert [h["id"] for h in out["results"]] == ["mydoc"]
    assert not any("decoy" in h["id"] for h in out["results"])


@pytest.mark.parametrize("trouble", [500, 403, "unreadable"])
async def test_one_failing_hit_does_not_abort_the_search(trouble: int | str) -> None:
    d = FakeDrive()
    d.folder("evil", "Shared by a stranger", shared_by=STRANGER)
    d.folder("odd", "Odd", "evil")
    d.file("bait", "budget bait", "odd", "budget", mime=TXT)
    _mine(d)
    if trouble == "unreadable":
        d.items["odd"].parents = ["evil", "not an id!"]  # still visible; its metadata won't parse
    else:
        d.fail["odd"] = int(trouble)
    svc = await _confirmed(d)
    out = await svc.search(UID, "budget")
    assert [h["id"] for h in out["results"]] == ["mydoc"]
    assert "bait" not in str(out)


async def test_a_failing_hit_alone_is_not_nothing_matched() -> None:
    d = FakeDrive()
    d.folder("evil", "Shared by a stranger", shared_by=STRANGER)
    d.folder("odd", "Odd", "evil")
    d.file("bait", "budget bait", "odd", "budget", mime=TXT)
    _mine(d)
    d.items["mydoc"].content = b"nothing relevant"
    d.fail["odd"] = 403
    svc = await _confirmed(d)
    out = await svc.search(UID, "budget")
    assert out["results"] == []
    assert "couldn't be checked" in out["note"] and "Nothing" not in out["note"]


async def test_drive_unreachable_still_fails_the_search() -> None:
    d = FakeDrive()
    _mine(d)
    svc = await _confirmed(d)

    async def down() -> str:
        raise DriveUnavailable("Couldn't reach Google Drive; try again shortly.")

    svc.client.tokens.token = down  # type: ignore[method-assign]
    with pytest.raises(DriveUnavailable):
        await svc.search(UID, "budget")


async def test_a_strangers_file_never_appears_even_when_it_matches() -> None:
    d = FakeDrive()
    d.folder("evil", "Shared by a stranger", shared_by=STRANGER)
    d.file("bait", "budget bait", "evil", "budget", mime=TXT)
    _mine(d)
    svc = await _confirmed(d)
    out = await svc.search(UID, "budget")
    assert [h["id"] for h in out["results"]] == ["mydoc"]
    with pytest.raises(NotInRoots):
        await svc.read(UID, "bait")


async def _confirmed(d: FakeDrive) -> DriveService:
    svc = _svc(d)
    await svc.set_use(UID, OWNER, "mine", True)
    return svc
