# tests/test_r11_1_i1_overcaution.py -- R11.1 I1, the over-caution check (orchestrator item
# 21): on a picture turn the turn guard refused ordinary web queries ("monsoon weather forecast").
# Measured on 35 ordinary queries and 26 person-name queries (every person made up), the owner
# having typed only "what is this?": before the tuning 23 of the 35 ordinary queries were refused
# and none of the 26 person-name queries went out; after it 5 of the 35 are refused (two
# capitalised words in a row, exactly a name's shape: they go ahead as soon as the picture shows
# them or he types them) and still none of the 26 goes out.
#
# I1 reviews (security H1, M2, M3; code M3): the light check let other scripts, links, `_`, a
# lone name beside a search word and a lower-case name beside a thing word through (36 of the 55
# probes below). Now the guard is STRICT whenever the picture may show a person (only his words,
# the picture's and free words go out: 0 of 55 and 0 of 26 go out; 30 of the 35 ordinary queries
# wait for his words), and LIGHT only when it is known to show nobody (still 5 of 35; 4 of the 55
# go out there, named below). The probes are the reviewers' own strings: the mononyms (Modi,
# Kohli, Shahrukh, Rahul Gandhi) are public figures' names in search queries; everyone else is
# made up.
from __future__ import annotations

import pytest

from jarvis.picture.turnguard import ALLOWED, STRICT, WEB_REFUSED, Refused, check_query

TYPED = "what is this?"
ORDINARY = [
    "monsoon weather forecast", "Kerala monsoon forecast", "weather in Mumbai today",
    "flights to Delhi tomorrow", "price of iPhone 16", "best biryani recipe",
    "how to clean a copper kettle", "Diwali 2026 date", "petrol price in Bengaluru",
    "gold rate today", "train from Chennai to Madurai", "cricket score", "Kochi metro timings",
    "New Delhi air quality", "rainfall in Kerala this week", "how to make masala chai",
    "stock market news", "exchange rate dollar to rupee", "Onam festival dishes",
    "Sabarimala temple timings", "Bengaluru traffic update", "symptoms of dengue",
    "nearest hospital open now", "Lalbagh flower show dates", "is it safe to drink",
    "plastic recycling rules", "air fryer reviews", "Weather Mumbai", "paint for a plain wall",
    "Mumbai Weather Today",
]  # fmt: skip
# two capitalised words in a row: a name's very shape, so refused unless shown or typed
SHAPED_LIKE_A_NAME = [
    "Taj Mahal opening hours", "Mumbai Pune expressway traffic", "Google Pixel 9 review",
    "Thrissur Pooram 2026", "Mount Everest height",
]  # fmt: skip
PERSON = [
    "Meenu Examplewala", "Meenu Examplewala actress", "Meenu Examplewala biography",
    "MEENU EXAMPLEWALA", "who is Meenu Examplewala", "Rajesh Examplekar minister",
    "Lekha Examplekar Instagram", "Arjun Testwala family", "Priya Sampleton net worth",
    "Kavya Demoraj husband", "Dr Ravi Fakename", "R K Examplekar", "meenu examplewala",
    "rajesh examplekar contact number", "Sita Placeholder age", "news about Arjun Testwala",
    "Arjun Testwala wife name", "the woman in the red saree", "actress with short hair",
    "bearded man in blue shirt", "photos of Lekha Examplekar", "Lekha Examplekar Kerala",
    "Is this Lekha Examplekar", "Testwala", "Anil Gates", "lekha examplekar latest news",
]  # fmt: skip


def test_the_sets_are_big_enough_to_mean_something() -> None:
    assert len(ORDINARY) + len(SHAPED_LIKE_A_NAME) >= 20 and len(PERSON) >= 20


@pytest.mark.parametrize("query", ORDINARY)
def test_an_ordinary_query_goes_ahead_on_a_picture_turn(query: str) -> None:
    assert check_query(query, TYPED, ()) == ALLOWED


@pytest.mark.parametrize("query", PERSON)
def test_a_person_name_query_he_did_not_type_never_goes_out(query: str) -> None:
    assert check_query(query, TYPED, ()) == Refused(WEB_REFUSED)


@pytest.mark.parametrize("query", SHAPED_LIKE_A_NAME)
def test_a_two_word_proper_name_goes_ahead_once_shown_or_typed(query: str) -> None:
    assert check_query(query, TYPED, ()) == Refused(WEB_REFUSED)  # the remaining over-caution
    name = " ".join(w for w in query.split() if w[:1].isupper())
    assert check_query(query, TYPED, (name,)) == ALLOWED  # the picture shows it
    assert check_query(query, f"tell me about {name.lower()}", ()) == ALLOWED  # he typed it


