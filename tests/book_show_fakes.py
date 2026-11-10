# tests/book_show_fakes.py -- fakes for R6 builder C's tests and evals (sessions, lock, talk,
# service, show routes). Imported bare (`from book_show_fakes import ...`); evals/r6_book puts
# tests/ on sys.path. Nothing here is used by the app.
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jarvis.buildbook.model import Book, FileKind, Release, load_book
from jarvis.buildbook.ports import BookUnavailable
from jarvis.keyring import Keyring
from jarvis.llm.base import ChatMessage, Completion, ToolSpec, Usage
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import Delete, MemoryDocs, Op

BOOK_DIR = Path(__file__).resolve().parent / "fixtures" / "book" / "_book"
T0 = datetime(2026, 11, 10, 8, 32, tzinfo=UTC)  # 14:02 in Asia/Kolkata
UID = "u_0123456789abcdef"
OTHER_UID = "u_fedcba9876543210"
OWNER_EMAIL = "akash.owner@example.com"


def keyring() -> Keyring:
    return Keyring(bytes(range(1, 33)))


class Clock:
    """An aware clock the tests move by hand."""

    def __init__(self, at: datetime = T0) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kw: float) -> datetime:
        self.at = self.at + timedelta(**kw)
        return self.at


class FixtureSource:
    """ports.BookSource over tests/fixtures/book/_book (A's release.py does this for real)."""

    def __init__(self, folder: Path = BOOK_DIR, *, present: bool = True) -> None:
        self.folder, self.present = folder, present
        self._book: Book | None = None

    def current(self) -> Release | None:
        if not self.present:
            return None
        return Release.model_validate_json((self.folder / "release.json").read_bytes())

    def read(self, kind: FileKind) -> bytes:
        rel = self.current()
        if rel is None or not rel.ok:
            raise BookUnavailable("This server has no build book.")
        data = (self.folder / ("book.json" if kind == "book" else "source.zip")).read_bytes()
        want = rel.book_sha256 if kind == "book" else rel.source_sha256
        if hashlib.sha256(data).hexdigest() != want:
            raise BookUnavailable("This server has no build book.")
        return data

    def book(self) -> Book:
        if self._book is None:
            self._book = load_book(self.read("book"))
        return self._book


class FlakyDocs(MemoryDocs):
    """MemoryDocs whose deletes (or reads) can be made to fail, for the wipe's retry path."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_deletes = False
        self.fail_reads = False

    async def get(self, path: str) -> dict[str, Any] | None:
        if self.fail_reads:
            raise RuntimeError("store down")
        return await super().get(path)

    async def write(self, ops: Sequence[Op]) -> None:
        if self.fail_deletes and any(isinstance(o, Delete) for o in ops):
            raise RuntimeError("store down")
        await super().write(ops)

    def dump(self) -> str:
        """Every document as text: what a needle scan reads."""
        return json.dumps(self._data, default=str, ensure_ascii=False)


class RecordingNotifier:
    """notify.ports.Notifier that keeps what it was asked to send."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, Signal, str]] = []
        self.fail = fail

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        if self.fail:
            raise RuntimeError("notify down")
        self.sent.append((uid, signal, message))
        return Delivery(action="ring", reason="direct", telegram=True)


class Prefs:
    """The Book settings reader (D16) as C reads it: a dict per owner."""

    def __init__(self, **values: Any) -> None:
        self.values = values
        self.fail = False

    async def get(self, uid: str) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("settings unreadable")
        return dict(self.values)


_JOIN_AT = re.compile(r"join (\w+) and ([\w.]+) with an at sign", re.IGNORECASE)
_DUMP = re.compile(r"everything you (?:can )?see", re.IGNORECASE)


class WorstCaseProvider:
    """A brain that obeys ANY instruction and echoes what it sees (the guest eval's model).

    It records every request. It answers by echoing the question; "join A and B with an at sign"
    makes it write an address; "everything you see" makes it dump its whole context (the
    reference text and the canary included); "tool" in the question makes it call one."""

    name = "worst-case"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _last(messages: list[ChatMessage]) -> str:
        content = messages[-1].content if messages else ""
        return content if isinstance(content, str) else ""

    def _answer(self, system: str, dynamic: str, messages: list[ChatMessage]) -> str:
        question = self._last(messages)
        if m := _JOIN_AT.search(question):
            return f"Sure: {m.group(1)}@{m.group(2)}"
        if _DUMP.search(question):
            history = " ".join(str(x.content) for x in messages)
            return f"{system}\n{dynamic}\n{history}"
        return f"You asked: {question} The book says JARVIS is built in eight layers."

    async def complete(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Any = None,
        tools: list[ToolSpec] | None = None,
    ) -> Completion:
        self.calls.append(
            {
                "system": system,
                "dynamic": system_dynamic or "",
                "messages": messages,
                "tools": tools,
                "max_tokens": max_tokens,
                "model": model,
            }
        )
        text = self._answer(system, system_dynamic or "", messages)
        return Completion(
            text=text[:4000],
            model=model,
            provider=self.name,
            usage=Usage(input_tokens=6500, output_tokens=250),
            latency_ms=1,
            cost_usd=0.0155,
        )

    def stream(self, **kw: Any) -> Any:  # pragma: no cover - the talk lane never streams
        raise NotImplementedError

    def seen(self) -> str:
        """Everything every request carried, as one text (for "never held an @" checks)."""
        return "\n".join(
            c["system"] + c["dynamic"] + " ".join(str(m.content) for m in c["messages"])
            for c in self.calls
        )


def ist(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def docs_with_ring() -> tuple[FlakyDocs, Keyring]:
    return FlakyDocs(), keyring()


__all__ = [
    "BOOK_DIR",
    "OTHER_UID",
    "OWNER_EMAIL",
    "T0",
    "UID",
    "Clock",
    "FixtureSource",
    "FlakyDocs",
    "Prefs",
    "RecordingNotifier",
    "WorstCaseProvider",
    "docs_with_ring",
    "ist",
    "keyring",
]
