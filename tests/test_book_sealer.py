# tests/test_book_sealer.py -- R6 D7 (builder B): BookSealer.ensure seals the release this server
# runs once (lease, seal, prune to 3, audit book_seal, one book_sealed notice), sends
# book_seal_failed once per failure, never seals at start-up, refuses a book holding an owner
# e-mail (D3), respects a Privacy hold, and shares one run between racing callers; BookSealJob.
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import pytest
from book_seal_fakes import (
    NOW,
    OTHER,
    UID,
    FakeAudit,
    FakeNotifier,
    FakeSource,
    FlakyDocs,
    big_zip,
    chunk_paths,
    failed_release,
    fixture_book,
    make_release,
    ring,
)

from jarvis.buildbook.model import FileKind, Release
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.seal_state import LEASE_S
from jarvis.buildbook.sealer import (
    BookSealer,
    BookSealJob,
    SealOutcome,
    holds_owner_email,
)
from jarvis.storage.docs import MemoryDocs
from jarvis.ticks import FAILED_COUNT, TickJob

OWNER_EMAIL = "akash.owner2558@example.com"


class Rig:
    def __init__(self, docs: MemoryDocs | FlakyDocs | None = None, **kw: Any) -> None:
        self.docs = docs or MemoryDocs()
        self.clock = {"now": NOW}
        self.source = FakeSource()
        self.notes = FakeNotifier()
        self.audit = FakeAudit()
        limit = kw.pop("limit_mb", 60)
        self.vault = DocsBookVault(self.docs, ring(), limit_mb=limit, clock=self.now)
        self.kw = {"limit_mb": limit, **kw}
        self.sealer = self.new_sealer()

    def now(self) -> dt.datetime:
        return self.clock["now"]

    def new_sealer(self) -> BookSealer:
        """A fresh process: same storage, nothing remembered in memory."""
        return BookSealer(
            self.source,
            self.vault,
            self.docs,
            notifier=self.notes,
            audit=self.audit,
            owner_emails=self.kw.get("owner_emails", (OWNER_EMAIL,)),
            honorific=self.kw.get("honorific", "Sir"),
            limit_mb=self.kw["limit_mb"],
            clock=self.now,
        )

    def deploy(self, n: int, **kw: Any) -> Release:
        release, files = make_release(n, **kw)
        self.source.use(release, files)
        self.clock["now"] = NOW + dt.timedelta(hours=n)
        return release


def inner(docs: MemoryDocs | FlakyDocs) -> MemoryDocs:
    return docs.inner if isinstance(docs, FlakyDocs) else docs


# ---- never at start-up; nothing to seal ------------------------------------------------------


async def test_building_the_sealer_touches_nothing() -> None:
    rig = Rig()
    rig.deploy(1)
    rig.new_sealer()
    BookSealJob(rig.sealer, UID)
    assert (rig.docs.reads, rig.docs.sets, rig.source.reads) == (0, 0, 0)
    assert rig.notes.sent == [] and rig.audit.rows == []


async def test_no_book_on_this_server_means_nothing_happens() -> None:
    rig = Rig()
    out = await rig.sealer.ensure(UID)
    assert out == SealOutcome("none") and rig.docs.sets == 0 and rig.notes.sent == []


async def test_a_failed_build_is_told_once_even_across_a_restart() -> None:
    rig = Rig()
    bad = failed_release(1)
    rig.source.use(bad)
    assert (await rig.sealer.ensure(UID)).state == "unbuilt"
    assert (await rig.sealer.ensure(UID)).state == "unbuilt"
    assert (await rig.new_sealer().ensure(UID)).state == "unbuilt"
    assert rig.notes.sent == [
        (
            UID,
            "book_seal_failed",
            f"Sir, the build book for R6 ({bad.id}) could not be built at deploy, "
            "so it isn't sealed.",
        )
    ]


# ---- seal once, tell once --------------------------------------------------------------------


