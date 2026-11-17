# tests/browser/test_r131_i1_wired.py -- R13.1 I1: D's console and B's REAL engine on the WIRED
# app (tests/r131_wired_server.py: create_app, every wardrobe part, C's real adapter on recorded
# Google answers, the mock brain deciding "what should I wear?" with R13's rules), in a real
# Chromium with WebGL2 (software). Parts B and D tested these against contract fakes; here every
# module is the real one (I0-NOTES section 5, items 2 to 4; the Workshop's step 3):
#   - row 388: a typed and a spoken "what should I wear tomorrow?" open the try-on card under the
#     reply with no tap, the REAL figure dressed in exactly the card's pieces (`show()`'s look and
#     its drawn + hidden + cards), a private slot covered;
#   - one stage on the page: the card's and the section's figures take turns;
#   - Helpers -> Wardrobe opens dressed by itself in tomorrow's planned look, its readiness from
#     the server; the checklist when WebGL2 is missing (AVT-15);
#   - See it on me on C's real routes: the garment, his YES, the ₹ confirm (Cancel sends nothing),
#     ONE picture a browser decodes, the catalog unchanged; console-only holds (no cookie: 403);
#   - the Privacy page's Try-on rows.
# The page clock is pinned to 17 Nov 2026, 19:00 IST (the server's wardrobe clock). Drawn pictures
# only (r13_fakes_d.Picture): never a photo of anyone.
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from r131_wired_server import COOKIE, serve_wired
from test_console import DESKTOP, PHONE
from test_r131_d_card import Page, browser, call, until
from test_r131_d_seeme import a_shirt, add_garment, add_photo, me_alone, png, seeme, text

__all__ = ["browser"]
pytestmark = pytest.mark.browser
EVENING = datetime(2026, 11, 17, 13, 30, tzinfo=UTC)  # 19:00 IST: tomorrow's look
ASK = "What should I wear tomorrow?"
SLOW_S = 120.0  # B's files (2.6 MB) and the device models load once a page
# B's engine, recorded as D uses it: every mount, every show() (its look and its answer), every
# lost reason. The real engine keeps working; the spy only watches (test-only, in the page).
SPY = """(() => {
  const rec = { mounts: 0, live: 0, shown: [], lost: [] };
  window.__i1 = rec;
  let real = null;
  Object.defineProperty(window, 'JarvisTryOn3D', { configurable: true, get() { return real; },
    set(v) {
      real = Object.freeze({ supported: v.supported, mount(host, opts) {
        const o = Object.assign({}, opts || {}), lost = o.onLost;
        o.onLost = (why) => { rec.lost.push(String(why)); if (lost) lost(why); };
        const s = v.mount(host, o); rec.mounts += 1; rec.live += 1;
        const w = Object.assign(Object.create(null), s);
        w.show = (look, op) => { const r = s.show(look, op);
          rec.shown.push({ figures: JSON.parse(JSON.stringify(look)), drawn: r.drawn || [],
                           hidden: r.hidden || [], cards: r.cards || [], forced: r.forced || {} });
          return r; };
        w.dispose = () => { rec.live -= 1; return s.dispose(); };
        rec.stage = w; return Object.freeze(w); } }); } });
})();"""
SPIED = (
    "() => { const r = window.__i1;"
    " return r && {mounts: r.mounts, live: r.live, shown: r.shown, lost: r.lost}; }"
)
FRAMED = (
    "() => { const s = window.__i1 && window.__i1.stage; return !!s && s.stats().triangles > 0; }"
)


@pytest.fixture(scope="module")
def w_url(token: str) -> Iterator[str]:
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    url, stop = serve_wired(token)
    try:
        yield url
    finally:
        stop()


class Wired(Page):
    """D's signed-in console on the wired app: B's real engine (spied), I0's hook and door as I1
    joined them, his console's cookie, the evening clock."""

    def __init__(self, browser: Any, url: str, token: str, viewport: dict[str, int] = DESKTOP,
                 *, gl_fail: str = "", console: bool = True) -> None:  # fmt: skip
        super().__init__(browser, url, token, viewport, gl_fail=gl_fail, fake_engine=False,
                         hook=False)  # fmt: skip
        self.page.clock.set_system_time(EVENING)
        self.page.add_init_script(SPY)
        if console:
            self.ctx.add_cookies([{"name": COOKIE, "value": "1", "url": url}])

    def spy(self) -> Any:
        return self.page.evaluate(SPIED)

    def framed(self) -> bool:
        return bool(self.page.evaluate(FRAMED))

    def figure(self) -> Any:
        rec = self.spy()
        return rec["shown"][-1] if rec and rec["shown"] else None

    def drawn(self) -> bool:
        rec = self.spy()
        return bool(rec and rec["shown"] and rec["live"] == 1)


