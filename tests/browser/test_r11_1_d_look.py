# tests/browser/test_r11_1_d_look.py -- R11.1 Part D in a real browser (plan D0, D16, D17, D19).
# O8: the People panel shows each profile as a card with its own real link; "Open next" opens
# exactly ONE tab a click and marks the card; "Open all" is gone and `window.open` is never
# called. O9: "Research the picture" asks the server for the open conversation's picture and
# shows what came back as text and links; a picture of a person shows the fixed sentence and no
# name. O11: a Vitals row that is being read says "Checking..." on its chip. Every state passes
# the visual gate (ui_checks.DOM_CHECKS_JS and the audit's own probes) at 1440x900 and 390x844,
# Night and Day, with no JS errors and no CSP violations. Everybody named here is made up.
# ruff: noqa: E501 -- JavaScript strings and selectors
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, MOCK_VITALS, install_mocks

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright, expect = _pw.sync_playwright, _pw.expect
pytestmark = pytest.mark.browser

VIEWPORTS = {"desktop": DESKTOP, "phone": PHONE}
PROFILES = [
    (
        "linkedin",
        "https://www.linkedin.com/in/example-person-0001",
        "Lekha Examplekar - Minister for Ports",
    ),
    (
        "wikipedia",
        "https://en.wikipedia.org/wiki/Lekha_Examplekar",
        "Lekha Examplekar - an example article",
    ),
    ("x", "https://x.com/example_person_0001", "@example_person_0001"),
]
DOSSIER: dict[str, Any] = {
    "dossier": {
        "name": "Lekha Examplekar",
        "context": "Minister for Ports",
        "profiles": [{"platform": p, "url": u, "title": t} for p, u, t in PROFILES],
        "findings": [
            {
                "title": "Ports",
                "domain": "ports.example.org",
                "snippet": "Lekha Examplekar, the minister for ports, opened the new harbour bridge.",
            },
            {
                "title": "Profile",
                "domain": "en.wikipedia.org",
                "snippet": "A made-up public figure used in JARVIS's tests; minister since 2024.",
            },
        ],
        "summary": "A made-up minister for ports, in office since 2024.",
        "spoken": "Lekha Examplekar is a made-up minister for ports.",
        "ambiguous": False,
        "no_ai": False,
        "note": "",
        "subject": "public_figure",
        "cost_usd": 0.0,
    }
}
COUNT_OPENS = "window.__opens = 0; window.open = function () { window.__opens += 1; return null; };"


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _json(route: Any, body: Any, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def boot(
    browser: Any,
    url: str,
    token: str,
    vp: dict[str, int],
    *,
    day: bool = False,
    routes: dict[str, Any] | None = None,
    clock: bool = False,
) -> Console:
    """A signed-in console with the shared mocks; `routes` (pattern -> handler) are set before the
    page loads, so the very first read of a panel already gets them. `clock`: the page's timers
    and Date are Playwright's, so a test can jump them forward (time still flows on its own)."""
    c = Console(browser, url, token, vp)
    if clock:
        c.page.clock.install()
    install_mocks(c.page)
    c.page.route("**/v1/people/last", lambda r: _json(r, DOSSIER))
    for pattern, handler in (routes or {}).items():
        c.page.route(pattern, handler)
    # a profile's own site is never loaded in a test: any outside page is an empty stand-in
    c.ctx.route(
        "https://**/*",
        lambda r: r.fulfill(status=200, content_type="text/html", body="<title>profile</title>"),
    )
    c.page.add_init_script(COUNT_OPENS)
    c.open()
    if day:
        c.page.locator("#themeBtn").click()
        c.page.locator('label[for="jx-s-day"]').click()
        c.page.keyboard.press("Escape")
    # the R11.1 modules load last (console-r111.js imports them): their block is there once built
    c.page.locator("#look").wait_for(state="attached")
    return c


def people(c: Console) -> None:
    c.open_panel("people")
    c.page.locator("#peopleCard .pname").wait_for()
    c.page.wait_for_timeout(400)


def gate(c: Console, sel: str, vp: str, what: str) -> None:
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), f"{what}: {sel} is not in the page"
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)
    assert c.csp_violations() == [] and c.errors == [], what


