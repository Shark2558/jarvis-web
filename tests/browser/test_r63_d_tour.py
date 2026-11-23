# tests/browser/test_r63_d_tour.py -- R6.3 part D (docs/plans/r6-3-book-content.md D9, D14; the
# `tour` suite): the short tour in today's player (/book/show), against the show's routes stubbed
# by book_mocks.FakeBook serving THIS branch's filled tour (tour_serve.tour_lines over the
# generator's output). The owner's tour plays all 17 scenes, Questions and Closing in 2D, in 3D
# (WebGL2 only, the Book's _need_3d rule) and under Motion Off, with the browser's voice (stubbed);
# each scene draws today's picture with its own data; the chapters menu names, for the owner, his
# own scene and each scene's full-book chapter; "continue" restarts the remembered scene of the
# same release for the owner only; a guest's tour has no T16, no owner-only line and no Rs; an
# older book plays today's 11 scenes. Screenshots (not committed) when R63_D_SHOTS names a folder.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from book_mocks import SCENES, SPEECH_STUB, TOKEN, FakeBook, script
from r63_fakes_d import OLD_BOOK, built, with_tour
from test_console import PHONE, Console

from jarvis.buildbook import tour_serve

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

LAPTOP = {"width": 1280, "height": 800}
SHOTS = os.environ.get("R63_D_SHOTS", "")
WORDS = {"h": "Sir", "his": "his", "by": "the Workshop, my owner"}
RUPEE = re.compile(r"₹|\bRs\b|rupee", re.IGNORECASE)
TOUR = built()
assert TOUR is not None
BOOK = with_tour(OLD_BOOK, TOUR)
REL = {
    "id": "3f2a1c9",
    "label": "R6.3",
    "version": "v6.3.0",
    "committed_at": "2026-11-24T09:00:00+05:30",
}
PLACE = "jarvis_book_place_v1"
SEED = """
if (!sessionStorage.getItem('__seeded')) {
  sessionStorage.setItem('__seeded', '1');
  sessionStorage.setItem('jarvis_book_token', '%s');
  sessionStorage.setItem('jarvis_book_session', JSON.stringify({ audience: '%s', session_id: 'bk_0123456789abcdef' }));
}
"""
STATE = "() => window.JarvisBookShow && window.JarvisBookShow.state()"


def served(audience: str, *, quick: bool = False) -> list[dict[str, Any]]:
    got = tour_serve.tour_lines(BOOK, audience, WORDS)  # type: ignore[arg-type]
    assert got is not None
    if not quick:
        return list(got["scenes"])
    return [
        {**s, "beats": [{**b, "text": " ".join(b["text"].split()[:2])} for b in s["beats"]]}
        for s in got["scenes"]
    ]


def tour_script(
    audience: str, *, quick: bool = False, release: dict[str, Any] = REL
) -> dict[str, Any]:
    body = script(audience, served(audience, quick=quick), voice="browser", listening="browser")
    seconds = (TOUR.owner if audience == "owner" else TOUR.guest).seconds
    return {**body, "kind": "tour", "seconds": seconds, "release": release}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(
    browser: Any,
    url: str,
    token: str,
    *,
    audience: str = "owner",
    viewport: dict[str, int] = PHONE,
    body: dict[str, Any] | None = None,
    motion: str = "",
    ctx: Any = None,
) -> tuple[Console, FakeBook]:
    c = Console(browser, url, token, viewport)
    if ctx is not None:  # the same browser profile again (its localStorage): a reopened show
        c.ctx.close()
        c.ctx, c.page = ctx, ctx.new_page()
        c.page.on("pageerror", lambda e: c.errors.append(f"pageerror: {e}"))
    if motion:
        c.page.add_init_script(
            f"try {{ localStorage.setItem('jarvis_motion', '{motion}'); }} catch (_) {{}}"
        )
    c.page.add_init_script(SPEECH_STUB)
    c.page.add_init_script(SEED % (TOKEN, audience))
    fake = FakeBook(c.page)
    fake.script_answer = (200, body if body is not None else tour_script(audience, quick=True))
    c.page.goto(url + "/book/show")
    c.page.locator("#shBegin").wait_for()
    return c, fake


def _state(c: Console) -> dict[str, Any]:
    return dict(c.page.evaluate(STATE))


def _begin(c: Console, *, paused: bool = False) -> None:
    c.page.locator("#shBegin").click()
    c.page.wait_for_function("() => window.JarvisBookShow.state().playing")
    if paused:
        c.page.locator("#shPlay").click()
        c.page.wait_for_function("() => !window.JarvisBookShow.state().playing")


def _chapters(c: Console) -> list[str]:
    c.page.locator("#shChapters").click()
    items = c.page.locator("#shChapterItems button").all_text_contents()
    c.page.locator("#shChapClose").click()
    return items


