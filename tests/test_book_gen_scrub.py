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


# ---- review fixes: more shapes, phone formats, disguised names, hidden URLs ------------------
NEW_SHAPES = ("telegram_dash", "google_oauth", "tavily", "openai", "groq", "openrouter")


@pytest.mark.parametrize("kind", NEW_SHAPES)
def test_every_snapshot_secret_shape_is_scrubbed_from_the_book(kind: str) -> None:
    assert S.clean(f"key {fake_secret(kind)}\nend") == f"key {REMOVED}\nend"


@pytest.mark.parametrize("kind", ["pem_block", "pgp"])
def test_a_private_key_block_is_removed_whole(kind: str) -> None:
    out = S.clean(f"before\n{fake_secret(kind)}\nafter")
    assert out == f"before\n{REMOVED}\nafter"


@pytest.mark.parametrize(
    "text",
    [
        "Call 98765 43210 now",
        "Call 98765-43210 now",
        "Call +91 98765 43210 now",
        "Call +91-98765-43210 now",
        "Call 0 98765 43210 now",
        "Call 098765 43210 now",
        "Call 0091 98765 43210 now",
        "Call 987 654 3210 now",
        "Call 9876 543 210 now",
        "Call 98765.43210 now",
        "Call 98765–43210 now",
        "Call 0471-2345678 now",
        "Call 011 2345 6789 now",
        "Call +44 20 7946 0958 now",
        "Call +1 415 555 0100 now",
        "Number 1234 5678 9012 here",
        "Number 4111 1111 1111 1111 here",
        "Number 123-456-7890 here",
    ],
)
def test_phone_numbers_with_separators_are_removed(text: str) -> None:
    out = S.clean(text)
    assert REMOVED in out and not re.search(r"\d\d", out), out
    assert S.findings(out) == () and out.split()[0] == text.split()[0]


@pytest.mark.parametrize(
    "text",
    [
        "Release R6 (3f2a1c9) on 2026-11-10, 2026-11-12 and 2026-11-14.",
        "Dates 2026-11-01 2026-11-10 and 10.11.2026 09:00.",
        "Versions 3.12.1, 0.115.0, 6.2.0.post1 and 2.9.2; pip 26.2.1; three 0.187.0.",
        "₹95.24 a dollar; ₹1,234,567.89 a year; 900,000 characters; 1 2 3 4 5 6 7 8 9 10.",
        "Prices 0.25 0.50 0.75 1.00 and 9.99 8.50 7.25 6.00; 1.234.567.890 in Europe.",
        "Ports 8080 and 8098; 127.0.0.1 and 192.168.1.10; 512 MiB, 1 GiB, 15 MB.",
        "A 7-digit id 1234567, a year range 2024-2025 and 54 minutes a month.",
        "+5 more, -3 fewer, x 2.5, 100-200 requests.",
    ],
)
def test_ordinary_numbers_dates_and_versions_are_kept(text: str) -> None:
    assert S.clean(text) == text and S.findings(text) == ()


@pytest.mark.parametrize(
    "text",
    [
        "Ｚｏｒｂｌａｔ said",  # fullwidth
        "Zor​blat said",  # a zero-width space inside
        "Zor­blat said",  # a soft hyphen inside
        "Zоrblat said",  # a Cyrillic look-alike "o"
        "Zórblat said",  # an accent
        "zorblat2558 said",  # digits glued on
        "2558Zorblat said",
        "ZorblatSmith said",  # camel case
        "smithZorblat said",
    ],
)
def test_a_disguised_name_is_still_removed(text: str) -> None:
    assert S.clean(text) == f"{REMOVED} said"
    assert S.findings(text) == ("name",)


def test_words_that_only_look_near_a_name_are_kept() -> None:
    text = "zorblats AirPods Zorblatty iPhone R6 OAuth2 HTTPServer"
    assert S.clean(text) == text


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("Open HTTPS://private.example.com/x now", "private"),
        ("Open Http://private.example.com/x now", "private"),
        ("Open www.private-site.in/x now", "private"),
        ("Back up to gs://my-proj-123-backups now", "proj"),
        ("Push asia-south1-docker.pkg.dev/my-proj-123/repo/img now", "proj"),
        ("Push gcr.io/my-proj-123/img now", "proj"),
        ("Read storage.googleapis.com/my-bucket-9/f now", "bucket"),
        ("Open https://docs.python.org/?u=someone%40gmail.com now", "someone"),
        ("Open https://user:pw@docs.python.org/3/ now", "user"),
    ],
)
def test_hidden_urls_and_project_hosts_are_removed(text: str, needle: str) -> None:
    out = S.clean(text)
    assert needle not in out and REMOVED in out and S.findings(out) == (), out
    assert out.startswith(text.split()[0]) and out.endswith(" now")


def test_a_secret_in_an_allowed_url_removes_the_url() -> None:
    out = S.clean(f"Open https://docs.python.org/bot{fake_secret('telegram')} now")
    assert out == f"Open {REMOVED} now"


def test_allowed_urls_in_any_case_and_www_are_kept() -> None:
    text = "See HTTPS://Docs.Python.org/3/ and www.w3.org/TR/css and https://www.w3.org/x"
    assert S.clean(text) == text
