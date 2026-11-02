# tests/test_documents_worker.py — security review H1/H2: extraction runs in a child process per
# upload (python -I, no inherited environment, CPU and address-space limits set by the child before
# it reads a byte), killed on the wall-clock timeout or when the upload is cancelled, at most one
# at a time; whatever the child does, the parent maps it to a plain refusal.
from __future__ import annotations

import asyncio
import os
import zlib

import pytest
from doc_fakes import encrypt_pdf, make_docx, make_pdf

from jarvis.documents import isolation
from jarvis.documents.extract import TOO_COMPLEX, Limits, extract
from jarvis.documents.isolation import Sandbox, child_env, extract_isolated
from jarvis.documents.limits import DocumentRejected
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.storage.docs import MemoryDocs

FAST = Sandbox(cpu_s=10, timeout_s=20)  # the real memory cap (MEMORY_LIMIT_BYTES)


class Spawned:
    """Records the child processes a test starts."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.procs: list[asyncio.subprocess.Process] = []
        self.cmds: list[tuple[object, ...]] = []
        real = asyncio.create_subprocess_exec

        async def spy(*cmd, **kw):  # type: ignore[no-untyped-def]
            proc = await real(*cmd, **kw)
            self.procs.append(proc)
            self.cmds.append(cmd)
            self.env = kw.get("env")
            return proc

        monkeypatch.setattr(isolation.asyncio, "create_subprocess_exec", spy)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie still answers kill(0): look at its state
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


async def test_the_child_reads_exactly_what_the_inline_extractor_reads() -> None:
    data = make_pdf(["First page here", "Second page (two)"])
    assert await extract_isolated(data, "pdf", Limits(), FAST) == extract(data, "pdf")


async def test_refusals_cross_the_process_boundary_unchanged() -> None:
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(encrypt_pdf(make_pdf(["x"])), "pdf", Limits(), FAST)
    assert e.value.code == "encrypted" and e.value.status == 422 and "password" in str(e.value)


async def test_the_child_runs_isolated_without_the_apps_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("JARVIS_ANTHROPIC_API_KEY", "sk-not-for-the-child")
    spawned = Spawned(monkeypatch)
    await extract_isolated(b"hello", "txt", Limits(), FAST)
    (cmd,) = spawned.cmds
    assert cmd[1] == "-I"  # no PYTHON* variables, no user site, no script directory
    assert spawned.env is not None and not any("JARVIS" in k for k in spawned.env)
    assert child_env() == spawned.env


async def test_a_child_past_its_wall_clock_is_killed_and_called_too_slow(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    spawned = Spawned(monkeypatch)
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(b"hello", "txt", Limits(), Sandbox(timeout_s=0.01))
    assert e.value.code == "too_slow"
    assert not _alive(spawned.procs[0].pid)


async def test_a_child_out_of_memory_is_too_complex() -> None:
    page = b"BT /F1 8 Tf " + b"(ab) Tj 0 -1 Td " * 400_000 + b"ET"  # 6 MB of text operators
    data = _pdf_with_content(zlib.compress(page, 9))
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(data, "pdf", Limits(), Sandbox(memory_bytes=120 * 1024 * 1024))
    assert e.value.code in ("too_complex", "too_slow")


def test_the_child_memory_cap_leaves_room_for_the_server() -> None:
    # Cloud Run gives the instance 512 MiB, shared by the server and this child (integration)
    assert isolation.MEMORY_LIMIT_BYTES == 200 * 1024 * 1024
    assert Sandbox().memory_bytes == isolation.MEMORY_LIMIT_BYTES == FAST.memory_bytes


async def test_ordinary_files_extract_under_the_default_memory_cap() -> None:
    long = make_pdf([f"Page {i}: " + "budget line " * 120 for i in range(300)])
    pdf = await extract_isolated(long, "pdf", Limits(), Sandbox())
    assert pdf.truncated and len(pdf.text) == Limits().max_chars and (pdf.pages or 0) > 200
    docx = make_docx(["Para " * 200] * 400, [["Item", "Cost"]] * 50)
    assert len((await extract_isolated(docx, "docx", Limits(), Sandbox())).text) > 100_000


async def test_a_file_past_the_default_memory_cap_is_too_complex() -> None:
    page = b"BT /F1 8 Tf " + b"(ab) Tj 0 -1 Td " * 400_000 + b"ET"  # 6 MB of text operators
    data = _pdf_with_content(zlib.compress(page, 9))
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(data, "pdf", Limits(), Sandbox())
    assert e.value.code == "too_complex" and str(e.value) == TOO_COMPLEX


async def test_a_child_over_its_cpu_limit_is_stopped() -> None:
    page = b"BT /F1 8 Tf " + b"(ab) Tj 0 -1 Td " * 400_000 + b"ET"
    data = _pdf_with_content(zlib.compress(page, 9))
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(data, "pdf", Limits(budget_s=60), Sandbox(cpu_s=1, timeout_s=30))
    assert e.value.code in ("too_slow", "too_complex")


async def test_cancelling_an_upload_kills_its_child_and_frees_the_slot(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    spawned = Spawned(monkeypatch)
    svc = DocumentService(AttachmentStore(MemoryDocs()), sandbox=FAST)
    page = b"BT /F1 8 Tf " + b"(ab) Tj 0 -1 Td " * 400_000 + b"ET"
    task = asyncio.create_task(svc.upload("u1", "slow.pdf", _pdf_with_content(zlib.compress(page))))
    for _ in range(200):
        if spawned.procs:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.2)
    assert svc.running == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert svc.running == 0 and not _alive(spawned.procs[0].pid)
    assert (await svc.upload("u1", "next.txt", b"fine")).kind == "txt"  # the slot is free again


async def test_uploads_queue_for_the_one_slot_instead_of_failing() -> None:
    svc = DocumentService(AttachmentStore(MemoryDocs()), sandbox=FAST)
    refs = await asyncio.gather(*(svc.upload("u1", f"{i}.txt", b"note") for i in range(3)))
    assert [r.kind for r in refs] == ["txt"] * 3


async def test_a_full_queue_is_busy_after_its_wait() -> None:
    svc = DocumentService(AttachmentStore(MemoryDocs()), sandbox=FAST, queue_wait_s=0.05)
    await svc._slot.acquire()  # someone else's upload holds the only slot
    try:
        with pytest.raises(DocumentRejected) as e:
            await svc.upload("u1", "a.txt", b"x")
        assert e.value.code == "busy" and e.value.status == 503
    finally:
        svc._slot.release()


@pytest.mark.parametrize(
    "out",
    [b"", b"not json", b'{"ok": true}', b'{"ok": false, "code": "pwned", "detail": "x"}',
     b'{"ok": true, "text": 5}', b"[1, 2]"],
)  # fmt: skip
def test_anything_odd_from_the_child_is_a_plain_refusal(out: bytes) -> None:
    with pytest.raises(DocumentRejected) as e:
        isolation.parse_output(out, 0, kind="pdf", limits=Limits())
    assert e.value.code in ("unreadable", "too_complex")


def _pdf_with_content(content: bytes) -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R "
        b"/Resources << /Font << /F1 3 0 R >> >> >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content)
        + content
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)
