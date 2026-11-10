# evals/r6_book/seal.py
"""R6 eval part `seal` (builder B): sealing, retention and download (D5-D7, D9), all on MemoryDocs
with the real keyring, vault, sealer and ticket store (the book source is the committed `_book`
fixture re-labelled per release; tests/book_seal_fakes.py).

Cases: two releases -> two sealed, two notices; a 4th -> 3 kept, the oldest's index entry and
chunks gone; a tampered chunk and a SHA-256 mismatch fail closed with ONE book_seal_failed; a
restart sends no notice; two racing sealers seal once; a book naming the owner's e-mail is
refused; the code downloads once with a 60 s ticket; nothing readable is stored.
Negative control: retention 4 (the sealer keeps four releases) -> the retention case fails.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import Awaitable, Callable
from typing import Any

from book_seal_fakes import (
    NOW,
    UID,
    FakeAudit,
    FakeNotifier,
    FakeSource,
    chunk_paths,
    fixture_book,
    make_release,
    ring,
    view,
)
from r6_common import Case

from jarvis.buildbook.model import KEEP
from jarvis.buildbook.owner import BookTickets
from jarvis.buildbook.ports import VaultTampered
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.seal_index import BookCrypto
from jarvis.buildbook.sealer import BookSealer
from jarvis.storage.docs import MemoryDocs
from jarvis.vault.unlock import TicketGone

PART = "seal"
BUILT = True
OWNER_EMAIL = "akash.owner2558@example.com"


class World:
    def __init__(self, keep: int) -> None:
        self.docs = MemoryDocs()
        self.clock = {"now": NOW}
        self.source = FakeSource()
        self.notes = FakeNotifier()
        self.audit = FakeAudit()
        self.keep = keep
        self.vault = DocsBookVault(self.docs, ring(), clock=lambda: self.clock["now"])
        self.sealer = self.process()

    def process(self) -> BookSealer:
        """A fresh server process on the same storage (a restart)."""
        return BookSealer(
            self.source, self.vault, self.docs, notifier=self.notes, audit=self.audit,
            owner_emails=(OWNER_EMAIL,), clock=lambda: self.clock["now"], keep=self.keep,
        )  # fmt: skip

    def deploy(self, n: int, **kw: Any) -> str:
        release, files = make_release(n, **kw)
        self.source.use(release, files)
        self.clock["now"] = NOW + dt.timedelta(hours=n)
        return release.id


Check = Callable[[World], Awaitable[list[str]]]


async def two_releases(w: World) -> list[str]:
    out = [(await w.sealer.ensure(UID)).state for _ in [w.deploy(1)]]
    out += [(await w.sealer.ensure(UID)).state for _ in [w.deploy(2)]]
    bad = [] if out == ["sealed", "sealed"] else [f"states {out}"]
    if w.notes.kinds() != ["book_sealed", "book_sealed"]:
        bad.append(f"notices {w.notes.kinds()}")
    if len(await w.vault.releases(UID)) != 2:
        bad.append("not two sealed")
    return bad


async def retention(w: World) -> list[str]:
    ids = []
    for n in (1, 2, 3, 4):
        ids.append(w.deploy(n))
        await w.sealer.ensure(UID)
    kept = [r.id for r in await w.vault.releases(UID)]
    bad = [] if kept == ids[:0:-1] else [f"kept {len(kept)} releases, want the newest {KEEP}"]
    if any(ids[0] in p for p in chunk_paths(w.docs)) or len(chunk_paths(w.docs)) != 2 * KEEP:
        bad.append(f"{len(chunk_paths(w.docs))} chunk documents left, want {2 * KEEP}")
    if not w.notes.sent[-1][2].endswith("3 releases kept."):
        bad.append("the notice does not say 3 releases kept")
    return bad


async def tampered_chunk(w: World) -> list[str]:
    rid = w.deploy(1)
    await w.sealer.ensure(UID)
    for p in chunk_paths(w.docs):
        w.docs._data[p]["blob"] = w.docs._data[p]["blob"][:-8] + "AAAAAAA="
    bad = []
    # what GET /v1/book/releases/{rid}/sections does on a failed read: this case proves the
    # once-only rule; that the route itself reports is tests/test_book_api.py's
    # test_a_tampered_sealed_book_stays_closed_and_the_owner_is_told_once
    for _ in range(2):
        try:
            await w.vault.read(UID, rid, "source")
            bad.append("a tampered chunk was read")
        except VaultTampered:
            await w.sealer.report_tampered(UID, rid, "R6")
    if w.notes.kinds() != ["book_sealed", "book_seal_failed"]:
        bad.append(f"notices {w.notes.kinds()}")
    return bad


async def sha_mismatch(w: World) -> list[str]:
    rid = w.deploy(1)
    w.source.files = {**w.source.files, "source": b"PK not this release"}
    bad = [] if (await w.sealer.ensure(UID)).state == "failed" else ["unmatched files sealed"]
    w.deploy(1)
    await w.sealer.ensure(UID)
    c = BookCrypto(ring())
    raw = json.loads(c.open_index(UID, w.docs._data[f"jarvis_book/{UID}"]["blob"]))
    raw["releases"][0]["files"][1]["sha256"] = "0" * 64
    w.docs._data[f"jarvis_book/{UID}"]["blob"] = c.seal_index(UID, json.dumps(raw).encode())
    try:
        await w.vault.read(UID, rid, raw["releases"][0]["files"][1]["kind"])
        bad.append("bytes that miss their SHA-256 were handed over")
    except VaultTampered:
        pass
    if w.notes.kinds() != ["book_seal_failed", "book_sealed"]:
        bad.append(f"notices {w.notes.kinds()}")
    return bad


async def restart(w: World) -> list[str]:
    w.deploy(1)
    await w.sealer.ensure(UID)
    states = [(await w.process().ensure(UID)).state for _ in range(3)]
    bad = [] if states == ["kept"] * 3 else [f"states {states}"]
    return bad + ([] if len(w.notes.sent) == 1 else [f"{len(w.notes.sent)} notices"])


async def racing(w: World) -> list[str]:
    w.deploy(1)
    outs = await asyncio.gather(*(w.process().ensure(UID) for _ in range(3)))
    sealed = [o.state for o in outs].count("sealed")
    bad = [] if sealed == 1 else [f"{sealed} seals"]
    if len(await w.vault.releases(UID)) != 1 or w.notes.kinds() != ["book_sealed"]:
        bad.append("not exactly one release and one notice")
    return bad + ([] if len(w.audit.rows) == 1 else [f"{len(w.audit.rows)} audit rows"])


async def owner_email(w: World) -> list[str]:
    book = fixture_book()
    text = "Built by " + OWNER_EMAIL.upper()
    w.deploy(
        1,
        book=book.model_copy(update={"digest": book.digest.model_copy(update={"overview": text})}),
    )
    states = [(await w.sealer.ensure(UID)).state for _ in range(2)]
    bad = [] if states == ["failed", "failed"] else [f"states {states}"]
    if await w.vault.releases(UID) or w.notes.kinds() != ["book_seal_failed"]:
        bad.append("a book naming the owner was sealed or told twice")
    return bad + ([] if OWNER_EMAIL not in str(w.notes.sent) else ["the address was echoed"])


async def download(w: World) -> list[str]:
    rid = w.deploy(1)
    await w.sealer.ensure(UID)
    tickets = BookTickets(w.docs, ring(), clock=lambda: w.clock["now"])
    session = view("owner", at=w.clock["now"])  # the live owner book session that asks (D9)
    t = await tickets.issue(UID, rid, session=session)
    taken = await tickets.take(UID, t.ticket)
    data = await w.vault.read(UID, str(taken.item), "source")
    bad = [] if data == w.source.files["source"] else ["the download is not the sealed code"]
    late = await tickets.issue(UID, rid, session=session)
    w.clock["now"] += dt.timedelta(seconds=61)
    for used in (t.ticket, late.ticket):
        try:
            await tickets.take(UID, used)
            bad.append("a used or expired ticket worked")
        except TicketGone:
            pass
    return bad


async def nothing_readable(w: World) -> list[str]:
    w.deploy(1)
    await w.sealer.ensure(UID)
    stored = json.dumps(w.docs._data)
    leaks = [s for s in ("JARVIS-source", "Eight layers", w.source.release.sha) if s in stored]  # type: ignore[union-attr]
    return [f"in clear: {leaks}"] if leaks else []


CASES: dict[str, Check] = {
    "two_releases_two_notices": two_releases,
    "a_fourth_keeps_three": retention,
    "tampered_chunk_fails_closed_told_once": tampered_chunk,
    "sha_mismatch_fails_closed": sha_mismatch,
    "restart_sends_no_notice": restart,
    "racing_sealers_seal_once": racing,
    "owner_email_refused": owner_email,
    "code_downloads_once": download,
    "nothing_readable_in_storage": nothing_readable,
}


async def _run(keep: int) -> list[Case]:
    results: list[Case] = []
    for name, check in CASES.items():
        try:
            failures = await check(World(keep))
        except Exception as exc:  # noqa: BLE001 - a crash is a failed case, never a pass
            failures = [f"raised {type(exc).__name__}"]
        results.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return results


async def cases() -> list[Case]:
    return await _run(KEEP)


async def control() -> dict[str, Any]:
    """Retention 4: the sealer keeps four releases; the suite must fail."""
    results = await _run(4)
    failed = [r["id"] for r in results if not r["passed"]]
    return {"name": f"{PART}: retention 4", "suite_failed": bool(failed), "failed_cases": failed}
