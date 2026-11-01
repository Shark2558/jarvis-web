# tests/test_web_sources.py — slice 10 B: URL normalisation, the per-conversation source ledger
# (numbering, the web_read allow-list, cited sources) and the private-query guard.
from __future__ import annotations

import pytest

from jarvis.core.models import Session, Turn
from jarvis.llm.base import Role, TextBlock, ToolResultBlock
from jarvis.web.guard import query_problem
from jarvis.web.ledger import (
    LEDGER_KEY,
    MAX_SOURCES,
    cited_numbers,
    cited_sources,
    conversation_of,
    current_conversation,
    web_conversation,
)
from jarvis.web.sources import domain_of, normalize_url, urls_in_text

# ---- normalize_url ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("https://Example.COM/Path?q=1#frag", "https://example.com/Path?q=1"),
        ("HTTPS://example.com", "https://example.com/"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("https://Bücher.de/x", "https://xn--bcher-kva.de/x"),
        ("https://xn--bcher-kva.de/x", "https://xn--bcher-kva.de/x"),
        ("  https://example.com/a  ", "https://example.com/a"),
        ("https://example.com./a", "https://example.com/a"),
    ],
)
def test_normalize_keeps_https_and_canonicalises(raw: str, want: str) -> None:
    assert normalize_url(raw) == want


@pytest.mark.parametrize(
    "raw",
    [
        "http://example.com/a",  # https only
        "ftp://example.com/a",
        "javascript:alert(1)",
        "data:text/html,hi",
        "https://user:pw@example.com/a",  # userinfo
        "https://127.0.0.1/a",  # IP literal
        "https://[::1]/a",
        "https://localhost/a",  # single label
        "https://ex ample.com/",
        "https://exa%6dple.com/",
        "https://example.com/a\nb",
        "https://example.com/" + "a" * 2100,
        "",
        None,
        42,
        "example.com/a",
    ],
)
def test_normalize_refuses_everything_else(raw: object) -> None:
    assert normalize_url(raw) is None


def test_domain_drops_www_and_stays_punycode() -> None:
    assert domain_of("https://www.example.com/a") == "example.com"
    assert domain_of("https://xn--bcher-kva.de/") == "xn--bcher-kva.de"
    assert domain_of("https://news.example.co.uk:8443/x") == "news.example.co.uk"


def test_urls_in_text_finds_https_links_without_trailing_punctuation() -> None:
    text = (
        "Read https://example.com/a, and (https://example.org/b). Also http://plain.example/c "
        "and https://en.wikipedia.org/wiki/Foo_(bar)!"
    )
    assert urls_in_text(text) == [
        "https://example.com/a",
        "https://example.org/b",
        "https://en.wikipedia.org/wiki/Foo_(bar)",
    ]


# ---- the ledger --------------------------------------------------------------------------------


def _session(*owner: str, voice: str | None = None) -> Session:
    s = Session(user_id="u_owner")
    for text in owner:
        s.append(Turn(role=Role.USER, content=text))
    if voice is not None:
        s.append(Turn(role=Role.USER, content=voice, channel="voice"))
    return s


def test_numbers_are_stable_and_deduplicated_across_the_conversation() -> None:
    s = _session("hi")
    c = conversation_of(s)
    assert c.add("A", "https://a.example/1") == 1
    assert c.add("B", "https://b.example/2") == 2
    assert c.add("A again", "https://A.example/1#top") == 1  # same page, same number
    # a later turn (a fresh view of the same stored metadata) continues the numbering
    c2 = conversation_of(s)
    assert c2.add("C", "https://c.example/3") == 3
    assert [x.n for x in c2.sources()] == [1, 2, 3]
    assert s.metadata[LEDGER_KEY]["next"] == 4


def test_ledger_keeps_only_the_newest_sources_but_never_reuses_a_number() -> None:
    s = _session("hi")
    c = conversation_of(s)
    for i in range(MAX_SOURCES + 5):
        c.add(f"T{i}", f"https://x.example/{i}")
    kept = c.sources()
    assert len(kept) == MAX_SOURCES and kept[0].n == 6
    assert c.add("new", "https://x.example/new") == MAX_SOURCES + 6
    assert not c.allows("https://x.example/0")  # dropped from the ledger → no longer readable


