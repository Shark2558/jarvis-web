# tests/test_r63_scrub_kinds.py -- R6.3 I0 seam 11 (docs/plans/r6-3-book-content.md D10 G8): the
# scrubber's NEW kinds, pinned here by I0 and built by PART A in `gen/scrub.py` (which also guards
# book.json, and which B's check (3) calls). A turns the marked tests green and removes their
# `xfail` marks (strict: a pass under the mark fails the suite, so the mark cannot be forgotten).
#
# The kinds `Scrubber.findings` names: "ipv4", "ipv6", "pan" (an Indian PAN, [A-Z]{5}[0-9]{4}[A-Z]),
# "aadhaar" (12 digits in groups of four), "host" (a hostname under a domain whose SHA-256 is in
# gen/redact.json's `domains` list: `Scrubber(redact, domains=...)`), "project_id" (a Google
# Cloud project-id shape: 6-30 lower-case letters, digits and hyphens, a letter first, with a
# digit run of 4 or more, as `my-proj-123456`), and M8's phrases ("name": a several-word name from
# redact.json's `phrases`, matched as consecutive words). Versions, dates, line numbers and code
# paths are NOT personal and stay as they are (the unmarked tests: true today, true after A).
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jarvis.buildbook.gen import scrub as scrub_mod
from jarvis.buildbook.gen.scrub import REMOVED, Scrubber, default_scrubber

NEW_KINDS = ("ipv4", "ipv6", "pan", "aadhaar", "host", "project_id")
CAUGHT = (
    ("ipv4", "the bridge answers on 192.168.1.20 at home"),
    ("ipv6", "or on fe80::1ff:fe23:4567:890a"),
    ("pan", "his PAN ABCDE1234F is on file"),
    ("aadhaar", "the number 2345 6789 0123 was read"),
    ("project_id", "deployed to jarvis-home-482913 last week"),
)
OWNER_DOMAIN = "owner-family.example"
LEFT_ALONE = (
    "v6.3.0 shipped on 2026-11-23",
    "see src/jarvis/buildbook/model.py:235 and model.py:70",
    "R6.3 and C16 and HTTP/2 and SHA-256",
    "the hold is Rs 11.84 at 95.24 a dollar",
    "`api/r6_wiring.py` and `/v1/book/writer/step`",
)


@pytest.mark.parametrize(("kind", "text"), CAUGHT)
def test_each_new_kind_is_found_and_removed(kind: str, text: str) -> None:
    scrub = default_scrubber()
    assert kind in scrub.findings(text), (kind, text)
    assert REMOVED in scrub.clean(text)


def test_a_hostname_under_a_listed_domain_is_removed() -> None:
    domains = frozenset({hashlib.sha256(OWNER_DOMAIN.encode()).hexdigest()})
    scrub = Scrubber(frozenset(), domains=domains)  # type: ignore[call-arg]
    text = f"the camera at cam.{OWNER_DOMAIN} and {OWNER_DOMAIN}"
    assert "host" in scrub.findings(text) and OWNER_DOMAIN not in scrub.clean(text)
    assert scrub.findings("docs at cloud.google.com") == ()  # an unlisted public host stays


def test_a_listed_phrase_is_removed_whole_and_its_words_alone_stay(tmp_path: Path) -> None:
    """M8: a several-word name (gen/redact.json `phrases`, scripts/redact_add.py) is matched as
    consecutive words, in any case, spacing or accent; its ordinary words alone stay."""
    phrase = hashlib.sha256(b"quimbledorf works").hexdigest()
    redact = tmp_path / "redact.json"
    redact.write_text(json.dumps({"sha256": [], "phrases": [phrase], "v": 1}), encoding="utf-8")
    assert scrub_mod.load_phrases(redact) == frozenset({phrase})  # type: ignore[attr-defined]
    scrub = Scrubber(frozenset(), phrases=frozenset({phrase}))  # type: ignore[call-arg]
    text = "we met at QUIMBLEDORF   Wörks today"
    assert "name" in scrub.findings(text) and "uimbledorf" not in scrub.clean(text).lower()
    assert scrub.findings("the Works page") == ()


def test_book_json_is_guarded_by_the_new_kinds_too() -> None:
    with pytest.raises(Exception, match="ipv4"):
        default_scrubber().verify({"architecture": {"note": "on 10.0.0.7"}})


@pytest.mark.parametrize("text", LEFT_ALONE)
def test_versions_dates_line_numbers_and_code_paths_are_left_alone(text: str) -> None:
    assert default_scrubber().findings(text) == ()
    assert default_scrubber().clean(text) == text


def test_the_pinned_kinds() -> None:
    assert NEW_KINDS == ("ipv4", "ipv6", "pan", "aadhaar", "host", "project_id")
    assert {k for k, _ in CAUGHT} | {"host"} == set(NEW_KINDS)