# ---- the I1 reviews' probes (security H1, M3; code M3), plus other scripts, links and `_` -------
EXTENDED = [
    # security H1: other scripts, links, `_`
    "लेखा एक्झाम्पलकर", "लेखा एक्झाम्पलकर मंत्री", "ലേഖ എക്സാമ്പിൾകർ",
    "https://en.wikipedia.org/wiki/Lekha_Examplekar", "rajesh_examplekar",
    "site:wikipedia.org lekha_examplekar",
    # security M3: a lone name beside a search word, a lower-case name beside a thing word, split
    "Modi news today", "modi news", "Kohli score", "Shahrukh latest news",
    "narendra modi car", "lekha examplekar phone number", "lekha examplekar phone",
    "Lekha weather", "Examplekar news",
    "lekha examplekar", "Rahul Gandhi news", "Narendra Modi latest", "Lekha-Examplekar",
    "Lekha. Examplekar", "L. K. Examplekar biography", "Dr. Lekha Examplekar",
    "Lekha\u200bExamplekar", "who is Lekha Examplekar",
    # code M3
    "Kohli news", "kohli news", "Modi news", "Modi latest news", "Kohli score today",
    "Examplewala news", "news Lekha", "Lekha news", "Testwala news", "Testwala score",
    "Kohli", "modi speech", "Kohli profile", "Lekha age",
    # the code reviewer's own
    "R K Examplekar", "Dr Lekha Examplekar phone", "Examplekar, Lekha", "Meenu's Instagram",
    # more scripts (Odia, Tamil, Bengali, Malayalam), a mixed one, links and joins
    "ଲେଖା ଏକ୍ଜାମ୍ପଲକର", "லேகா எக்ஸாம்பிள்கர்", "লেখা এক্সাম্পলকর", "ലേഖ എക്സാമ്പിൾകർ മന്ത്രി",
    "Lekha एक्झाम्पलकर", "https://www.instagram.com/lekha.examplekar",
    "linkedin.com/in/lekha-examplekar", "lekha_examplekar instagram", "Lekha_Examplekar",
    "https://en.wikipedia.org/wiki/lekha_examplekar", "site:instagram.com meenu_examplewala",
    "meenu.examplewala", "MEENU_EXAMPLEWALA news",
]  # fmt: skip
# What the LIGHT check (a picture known to show nobody, so no face to take a name from) still
# lets through: a lower-case name beside a thing word, and one name beside a weather word (the
# first half of a split). Strict mode refuses every one; see the I1 notes' residuals.
LIGHT_RESIDUAL = {
    "narendra modi car",
    "lekha examplekar phone number",
    "lekha examplekar phone",
    "Lekha weather",
}
# The ordinary queries strict mode lets through with nothing typed or shown: only free words.
STRICT_GOES_AHEAD = {
    "monsoon weather forecast",
    "cricket score",
    "stock market news",
    "nearest hospital open now",
    "is it safe to drink",
}


def test_the_extended_set_covers_both_reviews_and_every_form() -> None:
    assert len(EXTENDED) >= 50 and LIGHT_RESIDUAL <= set(EXTENDED)
    assert any(not q.isascii() for q in EXTENDED) and any("/" in q for q in EXTENDED)
    assert any("_" in q for q in EXTENDED)


@pytest.mark.parametrize("query", EXTENDED + PERSON)
def test_on_a_picture_that_may_show_a_person_no_probe_ever_goes_out(query: str) -> None:
    assert check_query(query, TYPED, (), STRICT) == Refused(WEB_REFUSED)


@pytest.mark.parametrize("query", sorted(set(EXTENDED) - LIGHT_RESIDUAL))
def test_on_a_picture_known_to_show_nobody_the_light_check_holds_the_probes(query: str) -> None:
    assert check_query(query, TYPED, ()) == Refused(WEB_REFUSED)


def test_the_light_check_lets_through_exactly_its_named_residuals() -> None:
    through = {q for q in EXTENDED if check_query(q, TYPED, ()) == ALLOWED}
    assert through == LIGHT_RESIDUAL


def test_a_name_split_across_two_queries_goes_out_in_neither_half_in_strict_mode() -> None:
    for half in ("Lekha weather", "Examplekar news", "lekha", "examplekar latest"):
        assert check_query(half, TYPED, (), STRICT) == Refused(WEB_REFUSED)


def test_strict_mode_holds_ordinary_queries_until_his_words_or_the_picture_carry_them() -> None:
    ordinary = ORDINARY + SHAPED_LIKE_A_NAME
    ahead = {q for q in ordinary if check_query(q, TYPED, (), STRICT) == ALLOWED}
    assert ahead == STRICT_GOES_AHEAD  # 30 of 35 wait: the accepted rise on person pictures
    for query in ordinary:
        assert check_query(query, f"what is this? {query}", (), STRICT) == ALLOWED  # typed
        assert check_query(query, TYPED, (query,), STRICT) == ALLOWED  # the picture shows it


def test_the_light_check_still_refuses_only_the_five_two_capital_queries() -> None:
    refused = {q for q in ORDINARY + SHAPED_LIKE_A_NAME if check_query(q, TYPED, ()) != ALLOWED}
    assert refused == set(SHAPED_LIKE_A_NAME)


@pytest.mark.parametrize(
    ("query", "typed"),
    [
        ("लेखा एक्झाम्पलकर", "लेखा एक्झाम्पलकर कोण आहे?"),  # his own words, in his own script
        ("ലേഖ എക്സാമ്പിൾകർ", "ലേഖ എക്സാമ്പിൾകർ ആരാണ്?"),
        ("Lekha_Examplekar", "who is Lekha Examplekar?"),
        ("lekha examplekar phone", "what phone does lekha examplekar use?"),
    ],
)
def test_a_name_he_typed_goes_ahead_in_either_mode_in_any_script(query: str, typed: str) -> None:
    assert check_query(query, typed, ()) == ALLOWED
    assert check_query(query, typed, (), STRICT) == ALLOWED