def _goto(c: Console, n: int) -> None:
    c.page.locator("#shChapters").click()
    c.page.locator("#shChapterItems button", has_text=f"{n:02d} ·").first.click()
    c.page.wait_for_function(f"() => window.JarvisBookShow.state().scene === {n}")


def _spoken(c: Console) -> list[str]:
    return list(c.page.evaluate("window.__spoken"))


def _clean(c: Console) -> None:
    assert [e for e in c.errors if "pageerror" in e] == [] and c.csp_violations() == []


def _need_3d(c: Console) -> None:
    if _state(c)["renderer"] == "3d":
        return
    st = c.page.evaluate("window.JarvisBook3D ? window.JarvisBook3D.stats() : {state: 'missing'}")
    assert st["state"] == "no-webgl2", st
    pytest.skip("this Chromium has no WebGL2: the 2D tour is covered elsewhere")


def _play_to_the_end(c: Console, audience: str) -> None:
    """Plays every line to Questions, then the closing, as a viewer would; the page then clears."""
    c.page.locator("#shTalk").wait_for(state="visible", timeout=60000)
    beats = [b["text"] for s in served(audience, quick=True) for b in s["beats"]]
    assert _spoken(c)[: len(beats)] == beats
    assert _state(c)["phase"] == "questions"
    c.page.evaluate("() => window.JarvisBookShow.toClosing()")
    c.page.wait_for_function("() => window.JarvisBookShow.state().phase === 'done'", timeout=30000)


def _facts_seen(c: Console, renderer: str) -> str:
    sel = "#sh2d .sh2-scene" if renderer == "2d" else "#shLabels"
    return c.page.locator(sel).text_content() or ""


def _draws_its_own(c: Console, scene: dict[str, Any], renderer: str) -> bool:
    text = _facts_seen(c, renderer)
    labels = [f["label"][:14] or f["value"][:14] for f in scene["picture"]["facts"]]
    return any(lab and lab in text for lab in labels)


def test_the_owners_tour_plays_all_17_scenes_questions_and_closing_in_2d(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token)
    try:
        assert _state(c)["renderer"] == "2d"
        assert "R6.3" in c.page.locator("#shStart").inner_text()
        _begin(c)
        _play_to_the_end(c, "owner")
        assert fake.to("POST", "/v1/book/show/speak") == []  # the browser's voice: Rs 0
        assert fake.to("POST", "/v1/book/close")
        _clean(c)
    finally:
        c.close()


def test_the_tour_plays_in_3d(browser: Any, server_url: str, token: str) -> None:
    c, _ = _open(browser, server_url, token, viewport=LAPTOP)
    try:
        _need_3d(c)
        _begin(c)
        _play_to_the_end(c, "owner")
        _clean(c)
    finally:
        c.close()


