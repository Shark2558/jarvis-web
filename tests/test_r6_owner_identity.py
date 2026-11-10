# tests/test_r6_owner_identity.py -- R6 D3 amendment (integrated review SEC-1): ONE owner-identity
# rule for the sealer, the guest door and the reply guard. The FULL owner address always counts,
# in any form (case, NFC/NFKC, percent-encoding, HTML entities, " at "/" dot " and [at]/(dot)
# spellings, zero-width characters); a local-part token (split on . _ - + and digits) counts only
# when it has >= 3 letters AND is not in JARVIS's fixed vocabulary, so an everyday local part
# ("owner", "jarvis", "home", "info", "mail", "vault") never blocks a release, a guest show or
# the owner's own replies, while "first.last@" still matches "First Last" and "Last, First".
from __future__ import annotations

import pytest
from book_seal_fakes import (
    NOW,
    FakeAudit,
    FakeNotifier,
    FakeSource,
    fixture_book,
    make_release,
    ring,
)
from book_show_fakes import T0, UID, FixtureSource, FlakyDocs, RecordingNotifier, keyring

from jarvis.buildbook import guard, owner_id, release
from jarvis.buildbook.lock import DocShowLock
from jarvis.buildbook.model import canonical_bytes, load_book
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.seal_words import holds_owner_email
from jarvis.buildbook.sealer import BookSealer
from jarvis.buildbook.service import BookService
from jarvis.buildbook.sessions import DocBookSessions
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

EVERYDAY = (
    "owner",
    "jarvis",
    "home",
    "info",
    "mail",
    "vault",
    "test",
    "book",
    "build",
    "google",
    "work",
    "personal",
    "the",
)
# a book text that holds every everyday word the reviewers found in this release's real book
WORDS = (
    "The owner's JARVIS keeps the home vault; info, mail, test, book, build, Google, work and "
    "personal notes are explained in the build book."
)
VOCAB_ONLY = "home.vault@example.com"  # every token is JARVIS's own word: only the address counts
NAMED = "akash.kumar@example.com"
HOSTS = frozenset({"cloud.google.com"})


def _book_with(text: str) -> bytes:
    data = canonical_bytes(fixture_book())
    return data.replace(b"The core loop sits in layer four.", text.encode("utf-8"), 1)


def _sealer(owner: str, book: bytes | None = None) -> tuple[BookSealer, FakeNotifier]:
    rel, files = make_release(1, book=None if book is None else load_book(book))
    docs, notes = MemoryDocs(), FakeNotifier()
    sealer = BookSealer(
        FakeSource(rel, files),
        DocsBookVault(docs, ring(), limit_mb=60, clock=lambda: NOW),
        docs,
        notifier=notes,
        audit=FakeAudit(),
        owner_emails=(owner,),
        honorific="Sir",
        limit_mb=60,
        clock=lambda: NOW,
    )
    return sealer, notes


def _reply(text: str, owners: tuple[str, ...]) -> str | None:
    return guard.post_guard(text, canary="CANARY9", owner_emails=owners, allowed_hosts=HOSTS)


# ---- an everyday local part never self-blocks --------------------------------------------------
@pytest.mark.parametrize("local", EVERYDAY)
def test_an_everyday_local_part_is_not_a_name(local: str) -> None:
    owners = (f"{local}@example.com",)
    data = _book_with(WORDS)
    assert owner_id.in_book(data, owners) is None
    assert holds_owner_email(data, owners) is False
    assert guard.book_names_owner(data, owners) is False
    assert release.owner_mentioned(data, owners) is False
    assert (
        _reply("I am JARVIS: the owner's home vault holds his notes, info and mail.", owners)
        is None
    )


@pytest.mark.parametrize("local", ["owner", "jarvis", "home", "vault"])
async def test_an_everyday_local_part_still_seals(local: str) -> None:
    sealer, notes = _sealer(f"{local}@example.com", _book_with(WORDS))
    assert (await sealer.ensure(UID)).state == "sealed"
    assert [kind for _, kind, _ in notes.sent] == ["book_sealed"]


@pytest.mark.parametrize("local", ["owner", "jarvis", "home", "info", "mail", "vault"])
async def test_an_everyday_local_part_still_runs_a_guest_show(local: str) -> None:
    docs = FlakyDocs()
    svc = BookService(
        source=FixtureSource(),
        sessions=DocBookSessions(docs, keyring()),
        lock=DocShowLock(docs, cache_s=0),
        talk=None,
        audit=AuditLog(),
        notifier=RecordingNotifier(),
        docs=docs,
        owner_emails=(f"{local}@example.com",),
    )
    assert svc.guest_refusal() is None
    opened = await svc.open(UID, "guest", how="passkey 1a2b", now=T0)
    assert opened.session.audience == "guest"
    assert (await svc.script(UID, opened.session))["scenes"]


# ---- the full address, in any form -------------------------------------------------------------
OBFUSCATED = (
    "HOME.VAULT@EXAMPLE.COM",
    "ｈｏｍｅ.ｖａｕｌｔ＠ｅｘａｍｐｌｅ.ｃｏｍ",  # full-width (NFKC)
    "home.vault%40example.com",
    "home%2Evault%40example%2Ecom",
    "home.vault%2540example.com",  # percent-encoded twice
    "home.vault&#64;example.com",
    "home.vault&commat;example&period;com",
    "&#x68;ome.vault&#x40;example.com",
    "home.vault at example dot com",
    "home dot vault at example dot com",
    "home.vault [at] example (dot) com",
    "home.vault(at)example(dot)com",
    "home.vault @ example . com",
    "home.​vault@exa‍mple.com",  # zero-width characters
    "home.vault\\u0040example.com",  # a JSON escape left in text
)


