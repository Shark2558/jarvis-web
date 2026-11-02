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
    owner_index,
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


def test_a_message_with_files_is_an_owner_message() -> None:
    """Integration review M3: the owner's text plus the fenced note of an attached file (a second
    text block) starts a new owner message; its typed link is readable, the file's are not. A tool
    exchange (results, an approval's instruction) never is one."""
    s = _session("hello")
    s.append(Turn(role=Role.ASSISTANT, content="hi"))
    text = "read this https://owner.example/a"
    note = "<<EXTERNAL CONTENT from file · 123456>>\nsee https://file.example/b\n<<END 123456>>"
    s.append(
        Turn(role=Role.USER, content=text, blocks=[TextBlock(text=text), TextBlock(text=note)])
    )
    assert owner_index(s) == 2
    c = conversation_of(s)
    assert c.allows("https://owner.example/a") and not c.allows("https://file.example/b")
    result = ToolResultBlock(tool_use_id="t", content="x")
    s.append(Turn(role=Role.USER, content="", blocks=[result, TextBlock(text="Owner approved.")]))
    assert owner_index(s) == 2


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


def test_only_sources_shown_in_this_turn_are_returned() -> None:
    s = _session("hi")
    c = conversation_of(s)
    for i in range(1, 5):
        c.add(f"T{i}", f"https://s.example/{i}")
    out = cited_sources("A [3] and B [1] and invented [9] and again [3].", s)
    assert [(x.n, x.url) for x in out] == [(1, "https://s.example/1"), (3, "https://s.example/3")]
    assert out[0].title == "T1" and out[0].domain == "s.example"
    assert cited_sources("No citations here.", s) == []
    assert cited_sources("A [1]", s, enabled=False) == []
    assert cited_sources("A [1]", _session("other")) == []


def test_a_later_message_without_a_search_cites_nothing() -> None:
    """Review M5: "steps [1] and [2]" in a new turn must not pick up last turn's sources."""
    s = _session("search please")
    c = conversation_of(s)
    c.add("One", "https://s.example/1")
    c.add("Two", "https://s.example/2")
    s.append(Turn(role=Role.ASSISTANT, content="Found it [1]."))
    s.append(Turn(role=Role.USER, content="Now list the steps"))
    assert cited_sources("Do steps [1] and [2].", s) == []
    c2 = conversation_of(s)
    c2.add("Two again", "https://s.example/2")  # shown again this turn: citable again
    assert [x.n for x in cited_sources("Do steps [1] and [2].", s)] == [2]


def test_list_markers_at_line_start_are_not_citations() -> None:
    s = _session("hi")
    c = conversation_of(s)
    c.add("One", "https://s.example/1")
    c.add("Two", "https://s.example/2")
    assert cited_sources("[1] Buy milk\n  [2] Call mum\n- [1] again", s) == []
    assert [x.n for x in cited_sources("[1] Buy milk, as reported [2]", s)] == [2]
    assert cited_numbers("[1] Buy milk, as reported [2]") == [2]


def test_per_turn_counters_reset_with_each_owner_message() -> None:
    s = _session("first")
    c = conversation_of(s)
    assert c.used("search") == 0
    c.bump("search")
    c.bump("search")
    c.bump("read")
    again = conversation_of(s)  # a later call in the same turn
    assert (again.used("search"), again.used("read")) == (2, 1)
    s.append(Turn(role=Role.USER, content="second"))
    fresh = conversation_of(s)
    assert (fresh.used("search"), fresh.used("read")) == (0, 0)
    assert fresh.sources() == []  # nothing added yet; the counters don't touch the ledger


def test_an_odd_stored_source_never_makes_a_turn_unreadable() -> None:
    odd = {"n": 0, "title": "t" * 5000, "url": "https://x.example/" + "a" * 3000, "domain": ""}
    turn = Turn.model_validate({"role": "assistant", "content": "x", "sources": [odd]})
    assert turn.sources[0].n == 0  # kept as stored; the console re-checks before showing it


# ---- the private-query guard --------------------------------------------------------------------


ZWSP = chr(0x200B)
DEVANAGARI = "".join(chr(0x0966 + int(d)) for d in "9845012345")
MALAYALAM = "".join(chr(0x0D66 + int(d)) for d in "9845012345")
AADHAAR_DEVANAGARI = " ".join(
    "".join(chr(0x0966 + int(d)) for d in g) for g in ("2345", "6789", "0123")
)


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
        # review H1: obfuscated forms
        "john\uff20example.com profile",  # full-width @
        f"john@exa{ZWSP}mple.com profile",
        "john@ example.com",
        "john (at) example (dot) com",
        "john [at] example [dot] com",
        "john at example dot com",
        "john%40example.com",
        "@johnsmith posts",
        f"owner of {DEVANAGARI}",
        f"owner of {MALAYALAM}",
        "owner of \uff19\uff18\uff14\uff15\uff10\uff11\uff12\uff13\uff14\uff15",
        f"owner of 98450{ZWSP}12345",
        "owner of 98450/12345",
        "owner of 98 45 01 23 45",
        "tel9845012345",
        f"aadhaar {AADHAAR_DEVANAGARI}",
        "A B C D E 1 2 3 4 F status",
        "account 50100 2345 6789",
    ],
)
def test_guard_refuses_queries_with_private_identifiers(query: str) -> None:
    reason = query_problem(query)
    assert reason is not None, query
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
        "Kerala budget 2025-2026 highlights",
        "flights 01/12/2026 Kochi to Delhi",
        "meeting tips at work",
        "1,40,00,00,000 rupees in words",
        "what is 22/7 as a decimal",
    ],
)
def test_guard_lets_ordinary_queries_through(query: str) -> None:
    assert query_problem(query) is None, query