def _pieces(look: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in look["slots"]:
        if s.get("piece") and not s.get("private"):
            out.setdefault(s["slot"], []).append(s["piece"])
    return out


def _the_card(url: str, token: str) -> dict[str, list[str]]:
    """What the wired app's chat route answers to ASK: the card's slot -> piece ids."""
    reply = call(url, token, "/v1/chat", {"message": ASK})
    [card] = [c for c in reply["cards"] if c["kind"] == "tryon"]
    return {s["slot"]: s["pieces"] for s in card["slots"] if not s.get("private")}


@pytest.mark.parametrize("voice", [False, True], ids=["typed", "spoken"])
def test_row388_what_to_wear_opens_the_real_figure_in_exactly_the_cards_pieces(
    browser: Any, w_url: str, token: str, voice: bool
) -> None:
    want = _the_card(w_url, token)
    c = Wired(browser, w_url, token)
    try:
        c.open()
        assert (c.spy() or {}).get("mounts", 0) == 0  # nothing drawn before the reply
        c.ask(ASK, voice=voice)
        until(c.page, lambda: c.card().count() == 1 and c.drawn(), "the card's figure", SLOW_S)
        fig = c.figure()
        look = fig["figures"][0]["look"]
        firsts = {k: v[0] for k, v in want.items()}
        assert {k: v[0] for k, v in _pieces(look).items()} == firsts
        named = {s["slot"] for s in look["slots"] if not s.get("private")}
        assert named <= set(fig["drawn"]) | set(fig["hidden"]) | set(fig["cards"])
        covered = [s for s in look["slots"] if s.get("private")]
        assert covered and all(set(s) == {"slot", "private"} for s in covered)
        until(c.page, c.framed, "the first frame", SLOW_S)
        assert c.spy()["lost"] == [] and c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_card_and_the_section_take_turns_on_one_stage(
    browser: Any, w_url: str, token: str
) -> None:
    c = Wired(browser, w_url, token)
    try:
        c.open()
        c.wardrobe()
        until(c.page, c.drawn, "the section's figure", SLOW_S)
        c.ask(ASK)
        until(c.page, lambda: c.card().count() == 1 and c.spy()["mounts"] == 2, "the card", SLOW_S)
        assert c.spy()["live"] == 1  # the section gave its stage back
        assert c.section().locator(".tr-view").get_attribute("data-why") == "elsewhere"
        c.card().get_by_role("button", name="Open in Helpers").click()
        sec = c.section().locator(".tr-view")
        until(c.page, lambda: sec.get_attribute("data-mode") == "3d" and c.spy()["mounts"] == 3,
              "the section takes it back", SLOW_S)  # fmt: skip
        assert c.spy()["live"] == 1 and c.page.locator(".tr-stage canvas").count() == 1
        assert c.spy()["lost"] == [] and c.errors == []
    finally:
        c.close()


def test_the_section_opens_dressed_in_tomorrows_planned_look_with_server_readiness(
    browser: Any, w_url: str, token: str
) -> None:
    plans = call(w_url, token, "/v1/outfits")["tomorrow"]
    look = call(w_url, token, f"/v1/tryon/look?plan={plans[0]['id']}")
    c = Wired(browser, w_url, token)
    try:
        c.open()
        c.wardrobe()
        until(c.page, c.drawn, "the section's figure", SLOW_S)
        mine = {k: v[0] for k, v in _pieces(c.figure()["figures"][0]["look"]).items()}
        assert mine == {s["slot"]: s["piece"] for s in look["slots"] if s.get("piece")}
        text = c.section().inner_text()
        assert "Ready" in text and "Base layer (covered)" in text
        # R13's "Today" row tonight is a suggestion (id "suggestion"), not a plan: Show in 3D only
        # on the planned meeting (I1: the wired app's own answer; the fake had plans only)
        rows = c.page.locator("#hpp-wardrobe").get_by_role("button", name="Show in 3D")
        assert rows.count() == len([p for p in plans if p["id"].startswith("op_")]) == 1
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_compare_with_todays_suggestion_shows_two_figures(
    browser: Any, w_url: str, token: str
) -> None:
    # tonight's "Today" row is R13's suggestion (no plan): compare reads it by its day (I1)
    c = Wired(browser, w_url, token)
    try:
        c.open()
        c.wardrobe()
        until(c.page, c.drawn, "the section's figure", SLOW_S)
        c.section().get_by_role("button", name="Compare", exact=True).click()
        until(c.page, lambda: "Compare this look with:" in c.section().inner_text(), "the choice")
        choice = c.section().locator("button", has_text="Today").first
        choice.click()
        until(c.page, lambda: len(c.figure()["figures"]) == 2, "two figures", SLOW_S)
        assert "isn't there any more" not in c.section().inner_text().replace("\u2019", "'")
        assert [r for r in c.sent if "plan=suggestion" in r["url"]] == []
    finally:
        c.close()


def test_with_no_webgl2_the_section_and_the_card_are_the_checklist(
    browser: Any, w_url: str, token: str
) -> None:
    c = Wired(browser, w_url, token, gl_fail="no-webgl2")
    try:
        c.open()
        c.ask(ASK)
        until(c.page, lambda: c.card().locator(".tr-view[data-mode='list']").count() == 1,
              "the card's checklist", SLOW_S)  # fmt: skip
        assert c.card().locator(".tr-item").count() >= 5
        assert "Base layer (covered)" in c.card().inner_text()
        assert (c.spy() or {}).get("mounts", 0) == 0
    finally:
        c.close()


def test_see_it_on_me_on_cs_real_routes_yes_rupees_and_one_decodable_picture(
    browser: Any, w_url: str, token: str, tmp_path: Path
) -> None:
    before = call(w_url, token, "/v1/wardrobe?private=1")
    c = Wired(browser, w_url, token)
    try:
        c.open()
        c.wardrobe()
        until(c.page, lambda: "Your photo" in text(c), "See it on me", SLOW_S)
        add_photo(c, png(tmp_path, "me", me_alone()))
        until(c.page, lambda: "Your photo is kept, sealed." in text(c), "his photo", SLOW_S)
        add_garment(c, png(tmp_path, "shirt", a_shirt()))
        until(c.page, lambda: "a new navy shirt, not in your wardrobe" in text(c), "added", SLOW_S)
        go = seeme(c).get_by_role("button", name="See it on me", exact=True)
        go.click()
        dlg = c.page.locator("dialog.bdialog.tr-dlg")
        dlg.wait_for()
        dlg.locator("input").fill("YES")
        dlg.get_by_role("button", name="Agree").click()
        until(c.page, lambda: "Make 1 picture" in (dlg.text_content() or ""), "the ₹ confirm")
        assert "with GST" in (dlg.text_content() or "") and "$" not in (dlg.text_content() or "")
        dlg.get_by_role("button", name="Cancel").click()
        until(c.page, lambda: "Nothing was sent." in text(c), "cancelled")
        assert not c.posts("/v1/seeme/pictures")  # Cancel sends nothing
        go.click()
        until(c.page, lambda: "Make 1 picture" in (dlg.text_content() or ""), "the confirm again")
        dlg.get_by_role("button", name="Make the picture").click()
        until(c.page, lambda: "Generated 2D style preview" in text(c), "the picture", SLOW_S)
        [sent] = c.posts("/v1/seeme/pictures")
        assert set(json.loads(sent["body"])) == {
            "garment", "pieces", "confirm_cost", "inr_shown", "request_id",
        }  # fmt: skip
        pic = seeme(c).locator("img.tr-pic").last
        until(c.page, lambda: (pic.get_attribute("src") or "").startswith("data:image/png"), "it")
        until(c.page, lambda: pic.evaluate("i => i.complete && i.naturalWidth > 0"), "decoded")
        after = call(w_url, token, "/v1/wardrobe?private=1")
        assert (after["rev"], after["pieces"]) == (before["rev"], before["pieces"])  # never his
        assert len(call(w_url, token, "/v1/seeme")["pictures"]) == 1
        assert c.csp_violations() == []
    finally:
        c.close()


def test_a_script_without_his_console_is_refused_on_the_wired_app(
    browser: Any, w_url: str, token: str
) -> None:
    c = Wired(browser, w_url, token, console=False)
    try:
        c.open()
        got = c.page.evaluate(
            """async () => { const r = await fetch('/v1/seeme/photo', {headers:
               {Authorization: 'Bearer ' + localStorage.getItem('jarvis_token')}});
               return [r.status, await r.text()]; }"""
        )
        assert got[0] in (401, 403)
    finally:
        c.close()


def test_the_privacy_page_shows_the_six_try_on_rows(browser: Any, w_url: str, token: str) -> None:
    view = call(w_url, token, "/v1/privacy")
    rows = [r for r in view["categories"] if r.get("section") == "Try-on"]
    assert [r["id"] for r in rows] == [
        "tryon_figure", "tryon_all", "tryon_device", "tryon_photo", "tryon_pictures", "tryon_spend",
    ]  # fmt: skip
    c = Wired(browser, w_url, token, PHONE)
    try:
        c.open()
        c.open_panel("privacy")
        until(c.page, lambda: "All your try-on data" in c.page.inner_text("body"), "the rows")
        assert json.dumps(view).count("Couldn't check right now") == 0
    finally:
        c.close()
