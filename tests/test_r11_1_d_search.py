# tests/test_r11_1_d_search.py -- R11.1 Part D, O9 (plan D17): the web search behind picture
# research (`jarvis.picture.search.WebFinder`) keeps every rule a typed `web_search` keeps. Inside
# a conversation its sources are numbered by that conversation's ledger (a reply's [n] becomes a
# source chip) and the search counts against the message's and the hour's caps, which it SHARES
# with `web_search`; with no gateway there is no governed path, so nothing is searched; pages
# that are a person's own are never kept; and what comes back unusable is said plainly.
from __future__ import annotations

from r11_1_fakes_d import UID, PictureRig, picture

from jarvis.core.models import Session, Turn
from jarvis.llm.base import Role
from jarvis.picture.search import (
    HOUR_LIMIT,
    MAX_RESULTS,
    NOTHING_FOUND,
    ROWS_UNREADABLE,
    TURN_LIMIT,
    WebFinder,
    about_a_person,
)
from jarvis.web.ledger import web_conversation
from jarvis.web.ports import SearchHit
from jarvis.web.tools import MAX_SEARCHES_PER_HOUR, MAX_SEARCHES_PER_TURN

THING = "Charminar monument"
RED = ((60, 60, 220, 170), (200, 40, 40))


def _rig() -> PictureRig:
    rig = PictureRig()
    pic = picture(blocks=[RED])
    rig.eyes.knows(pic, scene="A stone monument with four towers.", subjects=[("landmark", THING)])
    rig.turn.attach("sess_1", pic)
    return rig


def _session() -> Session:
    session = Session(user_id=UID)
    session.append(Turn(role=Role.USER, content="What is this building?"))
    return session


# ---- inside a conversation -----------------------------------------------------------------------
async def test_in_a_conversation_the_sources_take_its_numbers_and_the_search_is_counted() -> None:
    rig = _rig()
    with web_conversation(_session()) as conv:
        earlier = conv.add("An earlier page", "https://example.net/earlier")  # a web_search before
        out = (await rig.research()).result

        numbers = [r["n"] for r in out["results"]]
        assert earlier == 1 and numbers == [2, 3]  # they continue the conversation's numbering
        assert [conv.url_of(n) for n in numbers] == [
            "https://www.example.org/a",
            "https://example.com/b",
        ]
        assert conv.used("search") == 1
    assert rig.web is not None and rig.web.searches_last_hour(UID) == 1


async def test_the_messages_search_cap_is_shared_with_web_search() -> None:
    rig = _rig()
    with web_conversation(_session()) as conv:
        for _ in range(MAX_SEARCHES_PER_TURN):
            conv.bump("search")  # the message's typed web searches

        out = (await rig.research()).result

        assert conv.used("search") == MAX_SEARCHES_PER_TURN  # not counted again
    assert rig.vendor.queries == []
    assert out["status"] == "done" and out["results"] == [] and out["searched"] == [TURN_LIMIT]
    assert "four towers" in out["scene"]  # the picture is still described


async def test_the_hourly_search_cap_is_shared_with_web_search() -> None:
    rig = _rig()
    assert rig.web is not None
    for _ in range(MAX_SEARCHES_PER_HOUR):
        rig.web.count_search(UID)

    out = (await rig.research()).result

    assert rig.vendor.queries == [] and out["searched"] == [HOUR_LIMIT]
    assert rig.web.searches_last_hour(UID) == MAX_SEARCHES_PER_HOUR


# ---- no governed path, no search -----------------------------------------------------------------
async def test_without_a_gateway_nothing_is_searched() -> None:
    rig = _rig()
    finder = WebFinder(lambda: rig.web, lambda: None)

    found = await finder.find(UID, THING)

    assert (found.status, found.note, found.sources) == ("not_allowed", ROWS_UNREADABLE, ())
    assert rig.vendor.queries == []


# ---- what is kept of the results -----------------------------------------------------------------
def test_a_page_on_a_personal_social_site_is_about_a_person() -> None:
    assert about_a_person(SearchHit("A reel", "https://www.instagram.com/reel/Cx0000000", ""))
    assert about_a_person(SearchHit("A post", "https://www.facebook.com/photo/?fbid=1", ""))
    assert not about_a_person(SearchHit("Charminar", "https://www.example.org/charminar", "A fort"))


async def test_pages_that_are_not_plain_https_are_never_kept_and_it_says_so() -> None:
    rig = _rig()
    rig.vendor.default = [
        SearchHit("Plain http", "http://example.org/a", "x"),
        SearchHit("A file", "ftp://example.org/b", "x"),
        SearchHit("With a login", "https://user:pw@example.org/c", "x"),
    ]

    out = (await rig.research()).result

    assert rig.vendor.queries == [THING]
    assert out["results"] == [] and out["searched"] == [NOTHING_FOUND]


async def test_the_same_page_twice_is_one_source_and_at_most_three_are_kept() -> None:
    rig = _rig()
    rig.vendor.default = [
        SearchHit("One", "https://example.org/a", "x"),
        SearchHit("One again", "https://example.org/a#top", "x"),
        SearchHit("Two", "https://example.org/b", "x"),
        SearchHit("Three", "https://example.org/c", "x"),
        SearchHit("Four", "https://example.org/d", "x"),
    ]

    out = (await rig.research()).result

    report = rig.svc.last(UID, "sess_1")
    assert report is not None
    urls = [s.url for f in report.findings for s in f.sources]
    assert len(urls) == len(set(urls)) == len(out["results"]) == MAX_RESULTS
    assert urls[0] == "https://example.org/a"
