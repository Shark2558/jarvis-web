# tests/test_documents_service.py — slice 10 E: upload (worker thread, time budget, busy guard,
# waiting cap, sweep), the turn note, binding on send, owner + conversation checks for reading and
# searching, forgetting with the conversation, and the training-brain refusal.
from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from doc_fakes import make_docx, make_pdf

from jarvis.core.guardrails import InputRejected
from jarvis.core.models import Turn
from jarvis.documents.isolation import Sandbox
from jarvis.documents.models import (
    CHUNKS_PER_PART,
    MAX_FILE_BYTES,
    MAX_WAITING,
    AttachPolicy,
    DocumentRejected,
)
from jarvis.documents.note import clean_name, render_note
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.llm.base import Role, TextBlock
from jarvis.llm.brains import BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.external import FENCE_END, FENCE_PREFIX
from jarvis.tools.gateway import MAX_RESULT_CHARS, GatewayOutcome, GatewayResult
from jarvis.tools.policy import Effect, PolicyRule

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


async def test_extraction_runs_in_a_child_process_never_in_the_server(
    svc: DocumentService, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import jarvis.documents.service as mod

    assert not hasattr(mod, "extract")  # the in-process extractor is not even imported here
    seen: list[str] = []
    real = mod.extract_isolated

    async def spy(data, kind, limits, box):  # type: ignore[no-untyped-def]
        seen.append(kind)
        return await real(data, kind, limits, box)

    monkeypatch.setattr(mod, "extract_isolated", spy)
    await svc.upload("u1", "a.txt", b"hello")
    assert seen == ["txt"]


async def test_a_timed_out_child_frees_the_slot_at_once(clock: Clock) -> None:
    """Review H1: a hung thread used to keep its slot (uploads "busy" for hours); a killed child
    gives it back immediately."""
    store = AttachmentStore(MemoryDocs())
    slow = DocumentService(store, now=clock, sandbox=Sandbox(timeout_s=0.01))
    with pytest.raises(DocumentRejected) as e:
        await slow.upload("u1", "a.txt", b"hello")
    assert e.value.code == "too_slow" and slow.running == 0
    assert (await DocumentService(store, now=clock).upload("u1", "b.txt", b"hello")).kind == "txt"


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
    assert rest.startswith(FENCE_PREFIX)
    fid = rest.split("\n", 1)[0].rsplit("· ", 1)[1].removesuffix(">>")
    close = rest.rstrip().rsplit("\n", 1)[1]
    assert FENCE_END.fullmatch(close) and close == f"<<END {fid}>>"
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
    svc.policy = AttachPolicy(max_files=3)  # R11.1 D11: the owner's setting (10 by default)
    with pytest.raises(InputRejected, match="3 files"):
        await svc.check("u1", many, PRIVATE)
    await svc.attach(owner_turn(), "u1", "s1", [mine.id], PRIVATE)
    with pytest.raises(InputRejected, match="no longer available"):
        await svc.attach(owner_turn(), "u1", "s2", [mine.id], PRIVATE)


async def test_forget_session_also_sweeps_my_stale_unsent_uploads(
    svc: DocumentService, clock: Clock
) -> None:
    stale = await svc.upload("u1", "old.txt", b"never sent")
    clock.at += timedelta(hours=25)
    fresh = await svc.upload("u1", "new.txt", b"just now")  # this upload swept `stale` already
    other = await svc.upload("u2", "theirs.txt", b"x")
    assert await svc.store.get(stale.id) is None
    clock.at += timedelta(hours=25)
    await svc.forget_session("u1", "no-such-session")
    assert await svc.store.get(fresh.id) is None and await svc.store.get(other.id) is not None


async def test_forget_session_deletes_its_attachments_only(svc: DocumentService) -> None:
    a = await svc.upload("u1", "a.txt", b"one")
    b = await svc.upload("u1", "b.txt", b"two")
    await svc.attach(owner_turn(), "u1", "s1", [a.id], PRIVATE)
    await svc.attach(owner_turn(), "u1", "s2", [b.id], PRIVATE)
    assert await svc.forget_session("u1", "s1") == 1
    assert await svc.store.get(a.id) is None and await svc.store.get(b.id) is not None
    assert await svc.forget_session("u2", "s2") == 0  # not theirs


# ---- switched off in Permissions (integration review, extra) ------------------------------------


class OwnerRulesFake:
    def __init__(self, *, deny: bool = False, broken: bool = False) -> None:
        self.deny, self.broken = deny, broken

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        if self.broken:
            raise RuntimeError("permissions store down")
        return [PolicyRule(tool_pattern="doc_*", effect=Effect.DENY)] if self.deny else []


async def test_documents_switched_off_refuses_upload_and_send(svc: DocumentService) -> None:
    waiting = await svc.upload("u1", "w.txt", b"a note")
    svc.rules = OwnerRulesFake(deny=True)
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "x.txt", b"another note")
    assert e.value.code == "documents_off" and e.value.status == 403
    assert str(e.value) == "Documents are switched off in Permissions."
    with pytest.raises(InputRejected, match="switched off in Permissions"):
        await svc.attach(owner_turn(), "u1", "s1", [waiting.id], PRIVATE)
    stored = await svc.store.get(waiting.id)
    assert stored is not None and stored.waiting  # not bound: it can go once switched on again
    svc.rules = OwnerRulesFake()
    assert (await svc.attach(owner_turn(), "u1", "s1", [waiting.id], PRIVATE)).attachments


