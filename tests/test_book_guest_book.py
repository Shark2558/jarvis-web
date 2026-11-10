# tests/test_book_guest_book.py -- R6 D1/D3 at the door: a guest is never shown a book that names
# an owner's e-mail address or its local part (the same refusal the sealer makes before sealing),
# checked at the guest open and again on every guest read (script, spoken line, question); a book
# that can't be read is refused too (fail closed). The owner may still open his own book.
from __future__ import annotations

from typing import Any

import pytest
from book_app_fakes import CSRF, book_app, proof, register_passkey, sign_in
from book_show_fakes import (
    BOOK_DIR,
    OWNER_EMAIL,
    T0,
    UID,
    FixtureSource,
    FlakyDocs,
    NamingSource,
    RecordingNotifier,
    keyring,
)

from jarvis.buildbook import guard
from jarvis.buildbook.lock import DocShowLock
from jarvis.buildbook.ports import BookUnavailable
from jarvis.buildbook.service import BookService
from jarvis.buildbook.sessions import DocBookSessions
from jarvis.config import Settings
from jarvis.tools.audit import AuditLog

CLEAN = (BOOK_DIR / "book.json").read_bytes()


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Mail Akash.Owner@Example.com for access.", True),
        ("Written by akash.owner on a Sunday.", True),
        ("Written by ａｋａｓｈ.ｏｗｎｅｒ.", True),  # full-width letters (NFKC)
        ("akash.owner\\u0040example.com", True),  # a JSON escape
        ("The akash.owners club", True),  # D3 amendment: "akash" is the distinctive token
        ("The Akashic owners club", False),  # not a whole word; "owner" is JARVIS's own word
        ("The core loop sits in layer four.", False),
    ],
)
def test_the_book_check(text: str, named: bool) -> None:
    data = CLEAN.replace(b"The core loop sits in layer four.", text.encode("utf-8"), 1)
    assert guard.book_names_owner(data, (OWNER_EMAIL,)) is named
    assert guard.book_names_owner(CLEAN, (OWNER_EMAIL,)) is False
    assert guard.book_names_owner(data, ()) is False


def _svc(source: Any) -> BookService:
    docs = FlakyDocs()
    return BookService(
        source=source,
        sessions=DocBookSessions(docs, keyring()),
        lock=DocShowLock(docs, cache_s=0),
        talk=None,
        audit=AuditLog(),
        notifier=RecordingNotifier(),
        docs=docs,
        owner_emails=(OWNER_EMAIL,),
    )


async def test_a_guest_never_opens_a_book_naming_the_owner() -> None:
    svc = _svc(NamingSource())
    assert svc.guest_book_ok() is False
    with pytest.raises(BookUnavailable):
        await svc.open(UID, "guest", how="passkey 1a2b", now=T0)
    assert await svc.sessions.live(UID, now=T0) is None and await svc.lock_state(UID) is None
    owner = await svc.open(UID, "owner", how="passkey 1a2b", now=T0)  # his own book: fine
    assert owner.session.audience == "owner"
    assert _svc(FixtureSource()).guest_book_ok() is True


async def test_an_unreadable_book_is_refused_to_a_guest() -> None:
    source = NamingSource(text="The core loop sits in layer four.")
    source.broken = True
    svc = _svc(source)
    assert svc.guest_book_ok() is False
    with pytest.raises(BookUnavailable):
        await svc.open(UID, "guest", how="passkey 1a2b", now=T0)


async def test_every_guest_read_is_checked() -> None:
    svc = _svc(NamingSource())
    guest = (await svc.sessions.open(UID, "guest", now=T0))[0].session  # not through open()
    with pytest.raises(BookUnavailable):
        await svc.script(UID, guest)
    with pytest.raises(BookUnavailable):
        await svc.line_text(UID, guest, "s02b02")
    with pytest.raises(BookUnavailable):
        await svc.ask(UID, guest, "How does voice work?", now=T0)


async def test_the_route_answers_no_book_and_audits_the_refusal(settings: Settings) -> None:
    async for app in book_app(settings, source=NamingSource()):
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            body = {"audience": "guest", "proof": await proof(c, auth, "book_open", "guest")}
            r = await c.post("/v1/book/open", json=body, headers=CSRF)
            assert r.status_code == 404 and r.json()["error"] == "no_book"
            assert "e-mail" in r.json()["detail"]
            assert (await c.get("/auth/me")).status_code == 200  # nothing locked
            body = {"audience": "owner", "proof": await proof(c, auth, "book_open", "owner")}
            assert (await c.post("/v1/book/open", json=body, headers=CSRF)).status_code == 200
        tail = await app.state.gateway.audit.tail(20)
        opens = [(e.tool, e.outcome) for e in tail.entries if e.tool == "book_open"]
        assert opens == [("book_open", "refused"), ("book_open", "executed")]
