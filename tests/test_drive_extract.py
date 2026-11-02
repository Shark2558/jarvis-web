# tests/test_drive_extract.py — slice 12 D1 review F1 / F10: a Drive file is extracted through the
# app's ONE extraction slot (`DocumentService.extract`, injected by the app), so a chat upload and a
# Drive file never run two 200 MB children at once on the 512 MiB instance; and the extractor's
# refusals reach the owner in Drive's words (never slice 10's "attach it again").
from __future__ import annotations

import asyncio

import pytest
from doc_fakes import encrypt_pdf, make_pdf
from drive_fakes import PDF, SHEET, TXT, FakeDrive, StaticTokens

import jarvis.documents.service as docs_mod
from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.documents.extract import Extracted, Limits
from jarvis.documents.isolation import Sandbox
from jarvis.documents.limits import DocumentRejected
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.drive.client import DriveClient
from jarvis.drive.ports import DriveError
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.drive.tools import drive_tools
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

OWNER = "akash@example.com"
UID = "u_owner"


class Recorder:
    """Stands in for the sandboxed child process: records how many run at the same time."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.kinds: list[str] = []

    async def __call__(self, data: bytes, kind: str, limits: Limits, box: Sandbox) -> Extracted:
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.kinds.append(kind)
        try:
            await asyncio.sleep(0.02)
            return Extracted(kind=kind, text=data.decode())
        finally:
            self.active -= 1


def _drive() -> FakeDrive:
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER)
    for i in range(3):
        d.file(f"t{i}", f"note{i}.txt", "root1", f"drive words {i}", mime=TXT)
    return d


async def test_a_chat_upload_and_a_drive_file_never_extract_at_the_same_time(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = Recorder()
    monkeypatch.setattr(docs_mod, "extract_isolated", rec)
    d = _drive()
    svc = DriveService(DriveClient(StaticTokens(), http=d.client()), RootsStore(MemoryDocs()))
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore(), drive=svc)
    async with app.router.lifespan_context(app):
        await svc.set_use(UID, OWNER, "root1", True)
        uploads = [app.state.documents.upload(UID, f"c{i}.txt", b"chat words") for i in range(3)]
        reads = [svc.read(UID, f"t{i}") for i in range(3)]
        await asyncio.gather(*uploads, *reads)
    assert len(rec.kinds) == 6
    assert rec.peak == 1  # one child at a time across the whole app


async def test_the_app_builds_drive_on_the_documents_extractor(settings: Settings) -> None:
    app = create_app(
        settings.model_copy(update={"drive": True}),
        provider=MockProvider(),
        store=InMemorySessionStore(),
    )
    async with app.router.lifespan_context(app):
        assert app.state.drive is not None
        assert app.state.drive.extract == app.state.documents.extract


def test_the_drive_service_has_no_extractor_or_slot_of_its_own() -> None:
    import jarvis.drive.service as drive_mod

    assert not hasattr(drive_mod, "extract_isolated") and not hasattr(drive_mod, "Sandbox")
    svc = DriveService(
        DriveClient(StaticTokens(), http=_drive().client()), RootsStore(MemoryDocs())
    )
    assert not hasattr(svc, "_slot") and not hasattr(svc, "sandbox")


async def test_without_an_extractor_nothing_is_read() -> None:
    d = _drive()
    svc = DriveService(DriveClient(StaticTokens(), http=d.client()), RootsStore(MemoryDocs()))
    await svc.set_use(UID, OWNER, "root1", True)
    with pytest.raises(DriveError) as e:
        await svc.read(UID, "t0")
    assert "drive words" not in str(e.value)


# ---- the extractor's refusals, in Drive's words (F10) -------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "busy",
        "empty",
        "encrypted",
        "no_text",
        "unreadable",
        "too_complex",
        "too_slow",
        "unsupported",
        "too_large",
        "something_new",
    ],
)
async def test_extractor_refusals_are_said_in_drives_words(code: str) -> None:
    async def refuse(data: bytes, kind: str) -> Extracted:
        raise DocumentRejected(code, "Slice ten words: attach it again.")

    d = _drive()
    svc = DriveService(
        DriveClient(StaticTokens(), http=d.client()), RootsStore(MemoryDocs()), extract=refuse
    )
    await svc.set_use(UID, OWNER, "root1", True)
    with pytest.raises(DriveError) as e:
        await svc.read(UID, "t0")
    msg = str(e.value)
    assert msg and "attach" not in msg.lower() and "Slice ten" not in msg


async def test_a_password_protected_drive_pdf_is_not_told_to_attach_again() -> None:
    d = _drive()
    d.file("locked", "Locked.pdf", "root1", encrypt_pdf(make_pdf(["secret"])), mime=PDF)
    docs = DocumentService(AttachmentStore(MemoryDocs()), sandbox=Sandbox(timeout_s=30))
    svc = DriveService(
        DriveClient(StaticTokens(), http=d.client()), RootsStore(MemoryDocs()), extract=docs.extract
    )
    await svc.set_use(UID, OWNER, "root1", True)
    with pytest.raises(DriveError) as e:
        await svc.read(UID, "locked")
    assert "password" in str(e.value) and "attach" not in str(e.value).lower()


# ---- Sheets: only the first sheet (F10) ---------------------------------------------------------


async def test_a_sheet_says_only_its_first_sheet_was_read() -> None:
    d = _drive()
    d.file("sh", "Costs", "root1", "item,cost\nservers,2\n", mime=SHEET)
    docs = DocumentService(AttachmentStore(MemoryDocs()), sandbox=Sandbox(timeout_s=30))
    svc = DriveService(
        DriveClient(StaticTokens(), http=d.client()), RootsStore(MemoryDocs()), extract=docs.extract
    )
    await svc.set_use(UID, OWNER, "root1", True)
    out = await svc.read(UID, "sh")
    assert "first sheet" in out["note"]
    plain = await svc.read(UID, "t0")
    assert "first sheet" not in str(plain.get("note", ""))
    (read_tool,) = [t for t in drive_tools(svc) if t.name == "drive_read"]
    assert "first sheet" in read_tool.description
