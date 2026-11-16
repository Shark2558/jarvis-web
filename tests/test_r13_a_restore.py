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
