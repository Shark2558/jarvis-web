# evals/digilocker/run.py
"""R2 D9 eval -- the DigiLocker inbox: a Drive folder JARVIS copies new documents out of.

    python evals/digilocker/run.py --mock

15 cases over the real Drive service, parents guard, roots store and inbox service, an in-memory
Drive (evals/drive/fake_drive.py) and a fake vault intake (the vault itself is another workstream):
who may be picked (the owner's own folder only; not a Use folder, not inside one; a Use folder
cannot become the inbox), what is imported (once, again when the file changed, three a run, big and
unsupported ones skipped with words, a full vault stops and retries), and the guarantee that no
Drive tool reads the inbox (read, search, list, a shortcut, an unreadable record = nothing read)
while the slice 12 rules (owner-shared Use folders only, read-only) still hold.
Negative controls (each must make the suite FAIL): the guard's inbox deny off; the ownership test
saying yes to everything.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "drive"))
from fake_drive import DOCX, PDF, FakeDrive, StaticTokens  # noqa: E402
from r1d_common import finish  # noqa: E402

from jarvis.documents.extract import Extracted  # noqa: E402
from jarvis.drive.client import DriveClient  # noqa: E402
from jarvis.drive.ports import DriveError, NotInRoots  # noqa: E402
from jarvis.drive.roots import RootsStore  # noqa: E402
from jarvis.drive.service import DriveRejected, DriveService  # noqa: E402
from jarvis.logging import configure_logging, new_trace_id  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.vault.ports import IntakeResult, Source  # noqa: E402
from jarvis.vault_inbox.service import InboxService  # noqa: E402
from jarvis.vault_inbox.store import Inbox, InboxStore  # noqa: E402

OWNER = "akash@example.com"
UID = "u_owner"
PDF_BYTES = b"%PDF-1.4 fake driving licence"
Case = Callable[[], Awaitable[list[str]]]
CASES: list[tuple[str, Case]] = []


def case(name: str) -> Callable[[Case], Case]:
    def deco(fn: Case) -> Case:
        CASES.append((name, fn))
        return fn

    return deco


def check(cond: bool, msg: str, fails: list[str]) -> None:
    if not cond:
        fails.append(msg)


class Tokens(StaticTokens):
    async def email(self) -> str:
        return "jarvis-run@proj-123.iam.gserviceaccount.com"


@dataclass
class FakeIntake:
    items: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, int, str, str | None]] = field(default_factory=list)
    answer: IntakeResult | None = None

    async def intake(
        self, uid: str, data: bytes, *, source: Source, drive_id: str | None = None
    ) -> IntakeResult:
        self.calls.append((uid, len(data), source, drive_id))
        if self.answer is not None:
            return self.answer
        sha = hashlib.sha256(data).hexdigest()
        if sha in self.items:
            return IntakeResult(status="duplicate", item_id=self.items[sha])
        self.items[sha] = f"v_{len(self.items) + 1:012x}"
        return IntakeResult(status="added", item_id=self.items[sha])


async def _extract(data: bytes, kind: str) -> Extracted:
    return Extracted(kind=kind, text=data.decode("utf-8", "ignore"))


@dataclass
class Rig:
    drive: FakeDrive
    docs: MemoryDocs
    svc: DriveService
    inbox: InboxService
    intake: FakeIntake
    store: InboxStore


def rig() -> Rig:
    d = FakeDrive()
    d.folder("inbox1", "JARVIS Vault inbox", shared_by=OWNER)
    d.folder("use1", "Registry", shared_by=OWNER)
    d.folder("sub1", "Minutes", "use1")
    d.folder("evil", "Free money", shared_by="stranger@evil.example")
    docs = MemoryDocs()
    store = InboxStore(docs)
    intake = FakeIntake()
    ref: list[InboxService] = []

    async def inbox_id(uid: str) -> str | None:
        return await ref[0].folder_id(uid)

    svc = DriveService(
        DriveClient(Tokens(), http=d.client()), RootsStore(docs), extract=_extract, inbox=inbox_id
    )
    inbox = InboxService(svc, store, intake)
    ref.append(inbox)
    return Rig(d, docs, svc, inbox, intake, store)


async def picked() -> Rig:
    r = rig()
    await r.inbox.pick(UID, OWNER, "inbox1")
    return r


async def refused(coro: Awaitable[Any], exc: type[Exception]) -> bool:
    try:
        await coro
    except exc:
        return True
    return False


async def with_pan(r: Rig) -> None:
    """The hard layout: the inbox sits INSIDE a Use folder (a root above it would allow it), so only
    the deny can keep Drive tools out. (pick() refuses this layout; the record is forced.)"""
    r.drive.folder("inbox2", "Inbox in a Use folder", "use1")
    r.drive.file("pan", "PAN card", "inbox2", "ABCDE1234F permanent account number", mime=PDF)
    r.drive.file("note", "Minutes", "sub1", "Budget is four crore.")
    await r.svc.set_use(UID, OWNER, "use1", True)
    await r.store.change(UID, lambda _o: Inbox("inbox2", "x", OWNER, datetime.now(UTC)))
    r.svc.guard.forget()


@case("pick_the_owners_own_folder")
async def _pick() -> list[str]:
    r = await picked()
    f: list[str] = []
    check((await r.inbox.view(UID, OWNER))["folder"]["id"] == "inbox1", "not picked", f)
    return f


@case("a_strangers_folder_is_refused")
async def _stranger() -> list[str]:
    r = rig()
    f: list[str] = []
    check(await refused(r.inbox.pick(UID, OWNER, "evil"), DriveRejected), "stranger's accepted", f)
    return f


@case("a_use_folder_is_refused")
async def _use() -> list[str]:
    r = rig()
    await r.svc.set_use(UID, OWNER, "use1", True)
    f: list[str] = []
    check(await refused(r.inbox.pick(UID, OWNER, "use1"), DriveRejected), "Use folder", f)
    return f


@case("a_folder_inside_a_use_folder_is_refused")
async def _inside() -> list[str]:
    r = rig()
    await r.svc.set_use(UID, OWNER, "use1", True)
    f: list[str] = []
    check(await refused(r.inbox.pick(UID, OWNER, "sub1"), DriveRejected), "inside Use", f)
    return f


@case("the_inbox_cannot_become_a_use_folder")
async def _tick() -> list[str]:
    r = await picked()
    f: list[str] = []
    check(await refused(r.svc.set_use(UID, OWNER, "inbox1", True), DriveRejected), "ticked", f)
    return f


@case("a_new_pdf_is_imported_once")
async def _once() -> list[str]:
    r = await picked()
    r.drive.file("p1", "Licence.pdf", "inbox1", PDF_BYTES, mime=PDF)
    a, b = await r.inbox.check(UID), await r.inbox.check(UID)
    f: list[str] = []
    check(a.imported == 1 and b.imported == 0, f"{a.imported}/{b.imported}", f)
    check(r.intake.calls[0][2:] == ("digilocker", "p1"), f"{r.intake.calls}", f)
    return f


@case("a_changed_file_is_imported_again")
async def _changed() -> list[str]:
    r = await picked()
    item = r.drive.file("p1", "scan.pdf", "inbox1", PDF_BYTES, mime=PDF)
    await r.inbox.check(UID)
    item.content = PDF_BYTES + b" renewed"
    f: list[str] = []
    check((await r.inbox.check(UID)).imported == 1, "not re-imported", f)
    return f


@case("three_a_run_and_the_rest_next_time")
async def _three() -> list[str]:
    r = await picked()
    for i in range(5):
        r.drive.file(f"p{i}", f"{i}.pdf", "inbox1", PDF_BYTES + bytes([i]), mime=PDF)
    a, b = await r.inbox.check(UID), await r.inbox.check(UID)
    f: list[str] = []
    check((a.imported, a.more, b.imported) == (3, True, 2), f"{a} {b}", f)
    return f


@case("big_and_unsupported_files_are_skipped_not_downloaded")
async def _skipped() -> list[str]:
    r = await picked()
    r.drive.file("big", "big.pdf", "inbox1", b"x", mime=PDF, size=11 * 1024 * 1024)
    r.drive.file("doc", "letter.docx", "inbox1", b"x", mime=DOCX)
    res = await r.inbox.check(UID)
    f: list[str] = []
    check(res.imported == 0 and res.skipped == 2 and not r.intake.calls, f"{res}", f)
    return f


@case("a_full_vault_stops_and_retries_later")
async def _full() -> list[str]:
    r = await picked()
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    r.intake.answer = IntakeResult(
        status="skipped", code="vault_full", message="The vault is full."
    )
    first = await r.inbox.check(UID)
    r.intake.answer = None
    f: list[str] = []
    check(first.imported == 0 and first.stopped == "The vault is full.", f"{first}", f)
    check((await r.inbox.check(UID)).imported == 1, "not retried", f)
    return f


@case("drive_read_and_list_of_the_inbox_are_refused")
async def _read() -> list[str]:
    r = await picked()
    await with_pan(r)
    f: list[str] = []
    check(await refused(r.svc.read(UID, "pan"), NotInRoots), "read the inbox file", f)
    check(await refused(r.svc.list_folder(UID, "inbox2"), NotInRoots), "listed the inbox", f)
    return f


@case("drive_search_never_shows_an_inbox_file")
async def _search() -> list[str]:
    r = await picked()
    await with_pan(r)
    found = await r.svc.search(UID, "ABCDE1234F")
    f: list[str] = []
    check(found["results"] == [] and "permanent account" not in str(found), f"{found}", f)
    return f


@case("a_shortcut_to_an_inbox_file_is_refused")
async def _shortcut() -> list[str]:
    r = await picked()
    await with_pan(r)
    r.drive.shortcut("sc", "link", "sub1", "pan")
    f: list[str] = []
    check(await refused(r.svc.read(UID, "sc"), NotInRoots), "followed the shortcut", f)
    return f


@case("an_unreadable_inbox_record_reads_nothing")
async def _closed() -> list[str]:
    r = await picked()
    await with_pan(r)
    r.docs._data[f"jarvis_vault_inbox/{UID}"]["folder_id"] = "bad id!"  # type: ignore[attr-defined]
    f: list[str] = []
    check(await refused(r.svc.read(UID, "note"), DriveError), "read with the record unreadable", f)
    return f


@case("the_slice_12_rules_still_hold")
async def _slice12() -> list[str]:
    r = await picked()
    await with_pan(r)
    r.drive.folder("other", "Personal", shared_by=OWNER)
    r.drive.file("diary", "Diary", "other", "private words")
    r.drive.folder("evil2", "Evil", shared_by="stranger@evil.example")
    f: list[str] = []
    check((await r.svc.read(UID, "note"))["file"] == "note", "a Use folder no longer reads", f)
    check(await refused(r.svc.read(UID, "diary"), NotInRoots), "read outside the roots", f)
    check(await refused(r.svc.set_use(UID, OWNER, "evil2", True), DriveRejected), "stranger Use", f)
    check(all(q.method == "GET" for q in r.drive.requests), "Drive was written to", f)
    return f


async def run_all() -> list[dict[str, Any]]:
    out = []
    for name, fn in CASES:
        new_trace_id()
        try:
            fails = await fn()
        except Exception as exc:  # noqa: BLE001 -- a crashing case is a failed case
            fails = [f"crashed: {type(exc).__name__}: {exc}"]
        out.append({"id": name, "passed": not fails, "failures": fails})
    return out


@contextmanager
def deny_off() -> Any:
    saved = DriveService._deny

    async def nothing(self: DriveService, uid: str) -> tuple[str, ...]:
        return ()

    DriveService._deny = nothing  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        DriveService._deny = saved  # type: ignore[method-assign]


@contextmanager
def owner_check_off() -> Any:
    from jarvis.drive import live as roots

    saved = roots.RootChecks.__init__

    def init(self: Any, *a: Any, **kw: Any) -> None:
        saved(self, *a, **kw)
        self.owns = lambda f, email: True

    roots.RootChecks.__init__ = init  # type: ignore[method-assign]
    try:
        yield
    finally:
        roots.RootChecks.__init__ = saved  # type: ignore[method-assign]


async def controls() -> dict[str, Any]:
    with deny_off():
        no_deny = await run_all()
    with owner_check_off():
        no_owner = await run_all()
    failed = {
        "guard_deny_off": [r["id"] for r in no_deny if not r["passed"]],
        "ownership_says_yes": [r["id"] for r in no_owner if not r["passed"]],
    }
    return {"suite_failed": all(failed.values()), "failed_cases": failed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.parse_args()
    configure_logging()
    results = asyncio.run(run_all())
    return finish(HERE, "digilocker", results, asyncio.run(controls()))


if __name__ == "__main__":
    sys.exit(main())
