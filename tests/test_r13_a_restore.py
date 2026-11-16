# tests/test_r13_a_restore.py -- R13 Part A (docs/plans/r13-wardrobe.md D17, OPS-06; review A-1
# L1-L5): the backup file's head and lines are bound to one file of his, the restore token can't be
# forged, replayed after a purge or crash on odd input, the file is parsed off the event loop, and
# chunks are closed by bytes as well as by count. Fixed clock; the real part on fakes.
from __future__ import annotations

import threading
from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_a import Catalog, catalog

from jarvis.wardrobe.catalog import restore as restore_mod
from jarvis.wardrobe.catalog.edits import NewPiece


def desk(cat: Catalog) -> Any:
    return cat.store.desk  # type: ignore[attr-defined]


async def _shirts(cat: Catalog, n: int = 3) -> list[str]:
    return list((await desk(cat).service.add(UID, [NewPiece(type="shirt")] * n)).ids)


async def test_l5_the_file_is_parsed_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    cat = catalog()
    await _shirts(cat)
    body = await desk(cat).backup.file(UID)
    seen: list[int] = []
    real = restore_mod.parse

    def spy(*a: Any, **kw: Any) -> Any:
        seen.append(threading.get_ident())
        return real(*a, **kw)

    monkeypatch.setattr(restore_mod, "parse", spy)
    check = await desk(cat).restore.check(UID, body)
    await desk(cat).restore.apply(UID, body, check.token)
    assert len(seen) == 2 and threading.get_ident() not in seen  # voice and chat keep running


async def test_l1_the_head_is_bound_to_the_file_and_a_flipped_head_does_not_open() -> None:
    from jarvis.wardrobe.catalog.restore import UNREADABLE
    from jarvis.wardrobe.ports import Refused

    cat = catalog()
    await _shirts(cat)
    body = await desk(cat).backup.file(UID)
    flipped = body.replace(b'"photos":false', b'"photos":true', 1)
    assert flipped != body
    with pytest.raises(Refused) as got:
        await desk(cat).restore.check(UID, flipped)  # "with photos" is not his to claim
    assert str(got.value) == UNREADABLE


async def test_l1_a_line_from_another_of_his_files_does_not_open() -> None:
    from jarvis.wardrobe.catalog.restore import UNREADABLE
    from jarvis.wardrobe.ports import Refused

    cat = catalog()
    await _shirts(cat)
    one, two = await desk(cat).backup.file(UID), await desk(cat).backup.file(UID)
    a, b = one.rstrip(b"\n").split(b"\n"), two.rstrip(b"\n").split(b"\n")
    for spliced in (
        [a[0], a[1], b[2], *a[3:]],  # line 2 of his other file, in its own place
        [b[0], *a[1:]],  # the other file's head on this one's lines
    ):
        with pytest.raises(Refused) as got:
            await desk(cat).restore.check(UID, b"\n".join(spliced) + b"\n")
        assert str(got.value) == UNREADABLE
    assert (await desk(cat).restore.check(UID, one)).counts.already_there == 3  # whole: it opens


async def test_l2_a_forged_empty_digit_another_owners_or_an_odd_token_is_refused() -> None:
    from r13_fakes_a import OTHER

    from jarvis.wardrobe.catalog.restore import EXPIRED
    from jarvis.wardrobe.ports import Refused

    cat = catalog()
    await _shirts(cat)
    body = await desk(cat).backup.file(UID)
    token = (await desk(cat).restore.check(UID, body)).token
    head, empty, mac = token.split("-")
    await desk(cat).service.add(OTHER, [NewPiece(type="shirt")])
    theirs = await desk(cat).backup.file(OTHER)
    for bad in (
        f"{head}-{'1' if empty == '0' else '0'}-{mac}",  # "it was empty" is not his to claim
        (await desk(cat).restore.check(OTHER, theirs)).token,  # another owner's check
        f"{head}-{empty}-{mac[:-1]}é",  # not ASCII: refused in words, never a crash
        "",
    ):
        with pytest.raises(Refused) as got:
            await desk(cat).restore.apply(UID, body, bad)
        assert str(got.value) == EXPIRED


async def test_l2_an_empty_check_replayed_after_a_purge_says_check_again() -> None:
    from jarvis.wardrobe.catalog.restore import EXPIRED
    from jarvis.wardrobe.ports import Refused

    cat = catalog()
    ids = await _shirts(cat)
    body = await desk(cat).backup.file(UID)
    fresh = catalog(clock=cat.clock)
    token = (await desk(fresh).restore.check(UID, body)).token  # his wardrobe was empty
    await desk(fresh).restore.apply(UID, body, token)
    kept = await desk(fresh).bin.remove(UID, ids[0], owner_authored=True)
    assert await fresh.undo.purge(UID, kept.id)
    with pytest.raises(Refused) as got:
        await desk(fresh).restore.apply(UID, body, token)  # within the hour, the same file
    assert str(got.value) == EXPIRED
    assert ids[0] not in (await fresh.store.view(UID)).pieces  # never back unticked
    again = await desk(fresh).restore.check(UID, body)
    assert again.purged == (ids[0],)  # checked again: purged since, his to tick


async def test_l3_a_chunk_closes_by_bytes_as_well_as_by_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from r13_fakes import ev

    from jarvis.wardrobe.ports import Commit

    cat = catalog()
    ids = await _shirts(cat, 12)
    for pid in ids:  # heavy, old histories: 150 events each

        async def seen(view: object, tx: object, pid: str = pid) -> Commit:
            return Commit(events=tuple(ev(pid, "seen", cat.clock(), note="n" * 100)
                                       for _ in range(150)))  # fmt: skip

        await cat.store.transact(UID, seen)
    body = await desk(cat).backup.file(UID)
    limit = 250_000  # stands in for about 8 MiB, under Firestore's 10 MiB a commit
    monkeypatch.setattr(restore_mod, "CHUNK_BYTES", limit)
    fresh = catalog(clock=cat.clock)
    real, sizes = fresh.docs.transaction, []

    async def measured(fn: Any) -> Any:
        async def inner(tx: Any) -> Any:
            out = await fn(tx)
            sizes.append(sum(len(json.dumps(op.data)) for op in tx.ops if hasattr(op, "data")))
            return out

        return await real(inner)

    monkeypatch.setattr(fresh.docs, "transaction", measured)
    done = await desk(fresh).restore.apply(
        UID, body, (await desk(fresh).restore.check(UID, body)).token
    )
    assert done.chunks >= 3 and done.counts.added == 12  # 12 pieces: far under 50 a chunk
    assert sizes and max(sizes) <= limit
    for pid in ids:
        assert len(await fresh.store.history(UID, pid)) == 151


async def test_l4_a_backup_the_restore_would_refuse_is_refused_in_words_without_photos_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.wardrobe.catalog.backup import TOO_BIG_HISTORY
    from jarvis.wardrobe.ports import Refused

    cat = catalog()
    await _shirts(cat, 20)
    backup = desk(cat).backup
    plain, full = await backup.estimate(UID, photos=False), await backup.estimate(UID, photos=True)
    body = await backup.file(UID)
    assert len(body) <= plain <= full  # never under the real file: the check errs safe
    monkeypatch.setattr(backup, "max_bytes", len(body))  # a long history, near the cap
    with pytest.raises(Refused) as got:
        await backup.file(UID)  # refused before a byte is sent, not by the restore's 413
    assert str(got.value) == TOO_BIG_HISTORY.format(mb=backup.max_mb)
