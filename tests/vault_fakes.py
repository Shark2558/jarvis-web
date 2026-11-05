# tests/vault_fakes.py -- shared helpers for the R2 vault tests (no network, MemoryDocs only)
from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Any

from jarvis.documents.extract import Extracted
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.service import VaultService
from jarvis.vault.store import VaultStore

UID = "u_owner00000000001"
OTHER = "u_other00000000002"
KEY = bytes(range(1, 33))
NOW = dt.datetime(2026, 11, 5, 9, 0, tzinfo=dt.UTC)
PDF = b"%PDF-1.4\n" + b"x" * 100
JPEG = b"\xff\xd8\xff\xe0" + b"j" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 100


def ring() -> Keyring:
    return Keyring(KEY)


def pdf_with_text(lines: list[str]) -> bytes:
    """A one-page text PDF (Helvetica) written by hand: no dependency."""

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    body = "BT /F1 11 Tf 40 800 Td 14 TL\n" + "\n".join(f"({esc(x)}) '" for x in lines) + "\nET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(body)} >>\nstream\n{body}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class Bin:
    """A stand-in for UndoBin.keep / discard."""

    def __init__(self, fail: bool = False) -> None:
        self.kept: list[tuple[str, str, str, dict[str, Any]]] = []
        self.fail = fail

    async def keep(
        self, uid: str, kind: str, title: str, snapshot: dict[str, Any], **_: Any
    ) -> Any:
        if self.fail:
            raise RuntimeError("no bin")
        self.kept.append((uid, kind, title, snapshot))
        return type("K", (), {"id": f"del_{len(self.kept):020x}"})()

    async def discard(self, uid: str, item_id: str) -> None:
        return None


def fixed_extract(text: str) -> Callable[[bytes, str], Any]:
    async def run(data: bytes, kind: str) -> Extracted:
        return Extracted(kind=kind, text=text)

    return run


def make(
    *,
    text: str | None = None,
    max_mb: int = 150,
    undo: Any = None,
    clock: Callable[[], dt.datetime] | None = None,
    docs: MemoryDocs | None = None,
) -> tuple[VaultService, MemoryDocs, VaultStore]:
    docs = docs or MemoryDocs()
    crypto = VaultCrypto(ring())
    store = VaultStore(docs, crypto)
    svc = VaultService(
        store,
        crypto,
        extract=fixed_extract(text) if text is not None else None,
        undo=undo if undo is not None else Bin(),
        max_total_mb=max_mb,
        clock=clock or (lambda: NOW),
    )
    return svc, docs, store


def scan(docs: MemoryDocs, needle: bytes | str) -> list[str]:
    """Paths of stored documents whose JSON holds the needle."""
    n = needle.decode("latin-1") if isinstance(needle, bytes) else needle
    return [p for p, d in docs._data.items() if n in json.dumps(d, default=str)]
