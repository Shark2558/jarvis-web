# tests/test_book_gen_scrub.py
"""R6 D3: the build book's scrub (`jarvis.buildbook.gen.scrub`). Every text the generator takes
from the repo passes `Scrubber.clean`; `verify` re-checks the whole book before it is written.
Names are matched by the lower-case SHA-256 of a word (gen/redact.json holds hashes only)."""

from __future__ import annotations

import hashlib
import json
import re

import pytest
from book_gen_fakes import fake_secret, fixture_needles

from jarvis.buildbook.gen import scrub
from jarvis.buildbook.gen.scrub import REMOVED, NoScrub, Scrubber, ScrubLeak


def _h(word: str) -> str:
    return hashlib.sha256(word.lower().encode()).hexdigest()


S = Scrubber(frozenset({_h("zorblat")}))


@pytest.mark.parametrize(
    "text",
    [
        "Mail someone.else@example.org today",
        "Call +91 9876543210 now",
        "Call +91-9876543210 now",
        "Call 9876543210 now",
        "Account 12345678901234 here",
        "Open https://jarvis-abc123-el.a.run.app/console",
        "Host jarvis-abc123-el.a.run.app is live",
        "Host my-laptop.tail1234.ts.net answers",
        "See https://example.com/private/page for it",
        "Zorblat reviewed it",
    ],
)
def test_each_kind_of_personal_text_is_removed(text: str) -> None:
    out = S.clean(text)
    assert REMOVED in out
    assert S.findings(out) == ()


def test_the_removed_text_is_gone_and_the_rest_kept() -> None:
    out = S.clean("Ask zorblat at a.b@example.org or +91 9876543210, then deploy.")
    assert "zorblat" not in out.lower()
    assert "a.b@example.org" not in out and "9876543210" not in out
    assert out.startswith("Ask ") and out.endswith(", then deploy.")


def test_a_hashed_word_is_matched_case_insensitively_and_whole() -> None:
    assert S.clean("ZORBLAT's AirPods") == f"{REMOVED}'s AirPods"
    assert S.clean("zorblats") == "zorblats"  # another word


def test_public_docs_urls_are_kept() -> None:
    text = "Prices: https://cloud.google.com/run/pricing and https://ai.google.dev/gemini-api/docs"
    assert S.clean(text) == text
    assert S.findings(text) == ()


def test_secret_shaped_strings_are_removed_too() -> None:
    for kind in ("google", "anthropic", "github", "aws", "telegram"):
        out = S.clean(f"key {fake_secret(kind)} end")
        assert out == f"key {REMOVED} end", kind


def test_clean_is_idempotent_and_nfc() -> None:
    once = S.clean("Café at a@example.org")
    assert S.clean(once) == once
    assert "Café" in once


def test_ordinary_book_text_is_untouched() -> None:
    text = "Release R6 (3f2a1c9): 1,233 files, 2026-11-10, ₹95.24 a dollar, 900,000 characters."
    assert S.clean(text) == text
    assert S.findings(text) == ()


def test_findings_name_kinds_never_the_text() -> None:
    kinds = S.findings("zorblat a@example.org 9876543210")
    assert set(kinds) == {"name", "email", "phone"}
    assert all(re.fullmatch(r"[a-z_]+", k) for k in kinds)


def test_verify_walks_the_tree_and_names_paths_not_text() -> None:
    tree = {
        "release": {"sha": "9876543210" * 4},  # a commit id is never scrubbed
        "workflows": [{"steps": [{"symbol": "jarvis.core.brain:Brain.chat"}]}],
        "limitations": [{"text": "fine"}, {"text": "write to a@example.org"}],
    }
    with pytest.raises(ScrubLeak) as err:
        S.verify(tree)
    msg = str(err.value)
    assert "limitations[1].text" in msg and "email" in msg
    assert "a@example.org" not in msg
    S.verify({"release": {"sha": "9876543210" * 4}, "a": ["fine", {"b": "ok"}]})


def test_no_scrub_is_the_negative_control() -> None:
    off = NoScrub()
    assert off.clean("a@example.org") == "a@example.org"
    off.verify({"x": "a@example.org"})  # does nothing


def test_redact_json_holds_only_hashes_and_covers_the_fixture_name() -> None:
    data = json.loads(scrub.REDACT_FILE.read_text(encoding="utf-8"))
    hashes = data["sha256"]
    assert hashes == sorted(set(hashes))
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
    _, _, name = fixture_needles()
    words = name.lower().split()
    assert {_h(w) for w in words} <= set(hashes)
    raw = scrub.REDACT_FILE.read_text(encoding="utf-8").lower()
    assert all(w not in raw for w in words)  # no plaintext name in the file


def test_the_default_scrubber_removes_the_fixture_needles() -> None:
    email, phone, name = fixture_needles()
    out = scrub.default_scrubber().clean(f"{name} at {email}, {phone}.")
    for needle in (email, phone, *name.split()):
        assert needle not in out
