# tests/test_r63_a_scrub.py -- R6.3 part A, D10 G8 and M8 (docs/plans/r6-3-book-content.md): the
# scrubber's new kinds beyond I0's pins (tests/test_r63_scrub_kinds.py). What is NOT personal stays
# exactly as it is (loopback addresses, times, slices, curve names, dates, versions, code paths);
# phrases match only as whole consecutive words; the redact file's lists load hashes only.
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jarvis.buildbook.gen import scrub as scrub_mod
from jarvis.buildbook.gen.repo import GenError
from jarvis.buildbook.gen.scrub import REMOVED, Scrubber, default_scrubber


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


PHRASE = _h("quimbledorf works")
KEPT = (
    "bind 127.0.0.1 or 0.0.0.0 and ::1 here",
    "the brief runs at 10:30 and 04:00:00 IST",
    "take x[1::2] and y[::3] of the list",
    "keys are x25519 and ed25519; sha256 and es2020",
    "dates 2026-11-23 and 23-11-2026; python-3.11 and gemini-3.1-flash-image",
    "src/jarvis/llm/fallback.py:BREAKER_S and `llm/router.py:GUARD_REFRESH_S`",
    "a MAC 00:1a:2b:3c:4d:5e is not an address we scrub",
    "CONSTANT_NAME1234X and HTTP2 are names, not a PAN",
    "claude-sonnet-5-5 and cloud-run-source-deploy and jarvis-morning-brief",
)
CAUGHT = (
    ("ipv4", "home LAN 10.20.30.40"),
    ("ipv4", "tailnet 100.101.102.103:8123"),
    ("ipv6", "at 2001:db8:85a3::8a2e:370:7334 today"),
    ("pan", "(ABCDE1234F)"),
    ("aadhaar", "id 2345-6789-0123"),
    ("project_id", "gcloud config set project my-proj-123456"),
)


@pytest.mark.parametrize("text", KEPT)
def test_what_is_not_personal_stays_byte_for_byte(text: str) -> None:
    scrub = Scrubber(frozenset(), phrases=frozenset({PHRASE}), domains=frozenset({_h("x.test")}))
    assert scrub.findings(text) == ()
    assert scrub.clean(text) == text


@pytest.mark.parametrize(("kind", "text"), CAUGHT)
def test_each_kind_is_named_and_removed(kind: str, text: str) -> None:
    assert default_scrubber().findings(text) == (kind,)
    assert REMOVED in default_scrubber().clean(text)


def test_aadhaar_is_found_before_the_plain_digits_rule() -> None:
    assert default_scrubber().findings("2345 6789 0123") == ("aadhaar",)
    assert default_scrubber().clean("a 2345 6789 0123 b") == f"a {REMOVED} b"


def test_a_phrase_is_matched_across_case_accents_spacing_and_a_line_wrap() -> None:
    scrub = Scrubber(frozenset(), phrases=frozenset({PHRASE}))
    for text in (
        "Quimbledorf Works",
        "quimbledorf\nWORKS",
        "Quimbledorf-Works",
        "QUIMBLEDÖRF  works",
    ):
        assert scrub.findings(text) == ("name",), text
        assert scrub.clean(text) == REMOVED
    assert scrub.clean("see Quimbledorf Works, again") == f"see {REMOVED}, again"


def test_a_phrase_s_words_alone_or_apart_stay() -> None:
    scrub = Scrubber(frozenset(), phrases=frozenset({PHRASE}))
    for text in ("Quimbledorf", "the Works", "Quimbledorf the Works", "Quimbledorfx Works"):
        assert scrub.findings(text) == (), text


def test_a_longer_phrase_is_found_inside_a_sentence() -> None:
    three = _h("zorblaxton quimbledorf works")
    scrub = Scrubber(frozenset(), phrases=frozenset({three}))
    assert scrub.clean("at Zorblaxton Quimbledorf Works.") == f"at {REMOVED}."


def test_a_host_is_removed_only_under_a_listed_domain() -> None:
    scrub = Scrubber(frozenset(), domains=frozenset({_h("owner-family.example")}))
    assert scrub.clean("a.b.owner-family.example:8080") == f"{REMOVED}:8080"
    assert scrub.findings("owner-family.example.org and family.example") == ()
    assert Scrubber(frozenset()).findings("cam.owner-family.example") == ()


def test_the_redact_lists_load_hashes_only(tmp_path: Path) -> None:
    path = tmp_path / "redact.json"
    path.write_text(json.dumps({"sha256": [], "phrases": [PHRASE], "domains": []}), "utf-8")
    assert scrub_mod.load_phrases(path) == frozenset({PHRASE})
    assert scrub_mod.load_domains(path) == frozenset()
    path.write_text(json.dumps({"phrases": ["Not A Hash"]}), "utf-8")
    with pytest.raises(GenError, match="SHA-256"):
        scrub_mod.load_phrases(path)


def test_the_shipped_list_holds_four_phrases_and_no_domain_yet() -> None:
    assert len(scrub_mod.load_phrases()) == 4
    assert scrub_mod.load_domains() == frozenset()
    assert default_scrubber().findings("Quimbledorf Works") == ()  # a made-up stand-in only


def test_no_scrub_still_lets_everything_through() -> None:
    assert scrub_mod.NoScrub().clean("on 10.0.0.7") == "on 10.0.0.7"


def test_a_card_number_in_groups_of_four_is_digits_not_aadhaar() -> None:
    for text in ("4111 1111 1111 1111", "9999 2345 6789 0123"):
        assert default_scrubber().findings(text) == ("digits",), text
        assert default_scrubber().clean(text) == REMOVED
