# tests/browser/test_r131_d_card.py -- R13.1 Part D in a real Chromium (docs/plans/r13-1-try-on.md
# D8, D21; BRIEF-D section 3), against D's fake server (tests/r131_fakes_d.py over I0's):
#   - row 388: a reply carrying a `tryon` card opens the figure under it with NO tap, dressed in
#     exactly the card's slot -> piece ids (a private slot covered); typed or spoken; a reply
#     without the card draws nothing; one stage on the page (the card's and the section's take
#     turns)
#   - AVT-15: with no WebGL2, a lost context, a file that fails its check, a 10 s first render, or
#     I0's engine stub that throws, the checklist shows each piece with its image cards and
#     readiness; Change swaps a piece and "Wearing it" confirms the ready outfit through R13's
#     tools (the confirm first after a swap, L10)
# The 3D engine is the contract-keeping fake (tests/fixtures/r13_1/d_engine.mjs), routed in place
# of B's file; the page clock is pinned to 17 Nov 2026, 09:00 IST. The helpers here are shared by
# the other D modules.
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import pytest
from r131_fakes import T
from r131_fakes_d import CARD, ENGINE, PLAN, SHOE, SHOE2, serve_d
from test_console import CSP_SPY, DESKTOP, Console

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
PAGE_NOW = datetime(2026, 11, 17, 3, 30, tzinfo=UTC)  # 09:00 IST, r131_fakes.NOW
WHAT_TO_WEAR = "what should I wear today?"
CARD_PIECES = {s.slot: list(s.pieces) for s in CARD.slots if not s.private}


@pytest.fixture(scope="module")
def d_url(token: str) -> Iterator[str]:
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    url, stop = serve_d(token)
    try:
        yield url
    finally:
        stop()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def until(page: Any, check: Callable[[], Any], what: str, timeout_s: float = 30.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def call(url: str, token: str, path: str, body: Any = None, method: str | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url + path, data=data, method=method or ("POST" if data else "GET")
    )
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"null")


def reset(url: str, token: str, *, figure: bool = True) -> None:
    """The figure (178 cm typed, or none), no saved looks; his photo, YES, garments and pictures
    gone."""
    call(url, token, "/v1/test/r131-d/reset", {"figure": figure})
    call(url, token, "/v1/seeme/photo", method="DELETE")
    for g in call(url, token, "/v1/seeme/garments")["garments"]:
        call(url, token, f"/v1/seeme/garments/{g['id']}", method="DELETE")
    for p in call(url, token, "/v1/seeme")["pictures"]:
        call(url, token, f"/v1/seeme/pictures/{p['id']}", method="DELETE")


class Page(Console):
    """A signed-in console with the fake engine (or I0's stub), a pinned clock and a request log."""

    def __init__(
        self,
        browser: Any,
        url: str,
        token: str,
        viewport: dict[str, int] = DESKTOP,
        *,
        gl_fail: str = "",
        fake_engine: bool = True,
        clock: bool = False,
    ) -> None:
        self.url, self.token, self.errors = url, token, []
        # his phone and laptop keep India's time: the plan times and the caption read in IST
        self.ctx = browser.new_context(
            viewport=viewport, timezone_id="Asia/Kolkata", locale="en-IN"
        )
        self.page = self.ctx.new_page()
        self.page.add_init_script(CSP_SPY)
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("console", self._on_console)
        self.sent: list[dict[str, Any]] = []
        if clock:
            self.page.clock.install(time=PAGE_NOW)
        else:
            self.page.clock.set_system_time(PAGE_NOW)
        if gl_fail:
            self.page.add_init_script(f"window.__glFail = {json.dumps(gl_fail)};")
        if fake_engine:
            self.page.route("**/static/console-tryon-3d.js*", lambda r: r.fulfill(
                path=str(ENGINE), content_type="application/javascript"))  # fmt: skip
        self.page.on("request", self._log)

    def _log(self, req: Any) -> None:
        if "/v1/" not in req.url:
            return
        try:
            body = req.post_data
        except UnicodeDecodeError:  # a picture's bytes: only their size is kept here
            body = f"<{len(req.post_data_buffer or b'')} bytes>"
        self.sent.append({"method": req.method, "url": req.url, "body": body})

    def posts(self, part: str) -> list[dict[str, Any]]:
        return [r for r in self.sent if r["method"] != "GET" and part in r["url"]]

    def engine(self) -> Any:
        return self.page.evaluate("() => window.__r131d || null")

    def wardrobe(self) -> None:
        self.open_panel("helpers")
        self.page.locator("#hpt-wardrobe").click()
        until(self.page, lambda: self.section().locator(".tr-view").count() > 0, "Try it on")

    def section(self) -> Any:
        return self.page.locator("#hpp-wardrobe .tr-sec")

    def card(self) -> Any:
        return self.page.locator(".row.jarvis .tr-card").last

    def ask(self, text: str = WHAT_TO_WEAR, *, voice: bool = False) -> None:
        if voice:  # the voice module's own path: channel voice, the words already understood
            self.page.evaluate(
                "(t) => window.JarvisChat.send(t, { channel: 'voice', heard: '' })", text
            )
            self.page.locator(".row.jarvis .bubble:not(.typing)").last.wait_for()
        else:
            self.send(text)


