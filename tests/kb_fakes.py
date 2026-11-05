# tests/kb_fakes.py -- R2 C helpers: a NotesService on MemoryDocs with a keyring, a fake Tavily,
# Recently deleted, and a fixed clock. A plain module (not conftest) so tests can import it.
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr
from web_fakes import FakeTavily

from jarvis.kb.store import NotesStore
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.web.allowance import WebAllowance
from jarvis.web.service import WebService
from jarvis.web.tavily import TavilyProvider

if TYPE_CHECKING:
    from jarvis.kb.service import NotesService

UID = "u_owner"
OTHER = "u_other"
ROOT_KEY = bytes(range(1, 33))
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


class Clock:
    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kw: Any) -> None:
        self.at += timedelta(**kw)


@dataclass
class Rig:
    docs: MemoryDocs
    keyring: Keyring
    store: NotesStore
    svc: NotesService
    undo: UndoBin
    fake: FakeTavily
    web: WebService
    allowance: WebAllowance
    clock: Clock


def build_rig(*, with_web: bool = True, with_undo: bool = True) -> Rig:
    docs, clock, fake = MemoryDocs(), Clock(), FakeTavily()
    keyring = Keyring(ROOT_KEY)
    store = NotesStore(docs, keyring)
    allowance = WebAllowance(docs, now=clock)
    web = WebService(TavilyProvider(SecretStr("tvly-k"), http=fake.client()), allowance)
    from jarvis.kb.service import NotesService

    undo = UndoBin(DeletedStore(docs), clock=clock)
    svc = NotesService(
        store,
        web=web if with_web else None,
        undo=undo if with_undo else None,
        clock=clock,
    )
    if with_undo:
        undo.register("note", svc, svc)
    return Rig(docs, keyring, store, svc, undo, fake, web, allowance, clock)


def scan(docs: Any, *needles: str) -> list[str]:
    """Paths of stored documents whose JSON holds any needle (plaintext leak scan)."""
    hits: list[str] = []
    for path, doc in docs._data.items():
        text = json.dumps(doc, ensure_ascii=False, default=str)
        if any(n in text for n in needles):
            hits.append(path)
    return hits