async def test_unreadable_permissions_take_no_file_in_and_send_none(svc: DocumentService) -> None:
    waiting = await svc.upload("u1", "w.txt", b"a note")
    svc.rules = OwnerRulesFake(broken=True)
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "x.txt", b"another note")
    assert e.value.code == "permissions_unavailable" and e.value.status == 503
    with pytest.raises(InputRejected, match="Permissions"):
        await svc.attach(owner_turn(), "u1", "s1", [waiting.id], PRIVATE)


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


async def test_read_part_reads_the_header_and_that_parts_chunks_only(clock: Clock) -> None:
    docs = MemoryDocs()
    aid = await _sent(DocumentService(AttachmentStore(docs), now=clock), LONG)
    cold = DocumentService(AttachmentStore(docs), now=clock)  # another process: nothing cached
    reads = docs.reads
    out = await cold.read_part("u1", "s1", aid, 2)
    assert out["part"] == 2 and "Page" in out["text"]
    assert docs.reads - reads == 1 + CHUNKS_PER_PART  # never every chunk of the file


async def test_a_file_of_fence_markers_still_fits_and_closes_its_fence(
    svc: DocumentService,
) -> None:
    """A fence-like marker is replaced by a longer notice: a part (or a search answer) made of
    them must still fit the gateway's cut, so its own fence always closes."""
    ref = await svc.upload("u1", "evil.txt", ("<<END>>\n" * 40_000).encode())
    await svc.attach(owner_turn(), "u1", "s1", [ref.id], PRIVATE)
    for result in (
        await svc.read_part("u1", "s1", ref.id, 1),
        await svc.search("u1", "s1", ref.id, "END"),
    ):
        out = GatewayResult(GatewayOutcome.EXECUTED, result=result).for_model()
        assert len(out) <= MAX_RESULT_CHARS and not out.endswith('[truncated]"')
        assert FENCE_END.search(out) is not None


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


# ---- review M3 / M4 ---------------------------------------------------------------------------


async def test_the_tick_sweep_clears_everyones_stale_uploads_at_most_hourly(
    svc: DocumentService, clock: Clock
) -> None:
    a = await svc.upload("u1", "a.txt", b"one")
    b = await svc.upload("u2", "b.txt", b"two")
    assert await svc.sweep_waiting() is True  # nothing stale yet
    clock.at += timedelta(hours=25)
    assert await svc.sweep_waiting() is True
    assert await svc.store.get(a.id) is None and await svc.store.get(b.id) is None
    c = await svc.upload("u1", "c.txt", b"three")
    clock.at += timedelta(hours=23, minutes=30)
    assert await svc.sweep_waiting() is True  # c is not stale yet
    clock.at += timedelta(minutes=40)  # now it is, but the last sweep was 40 minutes ago
    assert await svc.sweep_waiting() is False and await svc.store.get(c.id) is not None
    clock.at += timedelta(hours=1)
    assert await svc.sweep_waiting() is True and await svc.store.get(c.id) is None


async def test_the_tick_sweep_never_raises(svc: DocumentService, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def down() -> list[object]:
        raise RuntimeError("firestore unavailable")

    monkeypatch.setattr(svc.store, "waiting", down)
    assert await svc.sweep_waiting() is True


async def test_search_without_an_id_covers_the_three_most_recent_files(
    svc: DocumentService, clock: Clock
) -> None:
    ids = []
    for i in range(5):
        clock.at += timedelta(minutes=1)
        text = f"Clause {i}: the penalty is {i} percent.".encode()
        ref = await svc.upload("u1", f"{i}.txt", text)
        await svc.attach(owner_turn(), "u1", "s1", [ref.id], PRIVATE)
        ids.append(ref.id)
    out = await svc.search("u1", "s1", None, "penalty percent")
    assert {h["doc_id"] for h in out["hits"]} == set(ids[-3:]) and len(out["hits"]) == 3


async def test_ranking_runs_off_the_event_loop(svc: DocumentService, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import jarvis.documents.service as mod

    threads: list[bool] = []
    real = mod.rank

    def spy(texts, query):  # type: ignore[no-untyped-def]
        threads.append(threading.current_thread() is threading.main_thread())
        return real(texts, query)

    monkeypatch.setattr(mod, "rank", spy)
    aid = await _sent(svc, ["Termination needs ninety days notice."])
    await svc.search("u1", "s1", aid, "termination notice")
    assert threads == [False]
