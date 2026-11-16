# tests/test_r13_a_backup.py -- R13 Part A (docs/plans/r13-wardrobe.md D17, OPS-06; plan review H3):
# the sealed backup file and its two-step restore. Restoring keeps ids and pair links and
# duplicates nothing; the check writes nothing; a restore cut after chunk 2 and run again
# duplicates nothing; another owner's, a cut or a spliced file does not open; photos only when
# ticked; a later change is never undone by an older backup.
from __future__ import annotations

import json
from typing import Any

import pytest
from r13_fakes import UID, ev
from r13_fakes_a import OTHER, Catalog, catalog, fp, jpeg, settings

from jarvis.storage.docs import MemoryDocs
from jarvis.wardrobe.catalog.backup import MAGIC, TOO_BIG
from jarvis.wardrobe.catalog.edits import Edit, NewPiece
from jarvis.wardrobe.catalog.restore import CHUNK, EXPIRED, UNREADABLE
from jarvis.wardrobe.ports import Commit, Refused


def desk(cat: Catalog) -> Any:
    return cat.store.desk  # type: ignore[attr-defined]


async def _seed(cat: Catalog, n: int = 4) -> list[str]:
    drawer = await desk(cat).places.add(UID, "Drawer 2")
    specs = [NewPiece(type="sock", label=f"Sock {i}", place=drawer.id) for i in range(n)]
    ids: list[str] = []
    for i in range(0, n, 20):
        ids += (await desk(cat).service.add(UID, specs[i : i + 20])).ids
    await desk(cat).links.pair(UID, ids[0], ids[1])
    cat.clock.advance(minutes=1)

    async def dep(view: object, tx: object) -> Commit:
        return Commit(events=(ev(ids[0], "deposited", cat.clock()),))

    await cat.store.transact(UID, dep)
    return ids


async def test_the_file_is_sealed_line_by_line_and_says_nothing_in_clear() -> None:
    cat = catalog()
    await _seed(cat)
    body = await desk(cat).backup.file(UID)
    head, *rest = body.rstrip(b"\n").split(b"\n")
    assert head.startswith(MAGIC) and json.loads(head[len(MAGIC) :]) == {
        "v": 1, "kid": "tk1", "photos": False
    }  # fmt: skip
    assert b"Sock" not in body and b"Drawer" not in body and b"deposited" not in body
    assert len(rest) == 1 + 4 + 1  # the index, four logs, the end


async def test_ops06_restoring_into_an_empty_wardrobe_keeps_ids_and_pair_links() -> None:
    cat = catalog()
    ids = await _seed(cat)
    body = await desk(cat).backup.file(UID)
    fresh = catalog(clock=cat.clock)  # a new, empty store (same key)
    check = await desk(fresh).restore.check(UID, body)
    assert (check.counts.added, check.counts.already_there, check.counts.events) == (4, 0, 5)
    assert fresh.docs._data == {}  # noqa: SLF001 - the check writes NOTHING
    done = await desk(fresh).restore.apply(UID, body, check.token)
    assert done.counts.added == 4 and done.chunks == 1
    view = await fresh.store.view(UID)
    assert sorted(view.pieces) == sorted(ids)
    assert [x.pieces for x in view.pairs.values()] == [(ids[0], ids[1])]
    assert view.pieces[ids[0]].state == "in_laundry"  # the history came back and re-folded
    assert [h.event.kind for h in await fresh.store.history(UID, ids[0])] == [
        "registered", "deposited"
    ]  # fmt: skip
    again = await desk(fresh).restore.apply(UID, body, check.token)
    assert again.counts.events == 0 and again.counts.added == 0  # restoring twice adds nothing


async def test_ops06_a_restore_cut_after_chunk_two_runs_again_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = catalog(s=settings(wardrobe_max_pieces=600))
    ids = await _seed(cat, n=CHUNK * 3)
    body = await desk(cat).backup.file(UID)
    fresh = catalog(clock=cat.clock, s=settings(wardrobe_max_pieces=600))
    restore = desk(fresh).restore
    token = (await restore.check(UID, body)).token
    real, calls = restore._chunk, []  # noqa: SLF001

    async def cut(*a: Any, **kw: Any) -> Any:
        if len(calls) == 2:
            raise RuntimeError("the server stopped")
        calls.append(1)
        return await real(*a, **kw)

    monkeypatch.setattr(restore, "_chunk", cut)
    with pytest.raises(RuntimeError):
        await restore.apply(UID, body, token)
    assert len((await fresh.store.view(UID)).pieces) == CHUNK * 2
    monkeypatch.setattr(restore, "_chunk", real)
    done = await restore.apply(UID, body, token)
    assert done.chunks == 3 and done.counts.already_there == CHUNK * 2
    view = await fresh.store.view(UID)
    assert len(view.pieces) == len(ids)
    for pid in ids[:3]:
        assert len(await fresh.store.history(UID, pid)) == len(await cat.store.history(UID, pid))