def shown_pieces(figure: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in figure["look"]["slots"]:
        if not s.get("private"):
            out.setdefault(s["slot"], []).append(s["piece"])
    return out


def mode(view: Any) -> str:
    return str(view.get_attribute("data-mode") or "")


def drawn(c: Page, n: int = 1) -> bool:
    """The engine has been shown a look n times (the figure is on the stage)."""
    rec = c.engine()
    return bool(rec and len(rec["shown"]) >= n and rec["live"] == 1)


# ---- row 388 -------------------------------------------------------------------------------------
def test_row388_asking_what_to_wear_opens_the_card_dressed_in_the_chosen_look(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token)
    try:
        c.open()
        clicks_before = c.page.evaluate("() => window.__r131d ? window.__r131d.mounts : 0")
        c.ask()
        until(c.page, lambda: c.card().count() == 1 and drawn(c), "the card's figure")
        assert (
            clicks_before == 0
        )  # nothing was mounted before the reply: it opened by itself, no tap
        rec = c.engine()
        last = rec["shown"][-1]
        assert len(last["figures"]) == 1
        assert (
            shown_pieces(last["figures"][0]) == CARD_PIECES
        )  # exactly the card's slot -> piece ids
        base = [s for s in last["figures"][0]["look"]["slots"] if s["slot"] == "base"]
        assert base == [{"slot": "base", "private": True}]  # covered: nothing that names it
        looks = [unquote(r["url"]) for r in c.sent if "/v1/tryon/look" in r["url"]]
        assert any(f"top:{T.striped}" in u and f"shoes:{SHOE},shoes:{SHOE2}" in u for u in looks)
        t = c.card().inner_text()
        assert "Base layer (covered)" in t and "vest" not in t.lower()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_row388_a_spoken_reply_opens_the_same_card(browser: Any, d_url: str, token: str) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token)
    try:
        c.open()
        c.ask(voice=True)
        until(c.page, lambda: c.card().count() == 1 and drawn(c), "the card")
        assert shown_pieces(c.engine()["shown"][-1]["figures"][0]) == CARD_PIECES
    finally:
        c.close()


def test_row388_a_reply_without_the_card_draws_nothing(
    browser: Any, d_url: str, token: str
) -> None:
    c = Page(browser, d_url, token)
    try:
        c.open()
        c.send("remember that I like navy")
        c.page.wait_for_timeout(500)
        assert c.page.locator(".tr-card").count() == 0 and c.engine() is None
        assert not [r for r in c.sent if "/v1/tryon" in r["url"]]
    finally:
        c.close()


def test_row388_with_no_webgl_the_card_shows_the_same_pieces_as_a_checklist(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token, gl_fail="no-webgl2")
    try:
        c.open()
        c.ask()
        until(
            c.page,
            lambda: c.card().locator(".tr-view[data-mode='list']").count() == 1,
            "the checklist",
        )
        rows = c.card().locator(".tr-item")
        got: dict[str, list[str]] = {}
        for i in range(rows.count()):
            r = rows.nth(i)
            if r.get_attribute("data-piece"):
                got.setdefault(str(r.get_attribute("data-slot")), []).append(
                    str(r.get_attribute("data-piece"))
                )
        assert got == CARD_PIECES
        assert "Base layer (covered)" in c.card().inner_text()
    finally:
        c.close()


