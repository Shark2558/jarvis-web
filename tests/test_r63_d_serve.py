# tests/test_r63_d_serve.py -- R6.3 part D (docs/plans/r6-3-book-content.md D9, D13; plan review
# H1): what the show serves of the short tour. `tour_serve.tour_lines` gives the session's audience
# its own filled tour (`{h}` and its kin filled by the show's words); `tour_line_text` reads a
# `tNNbMM` line ONLY when it belongs to the session's audience, so a guest's speak of an
# owner-only line (t13b03, t16b01) is 404 `unknown_line` through the real route, and every line
# of the session's own tour speaks. An older book has no tour: today's 11-scene show.
from __future__ import annotations

import re
from typing import Any

import pytest
from book_app_fakes import book, book_app, open_book, register_passkey, sign_in
from book_show_fakes import Clock
from r63_fakes_d import OLD_BOOK, TourSource, built, with_tour

from jarvis.buildbook import show_script, tour_serve
from jarvis.config import Settings

WORDS = {"h": "Sir", "his": "his", "by": "the Workshop, my owner"}
RUPEE = re.compile(r"₹|\bRs\b|rupee", re.IGNORECASE)
TOUR = built()
assert TOUR is not None
BOOK = with_tour(OLD_BOOK, TOUR)
OWNER_ONLY = sorted(
    b.id for s in TOUR.owner.scenes for b in s.beats if "owner" in (s.audience, b.audience)
)
GUEST_IDS = [b.id for s in TOUR.guest.scenes for b in s.beats]
OWNER_IDS = [b.id for s in TOUR.owner.scenes for b in s.beats]


def test_the_owner_only_lines_are_t13b03_and_t16b01() -> None:
    assert OWNER_ONLY == ["t13b03", "t16b01"]


def test_an_older_book_has_no_tour_and_plays_todays_show() -> None:
    assert tour_serve.tour_lines(OLD_BOOK, "owner", WORDS) is None
    assert tour_serve.tour_line_text(OLD_BOOK, "t01b01", "owner") is None


@pytest.mark.parametrize("audience", ["owner", "guest"])
def test_tour_lines_serve_the_sessions_own_tour(audience: str) -> None:
    got = tour_serve.tour_lines(BOOK, audience, WORDS)  # type: ignore[arg-type]
    assert got is not None
    mine = TOUR.owner if audience == "owner" else TOUR.guest
    assert got["seconds"] == mine.seconds
    assert [s["n"] for s in got["scenes"]] == [s.n for s in mine.scenes]
    ids = [b["id"] for s in got["scenes"] for b in s["beats"]]
    assert ids == [b.id for s in mine.scenes for b in s.beats]
    first = got["scenes"][0]
    assert set(first) == {"n", "id", "title", "picture", "chapter", "audience", "beats"}
    assert set(first["picture"]) == {"visual", "facts"}


def test_the_owners_t16_line_has_his_honorific_and_a_guests_tour_no_rupee() -> None:
    owner = tour_serve.tour_lines(BOOK, "owner", WORDS)
    assert owner is not None
    t16 = next(s for s in owner["scenes"] if s["n"] == 16)["beats"][0]["text"]
    assert t16.startswith("This scene is for you only, Sir. The bars are my prices in rupees")
    guest = tour_serve.tour_lines(BOOK, "guest", WORDS)
    assert guest is not None and not RUPEE.search(repr(guest))
    assert "{h}" not in repr(owner) and "{h}" not in repr(guest)


def test_tour_line_text_reads_only_the_sessions_audiences_lines() -> None:
    for line in GUEST_IDS:
        assert tour_serve.tour_line_text(BOOK, line, "guest"), line
    for line in OWNER_IDS:
        assert tour_serve.tour_line_text(BOOK, line, "owner"), line
    for line in OWNER_ONLY:
        assert tour_serve.tour_line_text(BOOK, line, "guest") is None, line
    assert tour_serve.tour_line_text(BOOK, "t13b04", "owner") is None  # the guest's own line
    assert tour_serve.tour_line_text(BOOK, "t99b01", "owner") is None
    assert tour_serve.tour_line_text(BOOK, "s01b01", "owner") is None  # a show id: not a tour line


def test_tour_line_text_refuses_an_owner_line_slipped_into_a_guests_scenes() -> None:
    """Defence in depth: even a book whose guest tour were wrong never speaks an owner line."""
    bad_scene = TOUR.owner.scenes[12]  # T13 with its owner-only line
    guest = TOUR.guest.model_construct(
        **{**TOUR.guest.__dict__, "scenes": (*TOUR.guest.scenes[:12], bad_scene)}
    )
    bad = with_tour(OLD_BOOK, TOUR.model_construct(owner=TOUR.owner, guest=guest))
    assert tour_serve.tour_line_text(bad, "t13b03", "guest") is None
    assert tour_serve.tour_line_text(bad, "t13b01", "guest")


async def _speak_all(settings: Settings, audience: str, lines: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    async for app in book_app(settings, source=TourSource(TOUR)):
        async with sign_in(app) as c:
            app.state.book_clock = Clock()
            auth = await register_passkey(c)
            h = book((await open_book(c, auth, audience))["token"])
            for line in lines:
                r = await c.post("/v1/book/show/speak", json={"line_id": line}, headers=h)
                out[line] = (r.status_code, r.json().get("error"))
            out["script"] = (await c.get("/v1/book/show/script", headers=h)).json()
    return out


async def test_a_guests_speak_of_an_owner_only_tour_line_is_404(settings: Settings) -> None:
    got = await _speak_all(settings, "guest", [*OWNER_ONLY, *GUEST_IDS])
    for line in OWNER_ONLY:
        assert got[line] == (404, "unknown_line"), line
    for line in GUEST_IDS:  # found, then the browser's voice (the default): 503, never 404
        assert got[line] == (503, "voice_unavailable"), line
    script = got["script"]
    assert script["kind"] == "tour" and [s["n"] for s in script["scenes"]] == [
        s.n for s in TOUR.guest.scenes
    ]
    assert script["costs"] == {} and not RUPEE.search(repr(script["scenes"]))


async def test_every_line_of_the_owners_tour_speaks_for_the_owner(settings: Settings) -> None:
    got = await _speak_all(settings, "owner", [*OWNER_IDS, "t13b04"])
    for line in OWNER_IDS:
        assert got[line] == (503, "voice_unavailable"), line
    assert got["t13b04"] == (404, "unknown_line")
    assert got["script"]["kind"] == "tour" and len(got["script"]["scenes"]) == 17


async def test_the_owners_spoken_t16_line_has_his_honorific() -> None:
    script = show_script.ShowScript(TourSource(TOUR), honorific="Sir")
    said = await script.line_text("u1", "t16b01", "owner")
    assert said is not None and said.startswith("This scene is for you only, Sir.")