def test_allow_list_is_results_plus_what_the_owner_typed() -> None:
    s = _session("Please read https://owner.example/report?id=7 for me")
    s.append(Turn(role=Role.ASSISTANT, content="See https://model.example/said"))
    tool = Turn(role=Role.USER, content="", blocks=[ToolResultBlock(tool_use_id="t", content="x")])
    s.append(tool)
    s.append(Turn(role=Role.USER, content="", blocks=[TextBlock(text="https://hidden.example/")]))
    c = conversation_of(_copy_with_voice(s, "read https://spoken.example/page"))
    c.add("Found", "https://result.example/a")
    assert c.allows("https://owner.example/report?id=7")
    assert c.allows("https://OWNER.example/report?id=7#x")  # normalised exact match
    assert c.allows("https://result.example/a")
    assert not c.allows("https://owner.example/report?id=8")  # not a prefix match
    assert not c.allows("https://model.example/said")  # the model's own words don't count
    assert not c.allows("https://hidden.example/")  # tool/instruction blocks don't count
    assert not c.allows("https://spoken.example/page")  # spoken: may be someone else's words
    assert not c.allows("http://owner.example/report?id=7")


def _copy_with_voice(s: Session, text: str) -> Session:
    s.append(Turn(role=Role.USER, content=text, channel="voice"))
    return s


def test_tampered_ledger_entries_are_ignored_not_trusted() -> None:
    s = _session("hi")
    s.metadata[LEDGER_KEY] = {
        "next": "x",
        "sources": [
            {"n": 1, "title": "ok", "url": "https://ok.example/", "domain": "ok.example"},
            {"n": 2, "title": "bad", "url": "javascript:alert(1)", "domain": "x"},
            {"n": "3", "title": "bad n", "url": "https://n.example/", "domain": "n.example"},
            "junk",
        ],
    }
    c = conversation_of(s)
    assert [x.url for x in c.sources()] == ["https://ok.example/"]
    assert c.add("next", "https://next.example/") == 2
    s.metadata[LEDGER_KEY] = "not a map"
    assert conversation_of(s).sources() == []


def test_the_conversation_is_visible_only_inside_the_context() -> None:
    s = _session("hi")
    assert current_conversation() is None
    with web_conversation(s) as c:
        assert current_conversation() is c
    assert current_conversation() is None


# ---- citations ---------------------------------------------------------------------------------


def test_cited_numbers_reads_the_usual_forms() -> None:
    text = "Rates rose [1]. Both agree [2][3], see also [4, 5] and [ 6 ]; arr[7] is code; [x]"
    assert cited_numbers(text) == [1, 2, 3, 4, 5, 6]  # not arr[7], not [x]


def test_only_cited_sources_from_the_ledger_are_returned() -> None:
    s = _session("hi")
    c = conversation_of(s)
    for i in range(1, 5):
        c.add(f"T{i}", f"https://s.example/{i}")
    out = cited_sources("A [3] and B [1] and invented [9] and again [3].", s.metadata)
    assert [(x.n, x.url) for x in out] == [(1, "https://s.example/1"), (3, "https://s.example/3")]
    assert out[0].title == "T1" and out[0].domain == "s.example"
    assert cited_sources("No citations here.", s.metadata) == []
    assert cited_sources("A [1]", s.metadata, enabled=False) == []
    assert cited_sources("A [1]", {}) == []


# ---- the private-query guard --------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "priya.sharma@example.com linkedin",
        "who owns +91 98765 43210",
        "9876543210 owner name",
        "(415) 555-0132 business",
        "card 4111 1111 1111 1111 balance",
        "PAN ABCDE1234F status",
        "aadhaar 2345 6789 0123",
        "my password is hunter22 leaked?",
    ],
)
def test_guard_refuses_queries_with_private_identifiers(query: str) -> None:
    reason = query_problem(query)
    assert reason is not None
    # names the kind of data, never the value
    assert "@" not in reason and not any(ch.isdigit() for ch in reason)
    assert "hunter" not in reason and "ABCDE" not in reason


@pytest.mark.parametrize(
    "query",
    [
        "RBI repo rate November 2026",
        "population of India 1.4 billion",
        "ISBN 978-0-306-40615-7 review",
        "iPhone 17 price in India",
        "ISO 27001 certification cost",
        "weather Thiruvananthapuram 2026-11-01",
        "train 12625 Kerala Express running status",
    ],
)
def test_guard_lets_ordinary_queries_through(query: str) -> None:
    assert query_problem(query) is None
