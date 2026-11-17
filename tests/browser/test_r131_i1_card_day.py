# tests/browser/test_r131_i1_card_day.py -- R13.1 integrated code review H1, end to end: row 388's
# card is read for ITS day and dress code, through the console's real request on the wired app
# (tests/r131_wired_server.py with tonight's 20:00 meeting planned and nothing planned tomorrow).
#   He asks "What should I wear tomorrow? Something formal." in the evening. R13 answers with
#   tomorrow's business formal look (no plan), and the card carries that day and code. The console
#   must ask A's look for exactly those: `day=` tomorrow and `code=` business_formal beside the
#   card's pieces (a covered slot as `slot:`), never today's default. Read for today, every piece
#   tonight's meeting holds reads "Draft: reserved for ..." and the formal shirt is drawn untucked.
# B's real engine (spied, as test_r131_i1_wired does); the page clock 17 Nov 2026, 19:00 IST.
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from r131_wired_server import serve_wired
from test_r131_d_card import browser, call, until
from test_r131_i1_wired import SLOW_S, Wired

__all__ = ["browser"]
pytestmark = pytest.mark.browser
ASK = "What should I wear tomorrow? Something formal."
TOMORROW = "2026-11-18"


@pytest.fixture(scope="module")
def t_url(token: str) -> Iterator[str]:
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    url, stop = serve_wired(token, plan_day="today")
    try:
        yield url
    finally:
        stop()


def _card(url: str, token: str) -> dict[str, Any]:
    reply = call(url, token, "/v1/chat", {"message": ASK})
    [card] = [c for c in reply["cards"] if c["kind"] == "tryon"]
    return dict(card)


def _asked(c: Wired) -> list[dict[str, list[str]]]:
    """Every look the page asked A for by pieces (row 388's card), its query parsed."""
    return [
        parse_qs(urlsplit(r["url"]).query, keep_blank_values=True)
        for r in c.sent
        if r["method"] == "GET" and "/v1/tryon/look?" in r["url"] and "pieces=" in r["url"]
    ]


def test_the_world_has_tonights_plan_and_tomorrows_card_has_no_plan(t_url: str, token: str) -> None:
    card = _card(t_url, token)
    assert card["day"] == TOMORROW and card["plan"] is None and card["code"] == "business_formal"
    outfits = call(t_url, token, "/v1/outfits")
    assert [p["id"][:3] for p in outfits["today"]] == ["op_"]  # tonight's meeting
    assert all(not p["id"].startswith("op_") for p in outfits["tomorrow"])  # nothing planned


@pytest.mark.parametrize("gl", ["", "no-webgl2"], ids=["figure", "checklist"])
def test_tomorrows_card_asks_for_its_own_day_and_code_and_reads_ready_and_tucked(
    browser: Any, t_url: str, token: str, gl: str
) -> None:
    card = _card(t_url, token)
    c = Wired(browser, t_url, token, gl_fail=gl)
    try:
        c.open()
        c.ask(ASK)
        until(c.page, lambda: c.card().count() == 1 and bool(_asked(c)), "the card's look", SLOW_S)
        [q] = _asked(c)
        assert q.get("day") == [TOMORROW] and q.get("code") == ["business_formal"], q
        assert "plan" not in q
        entries = q["pieces"][0].split(",")
        covered = [s["slot"] + ":" for s in card["slots"] if s.get("private")]
        assert covered and all(e in entries for e in covered)  # A reads them covered (AVT-14)
        # what that request answers: tomorrow's look, every piece of it Ready, the shirt tucked
        sent = next(r["url"] for r in c.sent if "/v1/tryon/look?" in r["url"])
        look = call(t_url, token, sent[sent.index("/v1/") :])
        assert look["day"] == TOMORROW and look["dress_code"] == "business_formal"
        assert look["tucked"] is True
        mine = [s for s in look["slots"] if not s.get("private")]
        assert mine and {s["readiness"] for s in mine} == {"Ready"}, mine
        if gl:  # the checklist says it row by row
            until(c.page, lambda: c.card().locator(".tr-item").count() >= len(mine), "the rows")
        else:  # the figure wears the shirt tucked, as a business formal look is worn
            until(c.page, c.drawn, "the card's figure", SLOW_S)
            fig = c.figure()["figures"][0]["look"]["slots"]
            assert [s["variant"] for s in fig if s["slot"] == "top"] == ["tucked"], fig
        shown = c.card().inner_text()
        assert "Draft" not in shown and "reserved" not in shown, shown
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
