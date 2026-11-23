# tests/test_r63_serve.py -- R6.3 I0 seam 10 (docs/plans/r6-3-book-content.md D9, plan review H1):
# the show script's joins to part D's `buildbook/tour_serve.py`. `ShowScript.build` asks D's
# `tour_lines(book, audience, words)` (I0's stub: None -> `kind: "show"`, today's script exactly);
# a tour answer is served as `kind: "tour"` with its scenes and seconds, and a guest's tour carries
# no Rs anywhere (no costs). `ShowScript.line_text(uid, line_id, audience)` hands a `tNNbMM` id with
# the SESSION'S audience to D's `tour_line_text` (stub: None), so a guest's speak of an owner-only
# tour line is 404 `unknown_line`, the same as a made-up id (H1: through the real route).
from __future__ import annotations

from typing import Any

import pytest
from book_app_fakes import book, book_app, open_book, register_passkey, sign_in
from book_show_fakes import Clock, FixtureSource

from jarvis.buildbook import show_script, tour_serve
from jarvis.config import Settings

TOUR = {
    "scenes": [
        {
            "n": 1,
            "id": "what",
            "title": "What JARVIS is",
            "picture": {"visual": 1, "facts": []},
            "chapter": "",
            "audience": "both",
            "beats": [{"id": "t01b01", "text": "Welcome.", "focus": ""}],
        }
    ],
    "seconds": 790.0,
}


def test_the_stubs_answer_none() -> None:
    assert tour_serve.tour_lines(object(), "owner", {}) is None  # type: ignore[arg-type]
    assert tour_serve.tour_line_text(object(), "t01b01", "guest") is None  # type: ignore[arg-type]
    assert tour_serve.TOUR_LINE.fullmatch("t13b03") and not tour_serve.TOUR_LINE.fullmatch("s01b01")


async def test_with_no_tour_the_script_is_todays_show_with_kind_show(settings: Settings) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            app.state.book_clock = Clock()
            auth = await register_passkey(c)
            h = book((await open_book(c, auth, "owner"))["token"])
            got = (await c.get("/v1/book/show/script", headers=h)).json()
    assert got["kind"] == "show" and [s["n"] for s in got["scenes"]] == list(range(1, 12))
    assert "seconds" not in got


@pytest.mark.parametrize("audience", ["owner", "guest"])
async def test_a_tour_answer_is_served_as_kind_tour_and_a_guests_has_no_costs(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, audience: str
) -> None:
    asked: list[str] = []

    def lines(book_: Any, who: str, words: dict[str, str]) -> dict[str, Any]:
        asked.append(who)
        assert set(words) >= {"h", "his", "by"}
        return TOUR

    monkeypatch.setattr(tour_serve, "tour_lines", lines)
    async for app in book_app(settings):
        async with sign_in(app) as c:
            app.state.book_clock = Clock()
            auth = await register_passkey(c)
            h = book((await open_book(c, auth, audience))["token"])
            got = (await c.get("/v1/book/show/script", headers=h)).json()
    assert asked == [audience] and got["kind"] == "tour" and got["scenes"] == TOUR["scenes"]
    assert got["seconds"] == 790.0
    if audience == "guest":
        assert got["costs"] == {}  # D9: no Rs anywhere in a guest's tour
    else:
        assert got["costs"]  # the owner's tour keeps the book's prices (T16 is his)


async def test_a_tour_line_is_read_for_the_sessions_audience_only(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []
    owner_only = {"t13b03", "t16b01"}

    def text(book_: Any, line_id: str, audience: str) -> str | None:
        seen.append((line_id, audience))
        if line_id in owner_only and audience != "owner":
            return None
        return "A tour line."

    monkeypatch.setattr(tour_serve, "tour_line_text", text)
    async for app in book_app(settings):
        async with sign_in(app) as c:
            app.state.book_clock = Clock()
            auth = await register_passkey(c)
            guest = book((await open_book(c, auth, "guest"))["token"])
            for line in sorted(owner_only):
                r = await c.post("/v1/book/show/speak", json={"line_id": line}, headers=guest)
                assert r.status_code == 404 and r.json()["error"] == "unknown_line", line
            r = await c.post("/v1/book/show/speak", json={"line_id": "t01b01"}, headers=guest)
            assert r.status_code == 503 and r.json()["error"] == "voice_unavailable"  # served
    assert seen == [("t13b03", "guest"), ("t16b01", "guest"), ("t01b01", "guest")]


async def test_the_owners_audience_reaches_the_tour_too(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        tour_serve,
        "tour_line_text",
        lambda b, i, a: seen.append(a) or "Line.",  # type: ignore[func-returns-value]
    )
    async for app in book_app(settings):
        async with sign_in(app) as c:
            app.state.book_clock = Clock()
            auth = await register_passkey(c)
            owner = book((await open_book(c, auth, "owner"))["token"])
            await c.post("/v1/book/show/speak", json={"line_id": "t16b01"}, headers=owner)
    assert seen == ["owner"]


async def test_a_show_line_and_a_fixed_line_still_read_as_before() -> None:
    script = show_script.ShowScript(FixtureSource(), honorific="Sir")
    for audience in ("owner", "guest"):
        assert (
            await script.line_text("u1", "s02b02", audience) == "The core loop sits in layer four."
        )
        assert await script.line_text("u1", "thanks_owner", audience) == "Thank you, Sir."
        assert await script.line_text("u1", "s99b99", audience) is None
        assert await script.line_text("u1", "t01b01", audience) is None  # no tour: unknown