@pytest.mark.parametrize("text", OBFUSCATED)
def test_the_full_address_counts_in_any_form(text: str) -> None:
    owners = (VOCAB_ONLY,)
    assert owner_id.match(text, owners) == "address"
    data = _book_with(f"Written by {text} on a Sunday.")
    assert owner_id.in_book(data, owners) == "address"
    assert holds_owner_email(data, owners) is True
    assert guard.book_names_owner(data, owners) is True
    assert _reply(f"My owner is {text}.", owners) == "refuse_data"


def test_the_vocabulary_words_alone_are_not_the_address() -> None:
    owners = (VOCAB_ONLY,)
    for text in ("The home vault", "home.vault", "home-vault keeps it", "Vault, Home"):
        assert owner_id.match(text, owners) is None


# ---- distinctive tokens: names ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("Built by Akash Kumar.", "word"),
        ("Kumar, Akash wrote it.", "word"),
        ("akash_kumar did this", "word"),
        ("ＡＫＡＳＨ was here", "word"),
        ("ak​ash", "word"),
        ("Akashic records", None),
        ("The kumaran river", None),
        ("akash.kumar@example.com", "address"),
    ],
)
def test_first_last_matches_the_name_in_any_order(text: str, hit: str | None) -> None:
    assert owner_id.match(text, (NAMED,)) == hit
    expected = None if hit is None else "refuse_data"
    assert _reply(text, (NAMED,)) == expected


def test_tokens_split_on_separators_and_digits() -> None:
    marks = owner_id.marks(["Akash.Kumar+jarvis_99-Home@Example.com", "ab.c@example.com", " "])
    assert marks.addresses == ("akash.kumar+jarvis_99-home@example.com", "ab.c@example.com")
    assert marks.tokens == ("akash", "kumar")  # "jarvis", "home": vocabulary; "ab", "c": short


def test_the_vocabulary_is_fixed_text_only() -> None:
    vocab = owner_id.vocabulary()
    assert vocab is owner_id.vocabulary()  # built once
    for word in ("jarvis", "owner", "vault", "home", "info", "mail", "device", "commit", "layers"):
        assert word in vocab, word
    for name in ("akash", "kumar", "priya"):
        assert name not in vocab


def test_the_seal_notice_names_what_matched() -> None:
    from jarvis.buildbook.seal_words import personal_words

    assert "holds your e-mail address" in personal_words("address")
    assert "holds a word from your e-mail address" in personal_words("word")


async def test_a_book_holding_a_name_token_is_refused_with_its_own_words() -> None:
    sealer, notes = _sealer(NAMED, _book_with("Built by Akash Kumar."))
    assert (await sealer.ensure(UID)).state == "failed"
    ((_, kind, words),) = notes.sent
    assert kind == "book_seal_failed" and "a word from your e-mail address" in words
    assert "akash" not in words.lower()


# ---- security re-review #3: a handle-style local part counts as a whole ------------------------
HANDLES = ("rk1987", "jk.rk", "ak47", "ab12cd")  # no token of >= 3 letters: once only the address


@pytest.mark.parametrize("local", HANDLES)
async def test_a_short_handle_local_part_counts_as_a_whole(local: str) -> None:
    owners = (f"{local}@example.com",)
    text = f"Thanks to {local.upper()} for the review."
    assert owner_id.match(text, owners) == "word"
    data = _book_with(text)
    assert owner_id.in_book(data, owners) == "word"
    assert holds_owner_email(data, owners) is True
    assert guard.book_names_owner(data, owners) is True
    assert release.owner_mentioned(data, owners) is True
    assert _reply(f"The reviewer was {local}.", owners) == "refuse_data"
    sealer, notes = _sealer(owners[0], data)
    assert (await sealer.ensure(UID)).state == "failed"
    assert "a word from your e-mail address" in notes.sent[0][2]


@pytest.mark.parametrize(
    "text",
    ["xrk1987 did it", "rk19870 did it", "build rk1987x", "a.rk1987 did it", "rk 1987", "rk-1987"],
)
def test_the_whole_local_part_counts_only_as_itself(text: str) -> None:
    assert owner_id.match(text, ("rk1987@example.com",)) is None


@pytest.mark.parametrize(
    ("email", "whole"),
    [
        ("rk1987@example.com", ("rk1987",)),
        ("RK1987+jarvis@example.com", ("rk1987+jarvis", "rk1987")),  # the mailbox without its tag
        ("akash.kumar@example.com", ("akash.kumar",)),
        ("owner2@example.com", ("owner2",)),  # a number makes it a handle
        ("rk1@example.com", ()),  # < 4 characters: not a name
        ("owner@example.com", ()),
        ("home@example.com", ()),
        ("info@example.com", ()),
        ("home.vault@example.com", ()),  # only vocabulary words: the address alone (D3 amendment)
        ("owner+jarvis@example.com", ()),
    ],
)
def test_the_whole_local_part_is_a_needle_unless_it_is_only_everyday_words(
    email: str, whole: tuple[str, ...]
) -> None:
    assert owner_id.marks([email]).whole == whole
