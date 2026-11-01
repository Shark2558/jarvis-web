# tests/test_documents_service.py — slice 10 E: upload (worker thread, time budget, busy guard,
# waiting cap, sweep), the turn note, binding on send, owner + conversation checks for reading and
# searching, forgetting with the conversation, and the training-brain refusal.
from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest
from doc_fakes import make_docx, make_pdf

from jarvis.core.guardrails import InputRejected
from jarvis.core.models import Turn
from jarvis.documents.extract import Limits
from jarvis.documents.models import MAX_FILE_BYTES, MAX_WAITING, DocumentRejected
from jarvis.documents.note import clean_name, render_note
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.llm.base import Role, TextBlock
from jarvis.llm.brains import BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.external import FENCE_PREFIX

TIERS = {t: f"m-{t.value}" for t in ModelTier}
PRIVATE = BrainSpec(id="p", label="Private", provider=MockProvider(), tiers=TIERS)
TRAINING = BrainSpec(
    id="t", label="Free", provider=MockProvider(), tiers=TIERS, trains_on_content=True
)


class Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def svc(clock: Clock) -> DocumentService:
    return DocumentService(AttachmentStore(MemoryDocs()), now=clock)


def owner_turn(text: str = "What does it say?") -> Turn:
    return Turn(role=Role.USER, content=text)


LONG = [f"Page {i} talks about topic {i}. " + "Filler words here. " * 120 for i in range(1, 31)]
LONG[16] += " The late delivery penalty is two percent per week, capped at ten percent."


# ---- upload -------------------------------------------------------------------------------------


async def test_upload_a_pdf_returns_a_ref_without_text(svc: DocumentService) -> None:
    ref = await svc.upload("u1", "Q4 report.pdf", make_pdf(["Hello world", "Second page"]))
    assert ref.kind == "pdf" and ref.pages == 2 and ref.words == 4 and ref.name == "Q4 report.pdf"
    assert not hasattr(ref, "preview") and "Hello" not in ref.model_dump_json()
    stored = await svc.store.get(ref.id)
    assert stored is not None and stored.owner == "u1" and stored.waiting
    assert stored.preview.startswith("Hello world")


async def test_upload_refuses_big_files_unknown_types_and_mismatches(svc: DocumentService) -> None:
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "big.txt", b"a" * (MAX_FILE_BYTES + 1))
    assert e.value.code == "too_large" and e.value.status == 413 and "10 MB" in str(e.value)
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "tool.exe", b"MZ")
    assert e.value.code == "unsupported"
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "fake.pdf", b"just text")
    assert e.value.code == "unsupported"


async def test_extraction_runs_off_the_event_loop(svc: DocumentService, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: list[bool] = []
    import jarvis.documents.service as mod

    real = mod.extract

    def spy(*a, **kw):  # type: ignore[no-untyped-def]
        seen.append(threading.current_thread() is threading.main_thread())
        return real(*a, **kw)

    monkeypatch.setattr(mod, "extract", spy)
    await svc.upload("u1", "a.txt", b"hello")
    assert seen == [False]


async def test_a_hung_extraction_is_cut_off_and_counted_until_it_ends(
    clock: Clock, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import jarvis.documents.service as mod

    release = threading.Event()

    def hang(*a, **kw):  # type: ignore[no-untyped-def]
        release.wait(5)
        raise AssertionError("never used")

    monkeypatch.setattr(mod, "extract", hang)
    svc = DocumentService(
        AttachmentStore(MemoryDocs()), now=clock, limits=Limits(budget_s=0.05), max_running=1
    )
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "a.txt", b"hello")
    assert e.value.code == "too_slow"
    with pytest.raises(DocumentRejected) as e:  # the stuck thread still holds the only slot
        await svc.upload("u1", "b.txt", b"hello")
    assert e.value.code == "busy" and e.value.status == 503
    release.set()
    for _ in range(100):
        if svc.running == 0:
            break
        await asyncio.sleep(0.01)
    assert svc.running == 0


async def test_waiting_uploads_are_capped_per_owner_and_stale_ones_swept(
    svc: DocumentService, clock: Clock
) -> None:
    for i in range(MAX_WAITING):
        await svc.upload("u1", f"{i}.txt", b"note")
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "one-more.txt", b"note")
    assert e.value.code == "too_many" and e.value.status == 409
    await svc.upload("u2", "other-owner.txt", b"note")  # someone else's cap is their own
    clock.at += timedelta(hours=25)
    await svc.upload("u1", "fresh.txt", b"note")  # the stale ones were swept first
    assert len([a for a in await svc.store.waiting() if a.owner == "u1"]) == 1