async def test_a_piece_in_both_keeps_his_current_record_and_a_later_change_wins() -> None:
    cat = catalog()
    ids = await _seed(cat)
    body = await desk(cat).backup.file(UID)
    await desk(cat).service.edit(UID, ids[2], Edit(label="Renamed sock"))
    cat.clock.advance(hours=1)

    async def back(view: object, tx: object) -> Commit:
        return Commit(events=(ev(ids[0], "returned", cat.clock()),))

    await cat.store.transact(UID, back)
    check = await desk(cat).restore.check(UID, body)
    assert (check.counts.already_there, check.counts.superseded, check.counts.events) == (4, 1, 0)
    await desk(cat).restore.apply(UID, body, check.token)
    view = await cat.store.view(UID)
    assert view.pieces[ids[2]].label == "Renamed sock" and view.pieces[ids[0]].state == "ready"


async def test_m2_a_restore_never_re_adds_a_pair_he_undid_or_a_place_he_removed() -> None:
    cat = catalog()
    l1, r1, r2 = (await desk(cat).service.add(UID, [NewPiece(type="sock")] * 3)).ids
    await desk(cat).links.pair(UID, l1, r1)
    shelf = await desk(cat).places.add(UID, "Top shelf")
    body = await desk(cat).backup.file(UID)
    await desk(cat).links.unpair(UID, l1)
    await desk(cat).links.pair(UID, l1, r2)  # he re-paired a replacement half himself (LND-13)
    await desk(cat).places.remove(UID, shelf.id)
    check = await desk(cat).restore.check(UID, body)
    await desk(cat).restore.apply(UID, body, check.token)
    view = await cat.store.view(UID)
    assert [x.pieces for x in view.pairs.values()] == [(l1, r2)]  # one pair a piece
    assert desk(cat).counts.of(view).pairs == 1 and shelf.id not in view.places
    fresh = catalog(clock=cat.clock)  # an empty wardrobe takes every link back
    await desk(fresh).restore.apply(UID, body, (await desk(fresh).restore.check(UID, body)).token)
    again = await fresh.store.view(UID)
    assert [x.pieces for x in again.pairs.values()] == [(l1, r1)] and shelf.id in again.places


async def test_a_piece_purged_since_comes_back_only_when_ticked() -> None:
    cat = catalog()
    ids = await _seed(cat)
    body = await desk(cat).backup.file(UID)
    kept = await desk(cat).bin.remove(UID, ids[3], owner_authored=True)
    assert await cat.undo.purge(UID, kept.id)
    check = await desk(cat).restore.check(UID, body)
    assert check.purged == (ids[3],) and check.counts.purged_since == 1
    await desk(cat).restore.apply(UID, body, check.token)
    assert ids[3] not in (await cat.store.view(UID)).pieces
    await desk(cat).restore.apply(UID, body, check.token, include_purged=[ids[3]])
    assert (await cat.store.view(UID)).pieces[ids[3]].label == "Sock 3"


async def test_photos_come_back_only_when_ticked_and_only_with_their_pieces() -> None:
    cat = catalog()
    [shirt] = (await desk(cat).service.add(UID, [NewPiece(type="shirt")])).ids
    photo, _ = await desk(cat).vault.save(UID, shirt, "front", jpeg())
    await desk(cat).vault.prints.save(UID, shirt, "front", "mnv2-int8-1", fp(9))
    plain, full = await desk(cat).backup.file(UID), await desk(cat).backup.file(UID, photos=True)
    for body, want in ((plain, None), (full, 1)):
        fresh = catalog(clock=cat.clock)
        token = (await desk(fresh).restore.check(UID, body)).token
        await desk(fresh).restore.apply(UID, body, token)
        got = await desk(fresh).vault.get(UID, photo)
        assert (got is not None) == (want is not None)
        prints = await desk(fresh).vault.prints.items(UID, "mnv2-int8-1")
        assert len(prints) == (want or 0)


async def _stored_prints(cat: Catalog) -> list[str]:
    """Every fingerprint entry at rest, opened (not only those `items` would serve)."""
    found = await desk(cat).vault.prints._read(cat.docs.get, UID)  # noqa: SLF001
    return sorted(e["p"] for e in found)