async def test_the_first_run_seals_audits_and_tells_once() -> None:
    rig = Rig(honorific="Ma'am")
    release = rig.deploy(1)
    out = await rig.sealer.ensure(UID)
    assert out == SealOutcome("sealed", release.id, kept=1)
    assert [r.id for r in await rig.vault.releases(UID)] == [release.id]
    assert rig.notes.sent == [
        (
            UID,
            "book_sealed",
            f"Ma'am, the build book for R6 ({release.id}) is sealed in your vault with this "
            "release's code. 1 release kept.",
        )
    ]
    (row,) = rig.audit.rows
    assert row["tool"] == "book_seal" and row["outcome"] == "executed" and row["detail"] == ""
    assert row["args"] == {"release": release.id, "label": "R6", "removed": [], "mb": 0.0}
    assert (await rig.sealer.ensure(UID)).state == "kept"
    assert (await rig.new_sealer().ensure(UID)).state == "kept"  # a restart: no second notice
    assert len(rig.notes.sent) == 1 and len(rig.audit.rows) == 1


async def test_a_fourth_release_keeps_three_and_says_so() -> None:
    rig = Rig()
    ids = []
    for n in (1, 2, 3, 4):
        ids.append(rig.deploy(n).id)
        await rig.sealer.ensure(UID)
    assert [r.id for r in await rig.vault.releases(UID)] == ids[:0:-1]
    assert rig.notes.kinds() == ["book_sealed"] * 4
    assert rig.notes.sent[-1][2].endswith(f"({ids[3]}) is sealed in your vault with this "
                                          "release's code. 3 releases kept.")  # fmt: skip
    assert rig.audit.rows[-1]["args"]["removed"] == [ids[0]]
    assert len(chunk_paths(inner(rig.docs))) == 3 * 2  # one book + one source chunk each


async def test_over_the_cap_the_oldest_goes_first_so_the_new_release_fits() -> None:
    rig = Rig(limit_mb=2)
    ids = [
        (rig.deploy(n, source=big_zip(n, 600_000)), await rig.sealer.ensure(UID))[0].id
        for n in (1, 2, 3)
    ]
    out = await rig.sealer.ensure(UID)
    assert out.state == "kept"
    rig.deploy(4, source=big_zip(4, 600_000))
    out = await rig.sealer.ensure(UID)
    assert out.state == "sealed" and out.removed == (ids[0],) and out.kept == 3


# ---- refusals and failures ---------------------------------------------------------------------


def _book_saying(text: str) -> Any:
    book = fixture_book()
    return book.model_copy(update={"digest": book.digest.model_copy(update={"overview": text})})


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("Built by AKASH.Owner2558@Example.com.", "your e-mail address"),
        ("Ask akash.owner2558 about it.", "a word from your e-mail address"),  # D3 amendment
        ("Mail: akash․owner2558@example．com", "your e-mail address"),  # look-alike dots: NFKC
    ],
)
async def test_a_book_holding_an_owner_address_is_refused_and_told_once(
    text: str, what: str
) -> None:
    rig = Rig()
    release = rig.deploy(1, book=_book_saying(text))
    assert (await rig.sealer.ensure(UID)).state == "failed"
    assert (await rig.sealer.ensure(UID)).state == "failed"
    assert await rig.vault.releases(UID) == () and chunk_paths(inner(rig.docs)) == []
    assert rig.notes.sent == [
        (
            UID,
            "book_seal_failed",
            f"Sir, the build book for R6 ({release.id}) holds {what}, so I refused to seal it.",
        )
    ]
    assert OWNER_EMAIL not in str(rig.notes.sent) and rig.audit.rows == []


def test_the_owner_address_check_matches_whole_words_only() -> None:
    emails = (OWNER_EMAIL, "me@example.com")
    assert holds_owner_email(b'{"a":"akash.owner2558"}', emails)
    assert holds_owner_email(b'{"a":"akash.owner2558\\u0040example.com"}', emails)
    # D3 amendment: "akash" is the distinctive token ("owner" is JARVIS's own word), whole words
    assert holds_owner_email(b'{"a":"akash.owner25589"}', emails)
    assert not holds_owner_email(b'{"a":"xakash.owner2558 akashic owner"}', emails)
    assert not holds_owner_email(b'{"a":"tell me about it"}', emails)  # a 2-letter local part
    assert not holds_owner_email(b'{"a":"akash.owner2558"}', ())