# ---- O8: profile cards ---------------------------------------------------------------------------
def test_each_profile_is_a_card_with_its_own_real_link(
    browser: Any, server_url: str, token: str
) -> None:
    c = boot(browser, server_url, token, DESKTOP)
    people(c)

    cards = c.page.locator("#peopleCard .pprof")
    assert cards.count() == 3
    for i, (_, url, title) in enumerate(PROFILES):
        link = cards.nth(i).locator("a.plink")
        assert link.count() == 1 and link.inner_text().strip().lower() == "open in browser"
        assert link.get_attribute("href") == url
        assert link.get_attribute("target") == "_blank"
        assert link.get_attribute("rel") == "noopener noreferrer"
        assert title in cards.nth(i).inner_text()
    names = [cards.nth(i).locator(".tname").inner_text() for i in range(3)]
    assert names == ["LinkedIn", "Wikipedia", "X"]
    # the dossier's own line about that site sits on its card, and is not repeated underneath
    assert "minister since 2024" in cards.nth(1).inner_text()
    assert c.page.locator("#peopleCard").inner_text().count("minister since 2024") == 1
    assert "harbour bridge" in c.page.locator("#peopleCard").inner_text()
    c.close()


def test_open_all_is_gone_and_no_page_is_framed(browser: Any, server_url: str, token: str) -> None:
    c = boot(browser, server_url, token, DESKTOP)
    people(c)

    panel = c.page.locator("#p-people")
    assert "open all" not in panel.inner_text().lower()
    assert c.page.locator("#peopleOpen").inner_text().strip().lower() == "open next"
    assert panel.locator("iframe, frame, object, embed").count() == 0
    c.close()


def test_open_next_opens_exactly_one_tab_a_click_and_marks_the_card(
    browser: Any, server_url: str, token: str
) -> None:
    c = boot(browser, server_url, token, DESKTOP)
    people(c)
    opened: list[str] = []
    c.ctx.on("page", lambda p: opened.append(p.url))
    cards, button = c.page.locator("#peopleCard .pprof"), c.page.locator("#peopleOpen")

    for n, (_, url, _title) in enumerate(PROFILES, start=1):
        with c.ctx.expect_page() as tab:
            button.click()
        tab.value.wait_for_load_state()
        assert tab.value.url == url
        c.page.wait_for_timeout(150)
        assert len(opened) == n  # one tab for one click, never more
        marks = [cards.nth(i).get_attribute("data-opened") for i in range(3)]
        assert marks == ["true"] * n + [None] * (3 - n)
        assert cards.nth(n - 1).locator(".pstate").inner_text() == "Opened"

    assert button.is_disabled() and button.inner_text().strip().lower() == "all opened"
    assert c.page.evaluate("window.__opens") == 0  # window.open is never called, so never counted
    assert "blocked" not in c.page.locator("#peopleNote").inner_text().lower()
    assert c.errors == [] and c.csp_violations() == []
    c.close()


def test_a_cards_own_link_opens_one_tab_and_open_next_then_skips_it(
    browser: Any, server_url: str, token: str
) -> None:
    c = boot(browser, server_url, token, DESKTOP)
    people(c)
    cards = c.page.locator("#peopleCard .pprof")

    with c.ctx.expect_page() as own:
        cards.nth(1).locator("a.plink").click()
    with c.ctx.expect_page() as first:
        c.page.locator("#peopleOpen").click()
    with c.ctx.expect_page() as last:
        c.page.locator("#peopleOpen").click()

    assert [own.value.url, first.value.url, last.value.url] == [
        PROFILES[1][1],
        PROFILES[0][1],
        PROFILES[2][1],
    ]
    assert c.page.locator("#peopleOpen").is_disabled()
    with c.ctx.expect_page() as again:  # a card's own link always works again
        cards.nth(0).locator("a.plink").click()
    assert again.value.url == PROFILES[0][1] and c.page.evaluate("window.__opens") == 0
    c.close()