def test_the_tour_plays_under_motion_off(browser: Any, server_url: str, token: str) -> None:
    c, _ = _open(browser, server_url, token, viewport=LAPTOP, motion="off")
    try:
        _begin(c)
        assert _state(c)["motion"] == "off"
        _play_to_the_end(c, "owner")
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("viewport", [PHONE, LAPTOP], ids=["phone", "laptop"])
def test_each_scene_draws_todays_picture_with_its_own_data(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    """Every scene whose picture differs from the scene before it (always redrawn)."""
    c, _ = _open(browser, server_url, token, viewport=viewport)
    try:
        _begin(c, paused=True)
        renderer, scenes, before = _state(c)["renderer"], served("owner", quick=True), 0
        for scene in scenes:
            _goto(c, scene["n"])
            visual = scene["picture"]["visual"]
            if renderer == "2d":
                got = c.page.locator("#sh2d .sh2-scene").get_attribute("data-scene")
                assert got == str(visual), scene["n"]
            if visual != before:
                assert _draws_its_own(c, scene, renderer), (
                    scene["n"],
                    _facts_seen(c, renderer)[:200],
                )
            before = visual
            if SHOTS:
                c.page.wait_for_timeout(900)  # the card's entry animation
                Path(SHOTS).mkdir(parents=True, exist_ok=True)
                name = "phone" if viewport is PHONE else "laptop"
                c.page.screenshot(
                    path=str(Path(SHOTS) / f"{name}-{scene['n']:02d}-{scene['id']}.png")
                )
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("viewport", [PHONE, LAPTOP], ids=["phone", "laptop"])
def test_a_scene_after_one_with_the_same_picture_draws_its_own_data(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    c, _ = _open(browser, server_url, token, viewport=viewport)
    try:
        _begin(c, paused=True)
        renderer, scenes = _state(c)["renderer"], {s["n"]: s for s in served("owner", quick=True)}
        for n in (12, 13, 14, 15):
            _goto(c, n)
            assert _draws_its_own(c, scenes[n], renderer), (n, _facts_seen(c, renderer)[:200])
    finally:
        c.close()


def test_the_owners_chapters_name_his_scene_and_the_full_book(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _open(browser, server_url, token)
    try:
        _begin(c, paused=True)
        items = _chapters(c)
        assert len(items) == 19 and items[-2:] == ["18 · Questions", "19 · Closing"]
        assert items[6] == "07 · Highlight 1 of 7: Voice · Full book: Voice"
        assert (
            items[12] == "13 · Highlight 7 of 7: Wardrobe & Try-on · Full book: Wardrobe & Try-on"
        )
        assert items[15] == "16 · What I cost · You only · Full book: Costs"
        assert items[13] == "14 · What else I can do"  # no single chapter: the title alone
        _clean(c)
    finally:
        c.close()


def test_a_guests_tour_has_no_t16_no_owner_line_no_rupee_and_is_never_remembered(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _open(browser, server_url, token, audience="guest")
    try:
        _begin(c, paused=True)
        items = _chapters(c)
        assert len(items) == 18 and not any("What I cost" in i for i in items)
        assert not any("You only" in i or "Full book" in i for i in items)
        c.page.locator("#shPlay").click()  # play on to the end
        _play_to_the_end(c, "guest")
        said = " ".join(_spoken(c))
        assert not RUPEE.search(said)
        assert c.page.evaluate(f"localStorage.getItem('{PLACE}')") is None
        _clean(c)
    finally:
        c.close()


def test_continue_restarts_the_remembered_scene_for_the_owner(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _open(browser, server_url, token)
    ctx = c.ctx
    try:
        _begin(c, paused=True)
        _goto(c, 7)
        c.page.keyboard.press("ArrowRight")  # the middle of the scene: its second line
        place = c.page.evaluate(f"JSON.parse(localStorage.getItem('{PLACE}'))")
        assert place == {"release": REL["id"], "scene": 7}
        c.page.close()
        again, _ = _open(browser, server_url, token, ctx=ctx)
        again.page.locator("#shBegin").click()
        again.page.wait_for_function("() => window.JarvisBookShow.state().scene === 7")
        first7 = next(s for s in served("owner", quick=True) if s["n"] == 7)["beats"][0]["text"]
        assert _spoken(again)[0] == first7  # the scene from its first line, never mid-line
        again.page.close()
        other, _ = _open(
            browser,
            server_url,
            token,
            ctx=ctx,
            body=tour_script("owner", quick=True, release={**REL, "id": "aebff3a"}),
        )
        other.page.locator("#shBegin").click()
        other.page.wait_for_function("() => window.JarvisBookShow.state().playing")
        assert _state(other)["scene"] == 1  # another release: from the start
    finally:
        ctx.close()


def test_reaching_questions_forgets_the_scene_but_keeps_the_readers_page(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _open(browser, server_url, token)
    try:
        c.page.evaluate(
            f"localStorage.setItem('{PLACE}', JSON.stringify({{release: '{REL['id']}', page: 'pg_module_voice'}}))"
        )
        _begin(c)
        c.page.locator("#shTalk").wait_for(state="visible", timeout=60000)
        place = c.page.evaluate(f"JSON.parse(localStorage.getItem('{PLACE}'))")
        assert place == {"release": REL["id"], "page": "pg_module_voice"}
    finally:
        c.close()


def test_playing_the_tour_leaves_another_releases_reader_place_alone(
    browser: Any, server_url: str, token: str
) -> None:
    """I1 (INTEGRATION-C 5.4): the tour keeps the reader's rule from its side; the reader's
    place of an older release stays exactly as the reader wrote it."""
    c, _ = _open(browser, server_url, token)
    try:
        c.page.evaluate(
            f"localStorage.setItem('{PLACE}', JSON.stringify({{release: 'aebff3a', page: 'pg_module_voice'}}))"
        )
        _begin(c, paused=True)
        _goto(c, 7)
        place = c.page.evaluate(f"JSON.parse(localStorage.getItem('{PLACE}'))")
        assert place == {"release": "aebff3a", "page": "pg_module_voice"}
    finally:
        c.close()


def test_an_older_book_plays_todays_11_scenes_without_the_tours_hooks(
    browser: Any, server_url: str, token: str
) -> None:
    quick = [
        {**s, "beats": [{**b, "text": " ".join(b["text"].split()[:2])} for b in s["beats"]]}
        for s in SCENES
    ]
    c, _ = _open(
        browser,
        server_url,
        token,
        body=script("owner", quick, voice="browser", listening="browser"),
    )
    try:
        _begin(c, paused=True)
        items = _chapters(c)
        assert (
            len(items) == 13 and items[-1] == "13 · Closing" and "Full book" not in " ".join(items)
        )
        c.page.locator("#shPlay").click()
        c.page.locator("#shTalk").wait_for(state="visible", timeout=60000)
        assert _spoken(c)[: sum(len(s["beats"]) for s in quick)] == [
            b["text"] for s in quick for b in s["beats"]
        ]
        assert c.page.evaluate(f"localStorage.getItem('{PLACE}')") is None
        _clean(c)
    finally:
        c.close()