async def test_h4_a_restore_never_writes_back_a_private_or_unticked_pieces_fingerprint() -> None:
    cat = catalog()
    shirt, sock = (
        await desk(cat).service.add(UID, [NewPiece(type="shirt"), NewPiece(type="sock")])
    ).ids
    await desk(cat).vault.prints.save(UID, shirt, "front", "mnv2-int8-1", fp(1))
    await desk(cat).vault.prints.save(UID, sock, "front", "mnv2-int8-1", fp(2))
    body = await desk(cat).backup.file(UID, photos=True)
    await desk(cat).service.edit(UID, shirt, Edit(private=True))  # D9: its fingerprint goes
    kept = await desk(cat).bin.remove(UID, sock, owner_authored=True)
    assert await cat.undo.purge(UID, kept.id)
    assert await _stored_prints(cat) == []
    check = await desk(cat).restore.check(UID, body)
    await desk(cat).restore.apply(UID, body, check.token)  # the sock NOT ticked (D17)
    assert await _stored_prints(cat) == []  # not even sealed at rest
    await desk(cat).restore.apply(UID, body, check.token, include_purged=[sock])
    assert await _stored_prints(cat) == [sock]  # ticked: it comes back with its piece
    assert (await cat.store.view(UID)).pieces[shirt].private  # the current record won


async def test_h4_every_chunk_brings_back_its_own_pieces_fingerprints() -> None:
    cat = catalog(s=settings(wardrobe_max_pieces=600))
    ids = await _seed(cat, n=CHUNK + 5)
    for n, pid in enumerate(ids):
        await desk(cat).vault.prints.save(UID, pid, "front", "mnv2-int8-1", fp(n))
    body = await desk(cat).backup.file(UID, photos=True)
    fresh = catalog(clock=cat.clock, s=settings(wardrobe_max_pieces=600))
    done = await desk(fresh).restore.apply(
        UID, body, (await desk(fresh).restore.check(UID, body)).token
    )
    assert done.chunks == 2 and await _stored_prints(fresh) == sorted(ids)
    again = await desk(fresh).restore.apply(
        UID, body, (await desk(fresh).restore.check(UID, body)).token
    )
    assert again.counts.added == 0 and await _stored_prints(fresh) == sorted(ids)  # never twice


async def test_a_backup_too_large_with_photos_is_refused_in_words() -> None:
    cat = catalog(s=settings(wardrobe_backup_max_mb=5))
    ids = (await desk(cat).service.add(UID, [NewPiece(type="shirt") for _ in range(20)])).ids
    for pid in ids:
        for view in ("front", "back", "detail"):
            await desk(cat).vault.save(UID, pid, view, jpeg(extra=b"x" * 100_000))
    with pytest.raises(Refused) as got:
        await desk(cat).backup.file(UID, photos=True)
    assert str(got.value) == TOO_BIG.format(mb=5)
    assert len(await desk(cat).backup.file(UID)) < 100_000  # without photos it is small


@pytest.mark.parametrize("damage", ["another_owner", "cut", "spliced", "not_ours", "key"])
async def test_a_file_that_is_not_his_whole_backup_does_not_open(damage: str) -> None:
    cat = catalog()
    await _seed(cat)
    body = await desk(cat).backup.file(UID)
    lines = body.rstrip(b"\n").split(b"\n")
    uid = UID
    if damage == "another_owner":
        uid = OTHER
    elif damage == "cut":
        body = b"\n".join(lines[:-1]) + b"\n"
    elif damage == "spliced":
        body = b"\n".join([lines[0], lines[1], lines[3], lines[2], *lines[4:]]) + b"\n"
    elif damage == "not_ours":
        body = b"PK\x03\x04" + body
    else:
        body = body.replace(b'"kid":"tk1"', b'"kid":"tk0"')
    with pytest.raises(Refused) as got:
        await desk(cat).restore.check(uid, body)
    assert str(got.value) == UNREADABLE


async def test_a_token_for_another_file_or_an_hour_old_is_refused() -> None:
    cat = catalog()
    await _seed(cat)
    body = await desk(cat).backup.file(UID)
    token = (await desk(cat).restore.check(UID, body)).token
    other = await desk(cat).backup.file(UID)  # a new file: new seals, another digest
    with pytest.raises(Refused) as got:
        await desk(cat).restore.apply(UID, other, token)
    assert str(got.value) == EXPIRED
    cat.clock.advance(minutes=61)
    with pytest.raises(Refused):
        await desk(cat).restore.apply(UID, body, token)


async def test_a_backup_never_opens_under_another_jarvis_key() -> None:
    from jarvis.keyring import Keyring

    cat = catalog()
    await _seed(cat)
    body = await desk(cat).backup.file(UID)
    elsewhere = catalog(MemoryDocs(), keyring=Keyring(bytes(range(1, 33))))
    with pytest.raises(Refused) as got:
        await desk(elsewhere).restore.check(UID, body)
    assert str(got.value) == UNREADABLE
