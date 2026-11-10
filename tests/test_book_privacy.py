# tests/test_book_privacy.py -- R6 D16 (builder B): the build book's two rows in the privacy
# dashboard. Sealed books: releases, MB, encrypted, export of metadata only, delete with a passkey
# (crypto-shred, and the current release isn't sealed again). Sessions: the live one, delete =
# simple -> end and wipe through the book service.
from __future__ import annotations

import datetime as dt

from book_seal_fakes import (
    UID,
    FakeNotifier,
    FakeSessions,
    FakeSource,
    chunk_paths,
    make_release,
    ring,
    view,
)

from jarvis.buildbook.privacy import BookSealedSource, BookSessionsSource
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.sealer import BookSealer
from jarvis.privacy.ports import PrivacyRegistry, PrivacySource
from jarvis.storage.docs import MemoryDocs


def sealed_rig() -> tuple[MemoryDocs, FakeSource, DocsBookVault, BookSealer, BookSealedSource]:
    docs, source = MemoryDocs(), FakeSource()
    vault = DocsBookVault(docs, ring(), limit_mb=60)
    sealer = BookSealer(source, vault, docs, notifier=FakeNotifier(), audit=None)
    return docs, source, vault, sealer, BookSealedSource(vault, sealer, limit_mb=60)


async def test_both_sources_meet_the_port_and_sit_in_existing_sections() -> None:
    from jarvis.privacy.sources import SEC_ACTIVITY

    *_, sealed = sealed_rig()
    sessions = BookSessionsSource(FakeSessions())  # type: ignore[arg-type]
    assert isinstance(sealed, PrivacySource) and isinstance(sessions, PrivacySource)
    assert (sealed.id, sealed.section) == ("book_sealed", "Documents")
    assert (sessions.id, sessions.section) == ("book_sessions", SEC_ACTIVITY)
    reg = PrivacyRegistry()
    reg.register(sealed)
    reg.register(sessions)
    views = await reg.describe_all(UID)
    assert [v.id for v in views] == ["book_sealed", "book_sessions"]
    assert all(v.available for v in views)


async def test_sealed_books_are_counted_in_mb_encrypted_and_need_a_passkey() -> None:
    _, source, _, sealer, src = sealed_rig()
    empty = await src.describe(UID)
    assert empty.count == 0 and empty.delete == "none"
    for n in (1, 2):
        source.use(*make_release(n))
        await sealer.ensure(UID)
    got = await src.describe(UID)
    assert (got.count, got.unit, got.delete, got.recoverable) == (2, "releases", "passkey", False)
    assert got.encrypted_by_jarvis and got.export and got.size_hint == "0.0 MB of 60 MB"
    assert "3" in got.retention and got.rev
    source.use(*make_release(3))
    await sealer.ensure(UID)
    assert (await src.describe(UID)).rev != got.rev


async def test_the_export_lists_releases_and_holds_no_key() -> None:
    _, source, _, sealer, src = sealed_rig()
    release, _ = make_release(1)
    source.use(*make_release(1))
    await sealer.ensure(UID)
    out = await src.export(UID)
    assert out is not None
    (row,) = out["releases"]
    assert row["id"] == release.id and row["label"] == "R6" and row["sha"] == release.sha
    assert set(row) == {"id", "label", "sha", "committed_at", "sealed_at", "mb"}
    assert "dek" not in str(out) and "bf_" not in str(out)


async def test_delete_shreds_them_all_and_this_release_is_not_sealed_again() -> None:
    docs, source, vault, sealer, src = sealed_rig()
    for n in (1, 2):
        source.use(*make_release(n))
        await sealer.ensure(UID)
    assert await src.delete(UID) == 2
    assert await vault.releases(UID) == () and chunk_paths(docs) == []
    assert (await sealer.ensure(UID)).state == "held"
    assert (await src.describe(UID)).count == 0
    source.use(*make_release(3))
    assert (await sealer.ensure(UID)).state == "sealed"


async def test_delete_without_a_sealer_still_shreds() -> None:
    docs, source, vault, sealer, _ = sealed_rig()
    source.use(*make_release(1))
    await sealer.ensure(UID)
    assert await BookSealedSource(vault, None, limit_mb=60).delete(UID) == 1
    assert chunk_paths(docs) == []


# ---- the live session ------------------------------------------------------------------------


async def test_no_session_means_nothing_to_delete() -> None:
    got = await BookSessionsSource(FakeSessions()).describe(UID)  # type: ignore[arg-type]
    assert got.count == 0 and got.delete == "none" and not got.export
    assert got.encrypted_by_jarvis


async def test_a_live_guest_session_is_shown_and_ended_through_the_service() -> None:
    sessions = FakeSessions()
    sessions.live_view = view("guest")
    ended: list[str] = []

    async def end(uid: str) -> int:
        ended.append(uid)
        return 1

    src = BookSessionsSource(sessions, end=end)  # type: ignore[arg-type]
    got = await src.describe(UID)
    assert got.count == 1 and got.delete == "simple" and "guest" in got.note
    assert "45 minutes" in got.retention
    assert await src.export(UID) is None
    assert await src.delete(UID) == 1 and ended == [UID]


async def test_without_the_service_a_delete_closes_the_session_for_privacy() -> None:
    sessions = FakeSessions()
    sessions.live_view = view("owner")
    src = BookSessionsSource(
        sessions,  # type: ignore[arg-type]
        session_minutes=30,
        clock=lambda: dt.datetime(2026, 11, 10, 9, 5, tzinfo=dt.UTC),
    )
    assert "30 minutes" in (await src.describe(UID)).retention
    assert await src.delete(UID) == 1
    assert sessions.closed == [("bk_" + "1" * 16, "privacy")]
    assert await src.delete(UID) == 0