def test_row388_one_stage_on_the_page_the_card_and_the_section_take_turns(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token)
    try:
        c.open()
        c.wardrobe()
        until(c.page, lambda: drawn(c), "the section's figure")
        c.ask()
        until(
            c.page,
            lambda: c.card().count() == 1 and drawn(c, 2) and c.engine()["mounts"] == 2,
            "the card's figure",
        )
        rec = c.engine()
        assert rec["maxLive"] == 1 and rec["live"] == 1 and rec["disposes"] >= 1
        assert c.section().locator(".tr-view").get_attribute("data-why") == "elsewhere"
    finally:
        c.close()


# ---- AVT-15 --------------------------------------------------------------------------------------
@pytest.mark.parametrize("how", ["no-webgl2", "lost", "asset", "timeout", "stub"])
def test_avt15_a_failed_render_leaves_a_checklist_that_can_change_a_piece_and_confirm(
    browser: Any, d_url: str, token: str, how: str
) -> None:
    reset(d_url, token)
    stub = how == "stub"  # I0's engine stub: mount() throws "The 3D view is not built yet."
    c = Page(
        browser,
        d_url,
        token,
        gl_fail="" if stub else how,
        fake_engine=not stub,
        clock=how == "timeout",
    )
    try:
        c.open()
        c.wardrobe()
        view = c.section().locator(".tr-view")
        if how == "timeout":
            until(c.page, lambda: c.engine() and c.engine()["mounts"] == 1, "the stage")
            c.page.clock.run_for(10_500)  # a first render over 10 s
        until(c.page, lambda: mode(view) == "list", "the checklist")
        assert view.get_attribute("data-why") == {"stub": "engine"}.get(how, how)
        rows = c.section().locator(".tr-item[data-slot='outer']")
        assert "charcoal blazer" in rows.inner_text() and "Ready" in rows.inner_text()
        assert (
            c.section().locator(".tr-item[data-slot='top'] + .tr-refs img.tr-thumb").count() >= 1
        )  # its image cards
        rows.get_by_role("button", name="Change").click()
        c.section().get_by_role("button", name="navy jacket · Draft: in the laundry").wait_for()
        before = len(call(d_url, token, "/v1/test/r131-d")["tools"])
        c.section().locator(".tr-item[data-slot='watch']").get_by_role(
            "button", name="Change"
        ).click()
        c.section().get_by_role("button", name="brown watch · Ready").click()
        until(
            c.page,
            lambda: c.section().locator(f".tr-item[data-piece='{T.watch2}']").count() == 1,
            "the swap",
        )
        c.section().get_by_role("button", name="Wearing it", exact=True).click()
        until(
            c.page,
            lambda: len(call(d_url, token, "/v1/test/r131-d")["tools"]) > before,
            "the tool call",
        )
        confirm = c.posts("/v1/tryon/confirm")
        assert len(confirm) == 1  # the swap wasn't confirmed: the confirm ran first (L10)
        body = json.loads(confirm[0]["body"])
        assert body["plan"] == PLAN and {"slot": "watch", "piece": T.watch2} in body["slots"]
        assert call(d_url, token, "/v1/test/r131-d")["tools"][-1] == {
            "tool": "wear_log", "arguments": {"action": "start", "plan": PLAN}}  # fmt: skip
        retry = 0 if how == "no-webgl2" else 1  # once a page; no point without WebGL2
        assert c.section().get_by_role("button", name="Retry 3D").count() == retry
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_avt15_retry_3d_is_offered_once_a_page(browser: Any, d_url: str, token: str) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token, gl_fail="lost")
    try:
        c.open()
        c.wardrobe()
        view = c.section().locator(".tr-view")
        until(c.page, lambda: mode(view) == "list", "the checklist")
        c.section().get_by_role("button", name="Retry 3D").click()
        until(c.page, lambda: c.engine()["mounts"] == 2, "the second mount")
        until(c.page, lambda: mode(view) == "list" and c.engine()["lost"] == 2, "lost again")
        assert c.section().get_by_role("button", name="Retry 3D").count() == 0
        assert c.section().get_by_role("button", name="Show in 3D").count() == 0
    finally:
        c.close()