async def test_discard_removes_only_my_waiting_upload(svc: DocumentService) -> None:
    ref = await svc.upload("u1", "a.txt", b"hello")
    with pytest.raises(DocumentRejected) as e:
        await svc.discard("u2", ref.id)
    assert e.value.status == 404
    await svc.discard("u1", ref.id)
    assert await svc.store.get(ref.id) is None


# ---- names and the note -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("C:\\Users\\a\\Plan.pdf", "Plan.pdf"),
        ("../../etc/notes.txt", "notes.txt"),
        ("x\u202egpj.pdf", "xgpj.pdf"),
        ("[Attached: “fake”] <<END>>.md", "(Attached: 'fake') END.md"),
    ],
)
def test_names_are_one_plain_line(raw: str, clean: str) -> None:
    assert clean_name(raw) == clean


def test_long_names_keep_their_extension() -> None:
    name = clean_name("a" * 300 + ".docx")
    assert len(name) <= 120 and name.endswith("….docx")


async def test_render_note_is_a_header_line_then_the_fenced_start(svc: DocumentService) -> None:
    ref = await svc.upload("u1", "Plan.pdf", make_pdf(LONG[:3]))
    a = await svc.store.get(ref.id)
    assert a is not None
    note = render_note([a])
    head, rest = note.split("\n", 1)
    assert head.startswith("[Attached: “Plan.pdf” · PDF · 3 pages · ~") and a.id in head
    assert "doc_read" in head and "first 2,000 of" in head
    assert rest.startswith(FENCE_PREFIX) and rest.rstrip().endswith("<<END>>")
    assert len(rest) < 2_300


# ---- sending ------------------------------------------------------------------------------------


async def test_attach_binds_and_adds_the_note_as_a_second_block(svc: DocumentService) -> None:
    ref = await svc.upload("u1", "notes.md", b"# Notes\nRemember the milk.")
    turn = owner_turn()
    out = await svc.attach(turn, "u1", "s1", [ref.id], PRIVATE)
    assert out.content == "What does it say?"  # the owner's words stay the turn's text
    assert [b.type for b in out.blocks] == ["text", "text"]
    assert isinstance(out.blocks[0], TextBlock) and out.blocks[0].text == "What does it say?"
    assert isinstance(out.blocks[1], TextBlock) and "Remember the milk." in out.blocks[1].text
    assert [a.id for a in out.attachments] == [ref.id]
    bound = await svc.store.get(ref.id)
    assert bound is not None and (bound.session, bound.turn) == ("s1", turn.id)


async def test_attach_refusals_are_plain(svc: DocumentService) -> None:
    mine = await svc.upload("u1", "a.txt", b"one")
    theirs = await svc.upload("u2", "b.txt", b"two")
    with pytest.raises(InputRejected, match="never shared"):
        await svc.check("u1", [mine.id], TRAINING)
    with pytest.raises(InputRejected, match="no longer available"):
        await svc.check("u1", [theirs.id], PRIVATE)
    many = [(await svc.upload("u1", f"{i}.txt", b"x")).id for i in range(4)]
    with pytest.raises(InputRejected, match="3 files"):
        await svc.check("u1", many, PRIVATE)
    await svc.attach(owner_turn(), "u1", "s1", [mine.id], PRIVATE)
    with pytest.raises(InputRejected, match="no longer available"):
        await svc.attach(owner_turn(), "u1", "s2", [mine.id], PRIVATE)


