# tests/inbox_fakes.py -- a fake `VaultIntake` and the DigiLocker inbox wiring over the slice 12
# fake Drive (R2 workstream B). Evals load it by path too (evals/digilocker/run.py).
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from drive_fakes import FakeDrive, StaticTokens

from jarvis.documents.extract import Extracted
from jarvis.drive.client import DriveClient
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.storage.docs import MemoryDocs
from jarvis.vault.ports import IntakeResult, Source
from jarvis.vault_inbox.service import InboxService
from jarvis.vault_inbox.store import InboxStore

OWNER = "akash@example.com"
UID = "u_owner"
PDF_BYTES = b"%PDF-1.4 fake driving licence"


@dataclass
class FakeIntake:
    """Records what the vault was handed; dedupes by SHA-256 like the real one."""

    items: dict[str, str] = field(default_factory=dict)  # sha -> item id
    calls: list[tuple[str, int, str, str | None]] = field(default_factory=list)
    answer: IntakeResult | None = None  # force an answer (a full vault, ...)

    async def intake(
        self, uid: str, data: bytes, *, source: Source, drive_id: str | None = None
    ) -> IntakeResult:
        self.calls.append((uid, len(data), source, drive_id))
        if self.answer is not None:
            return self.answer
        sha = hashlib.sha256(data).hexdigest()
        if sha in self.items:
            return IntakeResult(status="duplicate", item_id=self.items[sha])
        item = f"v_{len(self.items) + 1:012x}"
        self.items[sha] = item
        return IntakeResult(status="added", item_id=item)


class Tokens(StaticTokens):
    async def email(self) -> str:
        return "jarvis-run@proj-123.iam.gserviceaccount.com"


def drive_tree() -> FakeDrive:
    d = FakeDrive()
    d.folder("inbox1", "JARVIS Vault inbox", shared_by=OWNER)
    d.folder("use1", "Registry", shared_by=OWNER)
    d.folder("sub1", "Minutes", "use1")
    d.folder("evil", "Free money", shared_by="stranger@evil.example")
    return d


async def text_extract(data: bytes, kind: str) -> Extracted:
    """A stand-in for the sandboxed extractor: the bytes are the text."""
    return Extracted(kind=kind, text=data.decode("utf-8", "ignore"))


@dataclass
class Rig:
    drive: FakeDrive
    docs: MemoryDocs
    svc: DriveService
    inbox: InboxService
    intake: FakeIntake
    store: InboxStore


def rig(d: FakeDrive | None = None, intake: FakeIntake | None = None) -> Rig:
    d = d or drive_tree()
    docs = MemoryDocs()
    client = DriveClient(Tokens(), http=d.client())
    store = InboxStore(docs)
    fake = intake or FakeIntake()
    inbox_ref: list[InboxService] = []

    async def inbox_id(uid: str) -> str | None:
        return await inbox_ref[0].folder_id(uid)

    svc = DriveService(client, RootsStore(docs), extract=text_extract, inbox=inbox_id)
    inbox = InboxService(svc, store, fake)
    inbox_ref.append(inbox)
    return Rig(d, docs, svc, inbox, fake, store)