async def test_a_seal_that_fails_is_told_once_and_retried_by_the_next_run() -> None:
    docs = FlakyDocs()
    rig = Rig(docs)
    release = rig.deploy(1)
    docs.fail_writes = 99
    assert (await rig.sealer.ensure(UID)).state == "failed"
    assert (await rig.sealer.ensure(UID)).state == "failed"
    docs.fail_writes = 0
    assert (await rig.sealer.ensure(UID)).state == "sealed"
    assert rig.notes.sent[0] == (
        UID,
        "book_seal_failed",
        f"Sir, the build book for R6 ({release.id}) could not be sealed in your vault; "
        "I'll try again.",
    )
    assert rig.notes.kinds() == ["book_seal_failed", "book_sealed"]


async def test_a_tampered_index_is_told_once_and_left_as_it_is() -> None:
    rig = Rig()
    rig.deploy(1)
    await rig.sealer.ensure(UID)
    path = f"jarvis_book/{UID}"
    rig.docs._data[path]["blob"] = rig.docs._data[path]["blob"][:-4] + "AAA="
    before = dict(rig.docs._data[path])
    rig.deploy(2)
    assert (await rig.sealer.ensure(UID)).state == "failed"
    assert (await rig.new_sealer().ensure(UID)).state == "failed"
    assert rig.docs._data[path] == before
    assert rig.notes.kinds() == ["book_sealed", "book_seal_failed"]
    assert rig.notes.sent[-1][2] == (
        "Sir, your sealed build books failed their integrity check, so they stay closed."
    )


async def test_a_tampered_read_is_reported_once_per_release() -> None:
    rig = Rig()
    release = rig.deploy(1)
    await rig.sealer.ensure(UID)
    for _ in range(2):
        await rig.sealer.report_tampered(UID, release.id, "R6")
    await rig.new_sealer().report_tampered(UID, release.id, "R6")
    assert rig.notes.sent[1:] == [
        (
            UID,
            "book_seal_failed",
            f"Sir, the sealed build book for R6 ({release.id}) failed its integrity check, "
            "so it stays closed.",
        )
    ]


async def test_files_that_no_longer_match_their_release_are_a_failure() -> None:
    rig = Rig()
    release = rig.deploy(1)
    rig.source.files = {**rig.source.files, "source": b"PK changed"}
    assert (await rig.sealer.ensure(UID)).state == "failed"
    assert rig.notes.kinds() == ["book_seal_failed"]
    assert release.id in rig.notes.sent[0][2]


# ---- notices and audit that fail -----------------------------------------------------------


async def test_a_notice_that_could_not_go_is_sent_by_the_next_run() -> None:
    rig = Rig()
    rig.deploy(1)
    rig.notes.fail = True
    assert (await rig.sealer.ensure(UID)).state == "sealed"
    rig.notes.fail = False
    assert (await rig.new_sealer().ensure(UID)).state == "kept"
    assert (await rig.sealer.ensure(UID)).state == "kept"
    assert rig.notes.kinds() == ["book_sealed"]


async def test_an_audit_outage_never_stops_the_seal_or_its_notice() -> None:
    rig = Rig()
    rig.deploy(1)
    rig.audit.fail = True
    assert (await rig.sealer.ensure(UID)).state == "sealed"
    assert rig.notes.kinds() == ["book_sealed"]


async def test_no_notifier_still_seals() -> None:
    rig = Rig()
    rig.deploy(1)
    sealer = BookSealer(rig.source, rig.vault, rig.docs, notifier=None, audit=None, clock=rig.now)
    assert (await sealer.ensure(UID)).state == "sealed"


# ---- the lease, races, the Privacy hold ----------------------------------------------------


async def test_a_live_lease_held_elsewhere_waits_and_an_expired_one_is_taken() -> None:
    rig = Rig()
    rig.deploy(1)
    until = (rig.now() + dt.timedelta(seconds=60)).isoformat()
    rig.docs._data[f"jarvis_book_lease/{UID}"] = {"holder": "elsewhere", "until": until}
    assert (await rig.sealer.ensure(UID)).state == "busy"
    assert await rig.vault.releases(UID) == ()
    rig.clock["now"] += dt.timedelta(seconds=LEASE_S + 1)
    assert (await rig.sealer.ensure(UID)).state == "sealed"
    assert LEASE_S == 120
    lease = rig.docs._data[f"jarvis_book_lease/{UID}"]
    assert lease.get("holder") is None  # given back after the seal