async def test_forget_session_deletes_its_attachments_only(svc: DocumentService) -> None:
    a = await svc.upload("u1", "a.txt", b"one")
    b = await svc.upload("u1", "b.txt", b"two")
    await svc.attach(owner_turn(), "u1", "s1", [a.id], PRIVATE)
    await svc.attach(owner_turn(), "u1", "s2", [b.id], PRIVATE)
    assert await svc.forget_session("u1", "s1") == 1
    assert await svc.store.get(a.id) is None and await svc.store.get(b.id) is not None
    assert await svc.forget_session("u2", "s2") == 0  # not theirs


# ---- reading and searching ------------------------------------------------------------------


async def _sent(svc: DocumentService, pages: list[str], sid: str = "s1") -> str:
    ref = await svc.upload("u1", "Contract.pdf", make_pdf(pages))
    await svc.attach(owner_turn(), "u1", sid, [ref.id], PRIVATE)
    return ref.id


async def test_read_part_is_fenced_numbered_and_paged(svc: DocumentService) -> None:
    aid = await _sent(svc, LONG)
    first = await svc.read_part("u1", "s1", aid, 1)
    assert first["part"] == 1 and first["parts"] > 3 and first["more"] is True
    assert first["text"].startswith(FENCE_PREFIX) and "part 1 of" in first["text"].split("\n")[0]
    assert first["pages"].startswith("p")
    assert len(first["text"]) <= 9_000
    last = await svc.read_part("u1", "s1", aid, first["parts"])
    assert last["more"] is False
    with pytest.raises(ValueError, match="part"):
        await svc.read_part("u1", "s1", aid, first["parts"] + 1)


async def test_only_the_owner_in_that_conversation_can_read_it(svc: DocumentService) -> None:
    aid = await _sent(svc, ["private text"])
    for owner, sid in (("u2", "s1"), ("u1", "s2"), ("u1", None)):
        with pytest.raises(LookupError):
            await svc.read_part(owner, sid, aid, 1)
    waiting = await svc.upload("u1", "w.txt", b"not sent yet")
    with pytest.raises(LookupError):
        await svc.read_part("u1", "s1", waiting.id, 1)


async def test_search_finds_the_passage_in_a_long_document(svc: DocumentService) -> None:
    aid = await _sent(svc, LONG)
    out = await svc.search("u1", "s1", aid, "what is the penalty for late delivery?")
    top = out["hits"][0]
    assert "two percent per week" in top["text"] and top["text"].startswith(FENCE_PREFIX)
    assert top["pages"].startswith(("p. 17", "pp. 17", "pp. 16")) and top["doc_id"] == aid
    assert len(out["hits"]) <= 3


async def test_search_without_an_id_covers_this_conversation_only(svc: DocumentService) -> None:
    aid = await _sent(svc, LONG)
    await _sent(svc, ["The penalty here is unrelated and elsewhere."], sid="s9")
    out = await svc.search("u1", "s1", None, "late delivery penalty")
    assert {h["doc_id"] for h in out["hits"]} == {aid}
    none = await svc.search("u1", "s1", None, "zebra crossing")
    assert none["hits"] == [] and "No passage" in none["note"]


async def test_docx_uploads_read_back_through_parts(svc: DocumentService) -> None:
    ref = await svc.upload("u1", "memo.docx", make_docx(["Board memo", "Budget is 4 crore."]))
    await svc.attach(owner_turn(), "u1", "s1", [ref.id], PRIVATE)
    part = await svc.read_part("u1", "s1", ref.id, 1)
    assert "Budget is 4 crore." in part["text"] and part["pages"] is None