def test_a_new_research_starts_the_marks_again(browser: Any, server_url: str, token: str) -> None:
    c = boot(browser, server_url, token, DESKTOP)
    other = json.loads(json.dumps(DOSSIER["dossier"]))
    other["name"], other["profiles"] = "Another Examplekar", other["profiles"][:2]
    c.page.route("**/v1/people/research", lambda r: _json(r, other))
    people(c)
    with c.ctx.expect_page():
        c.page.locator("#peopleOpen").click()

    c.page.locator("#peopleName").fill("Another Examplekar")
    c.page.locator("#peopleGo").click()
    c.page.locator("#peopleCard .pname", has_text="Another").wait_for()

    cards = c.page.locator("#peopleCard .pprof")
    assert cards.count() == 2
    assert [cards.nth(i).get_attribute("data-opened") for i in range(2)] == [None, None]
    assert c.page.locator("#peopleOpen").is_enabled()
    c.close()


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_profile_cards_pass_the_visual_gate_fresh_and_opened(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c = boot(browser, server_url, token, VIEWPORTS[vp], day=surface == "day")
    people(c)
    gate(c, "#p-people", vp, f"people cards {vp} {surface}")

    with c.ctx.expect_page():
        c.page.locator("#peopleOpen").click()
    c.page.wait_for_timeout(200)

    gate(c, "#p-people", vp, f"people cards, one opened {vp} {surface}")
    heights = c.page.evaluate(
        "[...document.querySelectorAll('#p-people a[href], #p-people button')]"
        ".filter((e) => e.getBoundingClientRect().width > 0).map((e) => e.getBoundingClientRect().height)"
    )
    assert heights and min(heights) >= (43.5 if vp == "phone" else 23.5)
    assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    c.close()


# ---- O11: "Checking..." on the Vitals chip -------------------------------------------------------
def _vitals(checking: bool) -> dict[str, Any]:
    board = json.loads(json.dumps(MOCK_VITALS))
    for item in board["items"]:
        if item["id"] == "github_token":
            item.update(
                status="unknown" if checking else "ok",
                checking=checking,
                reason="is being checked" if checking else "",
                note="Checking… JARVIS is asking GitHub for its limits; they show on the next refresh."
                if checking
                else "This token doesn't expire.",
                expires_at=None,
            )
    return board


@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_a_token_being_read_says_checking_then_shows_its_figures_by_itself(
    browser: Any, server_url: str, token: str, vp: str
) -> None:
    asked: list[int] = []

    def answer(route: Any) -> None:
        asked.append(1)
        _json(route, _vitals(checking=len(asked) == 1))

    c = boot(browser, server_url, token, VIEWPORTS[vp], routes={"**/v1/vitals": answer})
    c.open_panel("vitals")
    row = c.page.locator('#vitals-board .vt-row[data-id="github_token"]')
    row.wait_for()

    chip = row.locator(".vt-chip")
    assert chip.inner_text().strip().lower() == "checking…"
    assert chip.get_attribute("data-status") == "unknown"  # the same chip, only its word differs
    assert "hasn't been used" not in row.inner_text()
    gate(c, "#p-vitals", vp, f"vitals checking {vp}")

    expect(chip).to_have_text(
        "OK", ignore_case=True, timeout=8000
    )  # the panel looked again by itself
    assert len(asked) == 2
    c.close()


def _row_chip(c: Console) -> tuple[Any, Any]:
    row = c.page.locator('#vitals-board .vt-row[data-id="github_token"]')
    row.wait_for()
    return row, row.locator(".vt-chip")


def test_the_panel_follows_a_slow_github_until_it_answers_however_many_looks_it_takes(
    browser: Any, server_url: str, token: str
) -> None:
    """Code review M4: it reads again until no row is checking (more than the old three looks),
    each look a few seconds after the last. The page's clock is jumped; it also runs on its own,
    so each step waits for the look it causes rather than counting on the jump alone."""
    asked: list[int] = []

    def answer(route: Any) -> None:
        asked.append(1)
        _json(route, _vitals(checking=len(asked) <= 4))

    c = boot(browser, server_url, token, DESKTOP, routes={"**/v1/vitals": answer}, clock=True)
    c.open_panel("vitals")
    _, chip = _row_chip(c)
    expect(chip).to_have_text("Checking\u2026")
    for _ in range(8):  # bounded: the old code stopped after four reads in all
        if len(asked) >= 5:
            break
        with c.page.expect_response("**/v1/vitals"):
            c.page.clock.fast_forward(3_100)

    expect(chip).to_have_text("OK", ignore_case=True)
    assert len(asked) == 5 and c.errors == []  # and it stopped once the row was no longer checking
    c.close()


def test_a_github_that_never_answers_ends_in_plain_words_and_refresh_starts_again(
    browser: Any, server_url: str, token: str
) -> None:
    asked: list[int] = []

    def answer(route: Any) -> None:
        asked.append(1)
        _json(route, _vitals(checking=True))

    c = boot(browser, server_url, token, PHONE, routes={"**/v1/vitals": answer}, clock=True)
    c.open_panel("vitals")
    row, chip = _row_chip(c)
    expect(chip).to_have_text("Checking\u2026")
    c.page.clock.fast_forward(50_000)  # far past the follow time: the next look gives up

    expect(chip).to_have_text("Unknown", timeout=10_000)
    expect(row.locator(".vt-note")).to_have_text("GitHub didn't answer; press Refresh.")
    before = len(asked)
    c.page.clock.fast_forward(10_000)
    assert len(asked) == before  # it stopped asking
    gate(c, "#p-vitals", "phone", "vitals: GitHub did not answer")

    with c.page.expect_response("**/v1/vitals"):
        c.page.locator("#vitals-board .vt-sub .btn").click()  # his press: follow from the start
    expect(chip).to_have_text("Checking\u2026")
    with c.page.expect_response("**/v1/vitals"):
        c.page.clock.fast_forward(3_100)
    assert len(asked) >= before + 2 and c.errors == []
    c.close()


# ---- the block keeps the console's rule: nothing is asked before sign-in --------------------------
def test_before_sign_in_the_block_asks_the_server_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    """A call made before sign-in is answered 401, and the console answers a 401 with the sign-in
    gate: landing late, it would throw an owner who has just signed in back to the gate."""
    c = Console(browser, server_url, token, DESKTOP)
    asked: list[str] = []
    c.page.on("request", lambda r: asked.append(r.url) if "/v1/picture" in r.url else None)
    c.page.goto(server_url + "/")
    c.page.locator("#tokIn").wait_for()
    c.page.wait_for_timeout(1200)  # the R11.1 modules have loaded and built their blocks

    assert c.page.locator("#look").count() == 1 and asked == [] and c.errors == []

    c.page.locator("#tokIn").fill(token)
    c.page.locator("#tokBtn").click()
    c.page.locator("#welcome").wait_for()
    c.page.wait_for_timeout(800)

    assert len(asked) >= 1  # once he is in, the block asks whether a picture can be looked at
    assert c.page.locator("#welcome").is_visible() and not c.page.locator("#tokIn").is_visible()
    assert c.errors == [] and c.csp_violations() == []
    c.close()


# ---- O9: "Research the picture" in the People panel ----------------------------------------------
NAME = "Lekha Examplekar"
CAN = {"part": "look", "ready": "ready", "can": True, "why": ""}
NO_AI = {
    "part": "look",
    "ready": "ready",
    "can": False,
    "why": "Looking at a picture needs the AI, Sir, and the AI is switched off (Brain: No-AI). Switch it on with the Brain pill in the top bar and ask again.",
}
THING: dict[str, Any] = {
    "status": "done",
    "message": "A red packet of biscuits on a table. It reads: PARLE-G; GLUCOSE BISCUITS. I found 2 sources for Parle-G biscuit packet.",
    "person": False,
    "scene": "A red packet of biscuits on a table.",
    "text": ["PARLE-G", "GLUCOSE BISCUITS"],
    "subjects": [{"kind": "product", "name": "Parle-G biscuit packet"}],
    "sources": [
        {
            "about": "Parle-G biscuit packet",
            "n": 1,
            "title": "Parle-G: the story of a biscuit that everyone in the country grew up with",
            "domain": "example.org",
            "url": "https://www.example.org/a",
            "snippet": "A long-running glucose biscuit, sold in a yellow and red packet.",
        },
        {
            "about": "Parle-G biscuit packet",
            "n": 2,
            "title": "<img src=x onerror=window.__pwned=1>",
            "domain": "example.com",
            "url": "https://example.com/b",
            "snippet": "More about the packet.",
        },
        {
            "about": "Parle-G biscuit packet",
            "n": 3,
            "title": "Not a web page",
            "domain": "evil.example",
            "url": "javascript:window.__pwned=1",
            "snippet": "x",
        },
        {
            "about": "Parle-G biscuit packet",
            "n": 4,
            "title": "Plain http",
            "domain": "insecure.example",
            "url": "http://insecure.example/x",
            "snippet": "x",
        },
    ],
    "notes": [],
    "offer": None,
    "pictures": 1,
}
PERSON: dict[str, Any] = {
    "status": "done",
    "message": f"A person in a blue top stands under a banner. I don't identify people from pictures, Sir. I found 1 source for harbour bridge. The picture's text names {NAME}. Caption read: 'MINISTER {NAME.upper()}'. Shall I look {NAME} up from public sources, Sir?",
    "person": True,
    "scene": "A person in a blue top stands under a banner.",
    "text": [f"MINISTER {NAME.upper()}", "OPENS THE HARBOUR BRIDGE"],
    "subjects": [{"kind": "landmark", "name": "harbour bridge"}],
    "sources": [
        {
            "about": "harbour bridge",
            "n": 1,
            "title": "The harbour bridge",
            "domain": "ports.example.org",
            "url": "https://ports.example.org/bridge",
            "snippet": "Opened in 2026.",
        }
    ],
    "notes": [],
    "offer": {"name": NAME, "caption": f"MINISTER {NAME.upper()}"},
    "pictures": 1,
}


class Look:
    """A stateful fake of /v1/picture: the status, and one scripted answer per research."""

    def __init__(self, status: dict[str, Any] | None = None) -> None:
        self.status = status or CAN
        self.answer: tuple[int, dict[str, Any]] = (200, THING)
        self.posts: list[dict[str, Any]] = []

    def routes(self) -> dict[str, Any]:
        return {"**/v1/picture": self._status, "**/v1/picture/research": self._research}

    def _status(self, route: Any) -> None:
        _json(route, self.status)

    def _research(self, route: Any) -> None:
        self.posts.append(json.loads(route.request.post_data or "{}"))
        _json(route, self.answer[1], self.answer[0])


def look_block(c: Console, *, chat: bool = True) -> None:
    """Open People with the picture block; `chat`: a conversation exists (a message was sent)."""
    if chat:
        c.send("what is in this picture?")
    people(c)
    c.page.locator("#lookGo").wait_for()


def test_the_picture_block_sits_in_people_and_says_what_it_will_not_do(
    browser: Any, server_url: str, token: str
) -> None:
    look = Look()
    c = boot(browser, server_url, token, DESKTOP, routes=look.routes())
    look_block(c)

    box = c.page.locator("#p-people #look")
    assert box.locator("#lookTitle").inner_text().strip().lower() == "research a picture"
    words = box.locator("#lookIntro").inner_text()
    assert "things, places, labels and logos" in words
    assert "I don't identify people from pictures" in words
    assert c.page.locator("#lookGo").is_enabled()
    # it comes after the profile cards and before the brain-mode row, and overlaps nothing
    order = c.page.evaluate(
        "[...document.querySelector('#people').children].map((e) => e.id || e.className.split(' ')[0])"
    )
    assert order.index("look") > order.index("peopleCard") and order[-1].startswith("bopt")
    gate(c, "#p-people", "desktop", "people with the picture block")
    c.close()


def test_when_no_picture_can_be_looked_at_the_block_says_why(
    browser: Any, server_url: str, token: str
) -> None:
    look = Look(NO_AI)
    c = boot(browser, server_url, token, DESKTOP, routes=look.routes())
    look_block(c)

    assert c.page.locator("#lookGo").is_disabled()
    assert "the AI is switched off (Brain: No-AI)" in c.page.locator("#lookNote").inner_text()
    assert look.posts == []
    gate(c, "#p-people", "desktop", "people, picture block, AI off")
    c.close()


def test_without_a_conversation_it_asks_for_a_picture_first(
    browser: Any, server_url: str, token: str
) -> None:
    look = Look()
    c = boot(browser, server_url, token, DESKTOP, routes=look.routes())
    look_block(c, chat=False)

    c.page.locator("#lookGo").click()

    assert "Attach a picture in the chat" in c.page.locator("#lookNote").inner_text()
    assert look.posts == []
    c.close()


def test_a_thing_is_shown_with_its_words_and_its_sources_as_real_links(
    browser: Any, server_url: str, token: str
) -> None:
    look = Look()
    c = boot(browser, server_url, token, DESKTOP, routes=look.routes())
    look_block(c)

    c.page.locator("#lookGo").click()
    card = c.page.locator("#lookCard .integ")
    card.wait_for()

    (post,) = look.posts
    session = c.page.evaluate("window.JarvisApprovals.session()")
    assert post == {"session_id": session, "picture": 1} and session
    assert THING["message"] in card.inner_text()
    assert card.locator(".istate").inner_text().strip().lower() == "2 sources"
    links = card.locator("a.plink")
    assert links.count() == 2  # the javascript: and the plain-http "sources" are not links
    assert [links.nth(i).get_attribute("href") for i in range(2)] == [
        "https://www.example.org/a",
        "https://example.com/b",
    ]
    for i in range(2):
        assert links.nth(i).get_attribute("target") == "_blank"
        assert links.nth(i).get_attribute("rel") == "noopener noreferrer"
    # a title that looks like markup is shown as the text it is
    assert "<img src=x onerror=window.__pwned=1>" in card.inner_text()
    assert card.locator("img").count() == 0 and c.page.evaluate("window.__pwned") is None
    with c.ctx.expect_page() as tab:
        links.nth(0).click()
    assert tab.value.url == "https://www.example.org/a" and c.page.evaluate("window.__opens") == 0
    assert c.errors == [] and c.csp_violations() == []
    c.close()


def test_a_person_gets_the_fixed_sentence_and_a_name_only_as_an_offer_he_must_press(
    browser: Any, server_url: str, token: str
) -> None:
    look = Look()
    look.answer = (200, PERSON)
    asked: list[Any] = []
    routes = {
        **look.routes(),
        "**/v1/people/research": lambda r: (asked.append(1), _json(r, DOSSIER["dossier"])),
    }
    c = boot(browser, server_url, token, DESKTOP, routes=routes)
    look_block(c)

    c.page.locator("#lookGo").click()
    card = c.page.locator("#lookCard .integ")
    card.wait_for()

    assert "I don't identify people from pictures, Sir." in card.inner_text()
    assert card.locator(".istate").inner_text().strip().lower() == "a person"
    offer = c.page.locator("#lookOffer")
    assert offer.inner_text().strip().lower() == "put this name in the people box"
    # the offer shows the very line of the picture's text the name was read from (review M2)
    assert c.page.locator("#lookCaption").inner_text() == f"Caption read: 'MINISTER {NAME.upper()}'"
    offer.click()
    expect(c.page.locator("#peopleName")).to_have_value(NAME)

    assert c.page.locator("#peopleName").input_value() == NAME
    assert c.page.evaluate("document.activeElement.id") == "peopleName"
    assert (
        asked == []
    )  # nothing is looked up until HE presses Research; then the usual check decides
    assert "Press Research" in c.page.locator("#lookNote").inner_text()
    c.close()


@pytest.mark.parametrize(
    ("status", "body", "words", "bad"),
    [
        (
            200,
            {
                "status": "no_picture",
                "message": "There is no picture with your last message in this conversation, Sir. Attach one, send it, and ask again.",
            },
            "There is no picture with your last message",
            False,
        ),
        (
            200,
            {
                "status": "waiting",
                "message": "That needs your OK, Sir: the approval is waiting in Approvals.",
            },
            "waiting in Approvals",
            False,
        ),
        (
            200,
            {
                "status": "limit",
                "message": "I can't look at the picture, Sir: This month's limit of ₹500 is used up (₹512.50 spent). Raise it in Vitals.",
            },
            "₹500",
            False,
        ),
        (
            503,
            {
                "error": "unavailable",
                "detail": "The picture could not be researched just now, Sir. Please try again.",
            },
            "could not be researched",
            True,
        ),
        (
            429,
            {"error": "rate_limited", "detail": "Too many pictures; wait a moment."},
            "Too many pictures",
            True,
        ),
    ],
)
def test_when_it_does_not_run_the_block_says_why_in_the_servers_words(
    browser: Any,
    server_url: str,
    token: str,
    status: int,
    body: dict[str, Any],
    words: str,
    bad: bool,
) -> None:
    look = Look()
    look.answer = (status, body)
    c = boot(browser, server_url, token, DESKTOP, routes=look.routes())
    look_block(c)

    c.page.locator("#lookGo").click()
    note = c.page.locator("#lookNote")
    expect(note).to_contain_text(words)

    assert ("bad" in (note.get_attribute("class") or "").split()) is bad
    assert (
        c.page.locator("#lookCard .integ").count() == 0 and c.page.locator("#lookGo").is_enabled()
    )
    c.close()


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", list(VIEWPORTS))
@pytest.mark.parametrize("answer", ["thing", "person"])
def test_the_picture_block_passes_the_visual_gate_with_a_result(
    browser: Any, server_url: str, token: str, vp: str, surface: str, answer: str
) -> None:
    look = Look()
    look.answer = (200, THING if answer == "thing" else PERSON)
    c = boot(browser, server_url, token, VIEWPORTS[vp], day=surface == "day", routes=look.routes())
    look_block(c)

    c.page.locator("#lookGo").click()
    c.page.locator("#lookCard .integ").wait_for()
    c.page.wait_for_timeout(500)

    gate(c, "#p-people", vp, f"picture block {answer} {vp} {surface}")
    heights = c.page.evaluate(
        "[...document.querySelectorAll('#look a[href], #look button')]"
        ".filter((e) => e.getBoundingClientRect().width > 0).map((e) => e.getBoundingClientRect().height)"
    )
    assert heights and min(heights) >= (43.5 if vp == "phone" else 23.5)
    assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    c.close()