async def test_two_racing_sealers_seal_once_and_tell_once() -> None:
    rig = Rig()
    rig.deploy(1)
    a, b = rig.new_sealer(), rig.new_sealer()
    outs = await asyncio.gather(a.ensure(UID), b.ensure(UID))
    assert sorted(o.state for o in outs) in (["busy", "sealed"], ["kept", "sealed"])
    assert len(await rig.vault.releases(UID)) == 1
    assert rig.notes.kinds() == ["book_sealed"] and len(rig.audit.rows) == 1


async def test_a_privacy_hold_stops_this_release_and_the_next_release_seals() -> None:
    rig = Rig()
    first = rig.deploy(1)
    assert await rig.sealer.hold(UID) == first.id
    assert (await rig.sealer.ensure(UID)).state == "held"
    assert (await rig.new_sealer().ensure(UID)).state == "held"
    assert await rig.vault.releases(UID) == () and rig.notes.sent == []
    rig.deploy(2)
    assert (await rig.sealer.ensure(UID)).state == "sealed"


async def test_hold_without_a_book_holds_nothing() -> None:
    assert await Rig().sealer.hold(UID) is None


# ---- bounded runs for a request ---------------------------------------------------------------


class SlowVault(DocsBookVault):
    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.gate = asyncio.Event()
        self.seals = 0

    async def seal(self, uid: str, release: Release, files: Any, *, now: dt.datetime) -> Any:
        self.seals += 1
        await self.gate.wait()
        return await super().seal(uid, release, files, now=now)


async def test_a_request_waits_a_bounded_time_and_shares_the_run() -> None:
    rig = Rig()
    rig.deploy(1)
    slow = SlowVault(rig.docs, ring(), clock=rig.now)
    sealer = BookSealer(rig.source, slow, rig.docs, notifier=rig.notes, audit=None, clock=rig.now)
    first = await sealer.ensure_bounded(UID, within_s=0.05)
    second = await sealer.ensure_bounded(UID, within_s=0.05)
    assert first.state == second.state == "sealing" and slow.seals == 1
    slow.gate.set()
    done = await sealer.ensure_bounded(UID, within_s=5)
    assert done.state in ("sealed", "kept")
    for _ in range(50):
        if rig.notes.sent:
            break
        await asyncio.sleep(0.01)
    assert rig.notes.kinds() == ["book_sealed"] and slow.seals == 1


async def test_a_run_that_blows_up_is_a_failed_outcome_not_an_exception() -> None:
    rig = Rig()
    rig.deploy(1)

    def boom(kind: FileKind) -> bytes:
        raise RuntimeError("disk")

    rig.source.read = boom  # type: ignore[method-assign]
    assert (await rig.sealer.ensure_bounded(UID, within_s=5)).state == "failed"


# ---- the tick job ------------------------------------------------------------------------------


async def test_the_job_seals_for_the_primary_owner_only() -> None:
    rig = Rig()
    release = rig.deploy(1)
    job = BookSealJob(rig.sealer, UID)
    assert isinstance(job, TickJob) and job.name == "book_seal" and 0 < job.budget_s <= 60
    counts = await job.run([OTHER, "u_somebody"])
    assert counts == {"sealed": 1, "removed": 0, FAILED_COUNT: 0}
    assert [r.id for r in await rig.vault.releases(UID)] == [release.id]
    assert await rig.vault.releases(OTHER) == ()
    assert await job.run([]) == {"sealed": 0, "removed": 0, FAILED_COUNT: 0}


async def test_the_job_counts_a_failure() -> None:
    docs = FlakyDocs()
    rig = Rig(docs)
    rig.deploy(1)
    docs.fail_writes = 99
    assert (await BookSealJob(rig.sealer, UID).run([]))[FAILED_COUNT] == 1


async def test_two_runs_that_both_seal_still_tell_once() -> None:
    """A seal that outlives its lease: another instance seals too (the vault keeps one entry);
    the `told` claim keeps it to one notice."""
    rig = Rig()
    release = rig.deploy(1)
    a, b = rig.new_sealer(), rig.new_sealer()
    await a._say.tell(UID, release, 1)
    await b._say.tell(UID, release, 1)
    assert rig.notes.kinds() == ["book_sealed"]
