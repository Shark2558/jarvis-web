# tests/test_r14_d_lock.py -- R14 D13 (2): a new guest lock keeps the earlier "sessions valid
# after" mark (`buildbook/lock.py` `DocShowLock.set`). Before R14, `set` wrote a fresh document, so
# a guest show opened after "Sign out everywhere" (R7 D21) or a Resume (R6 SEC-4) wiped the mark:
# once that lock was lifted, every cookie session the mark had ended counted again. A lift without
# a mark keeps the earlier one too, and a mark never moves back.
from __future__ import annotations

import pytest
from book_show_fakes import T0, UID, FlakyDocs

from jarvis.buildbook.lock import AFTER, DocShowLock
from jarvis.buildbook.ports import LockUnreadable
from jarvis.storage.docs import Set

PATH = f"jarvis_book_lock/{UID}"
OTHER = "u_fedcba9876543210"
BK = "bk_0123456789abcdef"
MARK = 1_800_000_000.0


async def test_a_lock_set_after_sign_out_everywhere_keeps_the_mark() -> None:
    docs = FlakyDocs()
    lock = DocShowLock(docs)
    await lock.end_sessions(UID, before=MARK)
    state = await lock.set(UID, BK, now=T0)
    assert await lock.view(UID) == (state, MARK)  # this instance at once
    assert await DocShowLock(docs).view(UID) == (state, MARK)  # another instance, from the store
    assert (await docs.get(PATH) or {})[AFTER] == MARK


async def test_the_mark_outlives_the_lock_when_it_is_lifted_without_a_new_one() -> None:
    docs = FlakyDocs()
    lock = DocShowLock(docs)
    await lock.end_sessions(UID, before=MARK)
    state = await lock.set(UID, BK, now=T0)
    assert await lock.lift(UID, state.id) is True
    assert await lock.view(UID) == (None, MARK)
    assert await docs.get(PATH) == {AFTER: MARK}
    assert await DocShowLock(docs).valid_after(UID) == MARK


async def test_a_resume_mark_never_moves_back() -> None:
    docs = FlakyDocs()
    lock = DocShowLock(docs, owners=(UID, OTHER))
    await lock.end_sessions(UID, before=MARK)
    await lock.end_sessions(OTHER, before=MARK)
    state = await lock.set(UID, BK, now=T0)
    assert await lock.lift(UID, state.id, signed_out_before=MARK - 60) is True
    assert await DocShowLock(docs).valid_after(UID) == MARK
    assert await DocShowLock(docs).valid_after(OTHER) == MARK
    later = await lock.set(UID, BK, now=T0)
    assert await lock.lift(UID, later.id, signed_out_before=MARK + 60) is True
    assert await DocShowLock(docs).valid_after(UID) == MARK + 60


async def test_without_a_mark_set_and_lift_are_as_before() -> None:
    docs = FlakyDocs()
    lock = DocShowLock(docs)
    state = await lock.set(UID, BK, now=T0)
    assert AFTER not in (await docs.get(PATH) or {})
    assert await lock.lift(UID, state.id) is True
    assert await docs.get(PATH) is None


async def test_a_lock_is_never_set_over_a_document_it_cannot_read() -> None:
    docs = FlakyDocs()
    await docs.write([Set(PATH, {AFTER: "not a time"})])
    with pytest.raises(LockUnreadable):
        await DocShowLock(docs).set(UID, BK, now=T0)
    docs.fail_reads = True
    with pytest.raises(RuntimeError):
        await DocShowLock(docs).set(UID, BK, now=T0)  # the guest show is then refused (NO_LOCK)


async def test_another_owners_unreadable_document_never_blocks_a_resume() -> None:
    docs = FlakyDocs()
    await docs.write([Set(f"jarvis_book_lock/{OTHER}", {AFTER: "not a time"})])
    lock = DocShowLock(docs, owners=(UID, OTHER))
    state = await lock.set(UID, BK, now=T0)
    assert await lock.lift(UID, state.id, signed_out_before=MARK) is True
    assert await DocShowLock(docs).valid_after(OTHER) == MARK  # healed with the new mark
