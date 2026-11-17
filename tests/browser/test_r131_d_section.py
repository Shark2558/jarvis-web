# tests/browser/test_r131_d_section.py -- R13.1 Part D: Helpers -> Wardrobe -> Try it on in a real
# Chromium (docs/plans/r13-1-try-on.md D1, D4, D5, D7, D9, D16; BRIEF-D section 3, the UI halves):
# the section opens dressed by itself; Front, Side, Back, Turn around, Closer look, zoom (AVT-02);
# the measurements form (AVT-03); the reference cards (AVT-04); the shape choice (AVT-05); the
# watch swap and its thumbnail (AVT-06); Front -> Back keeps the state (AVT-08); a draft jacket,
# the server's refusal and undo (AVT-09); tuck and open (AVT-10); compare and save (AVT-11); the
# share caption (AVT-14); Delete all my try-on data (OPS-05). Fake engine, fake server, pinned
# clock (test_r131_d_card.py's helpers).
from __future__ import annotations

import json
from typing import Any

from r131_fakes import T
from r131_fakes_d import BLAZER_PHOTO, FESTIVE, PLAN, WATCH2_PHOTO, WATCH_PHOTO
from test_r131_d_card import Page, browser, call, d_url, drawn, reset, shown_pieces, until

__all__ = ["browser", "d_url"]  # the fixtures, shared
pytestmark = __import__("pytest").mark.browser


def opened(c: Page) -> Page:
    c.open()
    c.wardrobe()
    until(c.page, lambda: drawn(c), "the section's figure")
    return c


def last(c: Page) -> dict[str, Any]:
    return dict(c.engine()["shown"][-1])


def press(c: Page, name: str) -> None:
    c.section().get_by_role("button", name=name, exact=True).first.click()


def row(c: Page, slot: str, n: int = 0) -> Any:
    return c.section().locator(f".tr-col[data-look='{n}'] .tr-item[data-slot='{slot}']").first


def test_the_section_opens_dressed_in_the_first_plans_look_by_itself(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        pieces = shown_pieces(last(c)["figures"][0])
        assert pieces["top"] == [T.striped] and pieces["outer"] == [T.blazer]
        head = c.section().locator(".tr-head").inner_text()
        assert "Today · 10:00 · business formal" in head
        assert "Estimated from your measurements" in head
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_avt02_controls_front_side_back_turn_closer_and_zoom(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        for name in ("Side", "Back", "Front"):
            press(c, name)
        press(c, "Turn around")
        press(c, "Closer look")
        press(c, "Zoom in")
        press(c, "Zoom out")
        rec = c.engine()
        assert rec["views"] == ["side", "back", "front"]
        assert rec["spins"] == [True] and rec["closer"] == 1 and rec["zooms"] == [1, -1]
        front = c.section().get_by_role("button", name="Front", exact=True)
        assert front.get_attribute("aria-pressed") == "true"
        # drag turns the figure on B's own canvas (its controls); the stage has nothing over it
        assert c.section().locator(".tr-stage > :not(svg):not(p)").count() == 0
    finally:
        c.close()


def test_avt03_form_correcting_height_redraws_and_keeps_every_piece(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        before = last(c)
        form = c.section().locator(".tr-form")
        assert "estimated" in form.inner_text() and "typed" in form.inner_text()
        height = form.locator("input[name='height']")
        assert height.input_value() == "178"
        height.fill("140")
        height.press("Enter")
        until(
            c.page,
            lambda: "The figure can be 150 to 195 cm tall" in c.section().inner_text(),
            "the words",
        )
        assert not c.posts("/v1/tryon/body")  # refused in words, nothing sent
        height.fill("181")
        height.press("Enter")
        until(c.page, lambda: c.posts("/v1/tryon/body"), "the draft")
        assert json.loads(c.posts("/v1/tryon/body")[0]["body"]) == {"height": 181}
        until(
            c.page, lambda: last(c)["figures"][0]["body"] != before["figures"][0]["body"], "redraw"
        )
        after = last(c)
        assert shown_pieces(after["figures"][0]) == shown_pieces(before["figures"][0])  # kept
        assert after["figures"][0]["body"]["weights"]["height"] > 0.3
        press(c, "Use these measurements")
        until(c.page, lambda: c.posts("/v1/tryon/body/use"), "Use these measurements")
        until(
            c.page,
            lambda: c.section().get_by_role("button", name="Keep the current").count() == 0,
            "the draft made current",
        )
    finally:
        c.close()


def test_avt04_cards_a_kurta_shows_front_and_back_and_a_shirt_asks_for_its_back(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        c.page.locator("#hpp-wardrobe .wd-plan").nth(1).get_by_role(
            "button", name="Show in 3D"
        ).click()
        until(
            c.page, lambda: shown_pieces(last(c)["figures"][0]).get("top") == [T.kurta], "festive"
        )
        refs = c.section().locator(".tr-item[data-slot='top'] + .tr-refs")
        until(
            c.page,
            lambda: refs.locator("img.tr-thumb[src^='data:image/png']").count() == 2,
            "both cards",
        )
        assert refs.locator("img").evaluate_all("l => l.map(i => i.dataset.photo)") == [
            "wh_00000000a001",
            "wh_00000000a002",
        ]
        assert "Front" in refs.inner_text() and "Back" in refs.inner_text()
        assert "No back photo" not in refs.inner_text()
        c.page.locator("#hpp-wardrobe .wd-plan").nth(0).get_by_role(
            "button", name="Show in 3D"
        ).click()
        until(
            c.page, lambda: shown_pieces(last(c)["figures"][0]).get("top") == [T.striped], "formal"
        )
        refs = c.section().locator(".tr-item[data-slot='top'] + .tr-refs")
        assert "No back photo of it yet: add one in Camera, Wardrobe." in refs.inner_text()
        assert refs.get_by_role("button", name="Open Camera").count() == 1
        assert row(c, "top").get_attribute("data-piece") == T.striped  # still selectable, same id
    finally:
        c.close()


def test_avt05_card_a_patterned_shirt_is_approximate_and_can_be_its_photo_only(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        top = row(c, "top")
        assert (
            "Approximate shape" in top.inner_text() and "texture from its photo" in top.inner_text()
        )
        assert last(c)["figures"][0]["look"]["slots"][0]["template"] == "shirt"
        pick = c.section().locator(".tr-shapes select").first
        assert pick.input_value() == "shirt"
        pick.select_option("")
        until(c.page, lambda: c.posts(f"/v1/tryon/assets/{T.striped}"), "the choice")
        sent = json.loads(c.posts(f"/v1/tryon/assets/{T.striped}")[0]["body"])
        assert sent == {"piece": T.striped, "template": None, "card_only": True}
        until(c.page, lambda: last(c)["figures"][0]["look"]["slots"][0]["template"] is None, "card")
        assert "Shown as its photo only" in row(c, "top").inner_text()
        assert c.section().locator(".tr-item[data-slot='top'] + .tr-refs img").count() >= 1
    finally:
        c.close()


def test_avt06_swap_the_watch_changes_its_wrist_piece_and_its_thumbnail(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        refs = c.section().locator(".tr-item[data-slot='watch'] + .tr-refs img")
        assert refs.first.get_attribute("data-photo") == WATCH_PHOTO
        row(c, "watch").get_by_role("button", name="Change").click()
        press(c, "brown watch · Ready")
        until(c.page, lambda: row(c, "watch").get_attribute("data-piece") == T.watch2, "the swap")
        assert refs.first.get_attribute("data-photo") == WATCH2_PHOTO  # W2's thumbnail now
        watch = [s for s in last(c)["figures"][0]["look"]["slots"] if s["slot"] == "watch"]
        assert watch[0]["piece"] == T.watch2 and watch[0]["rgb"] == [110, 75, 50]
    finally:
        c.close()


EMPTY_IMAGES = """() => [...document.querySelectorAll('#hpp-wardrobe .tr-sec img.tr-thumb')]
  .filter((i) => !i.getAttribute('src') && i.getBoundingClientRect().height
    && getComputedStyle(i).visibility !== 'hidden').length"""  # an <img> painting its alt text


def crops(c: Page) -> int:
    return len([r for r in c.sent if "/v1/wardrobe/photos/" in r["url"]])


def test_a_control_press_fetches_no_image_card_again_and_shows_no_empty_one(
    browser: Any, d_url: str, token: str
) -> None:
    # review D-1 M2: three view presses made 12 crop requests, and 50 ms after each every card
    # had no src (Chromium painted "Front photo", "Detail photo" and a broken-image icon)
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        cards = c.section().locator("img.tr-thumb[src^='data:image/png']")
        until(c.page, lambda: cards.count() >= 3, "the image cards")
        before = crops(c)
        for name in ("Side", "Back", "Front"):
            press(c, name)
            c.page.wait_for_timeout(50)
            assert c.page.evaluate(EMPTY_IMAGES) == 0, name
        row(c, "watch").get_by_role("button", name="Change").click()  # the list is drawn again
        assert c.page.evaluate(EMPTY_IMAGES) == 0
        press(c, "Cancel")
        c.page.wait_for_timeout(300)
        assert c.page.evaluate(EMPTY_IMAGES) == 0
        assert crops(c) == before  # every card from page memory, none fetched again
    finally:
        c.close()


FOCUSED = """() => { const a = document.activeElement;
  return [a.textContent, a.getAttribute('aria-pressed')]; }"""


def enter(c: Page, button: Any) -> None:
    button.focus()
    c.page.keyboard.press("Enter")


def test_keyboard_focus_stays_on_the_pressed_control_or_the_one_in_its_place(
    browser: Any, d_url: str, token: str
) -> None:
    # review D-1 M5: draw() replaced every button, so after Enter on Side the focus was on BODY
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        sec = c.section()
        enter(c, sec.get_by_role("button", name="Side", exact=True))
        until(c.page, lambda: c.engine()["views"][-1:] == ["side"], "Side")
        assert c.page.evaluate(FOCUSED) == ["Side", "true"]
        enter(c, sec.get_by_role("button", name="Untuck", exact=True))
        assert c.page.evaluate(FOCUSED)[0] == "Tuck in"  # the same control, its words turned
        enter(c, sec.get_by_role("button", name="Without the outer layer", exact=True))
        assert c.page.evaluate(FOCUSED) == ["Without the outer layer", "true"]
        enter(c, sec.get_by_role("button", name="Undo", exact=True))
        assert c.page.evaluate(FOCUSED)[0] == "Undo"
        enter(c, row(c, "watch").get_by_role("button", name="Change"))
        assert c.page.evaluate(FOCUSED)[0] == "Change"
        enter(c, sec.get_by_role("button", name="brown watch · Ready"))
        until(c.page, lambda: row(c, "watch").get_attribute("data-piece") == T.watch2, "the swap")
        on = c.page.evaluate("() => document.activeElement.closest('.tr-item').dataset.slot")
        assert on == "watch"  # back on that slot's Change
        enter(c, sec.get_by_role("button", name="Show as a list", exact=True))
        assert c.page.evaluate(FOCUSED)[0] == "Show in 3D"  # the switch in its place
    finally:
        c.close()


def test_avt08_front_to_back_keeps_the_pieces_the_styling_and_the_figure(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        press(c, "Untuck")
        press(c, "Close the jacket")
        before = last(c)
        press(c, "Back")
        until(c.page, lambda: c.engine()["views"][-1:] == ["back"], "Back")
        press(c, "All layers")
        after = last(c)
        assert shown_pieces(after["figures"][0]) == shown_pieces(before["figures"][0])
        assert after["figures"][0]["body"] == before["figures"][0]["body"]
        assert {k: after["opts"][k] for k in ("tucked", "open", "layers")} == {
            "tucked": False,
            "open": False,
            "layers": "all",
        }
        assert after["opts"]["view"] == "back"
    finally:
        c.close()


def test_avt09_swap_undo_a_jacket_in_the_laundry_is_a_draft_the_server_refuses(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        row(c, "outer").get_by_role("button", name="Change").click()
        press(c, "navy jacket · Draft: in the laundry")
        until(c.page, lambda: row(c, "outer").get_attribute("data-piece") == T.rain_jacket, "swap")
        outer = [s for s in last(c)["figures"][0]["look"]["slots"] if s["slot"] == "outer"]
        assert outer[0]["piece"] == T.rain_jacket  # the figure and the checklist in one step
        assert "Draft: in the laundry" in row(c, "outer").inner_text()
        assert "can’t be confirmed for the event" in c.section().inner_text()
        tools = len(call(d_url, token, "/v1/test/r131-d")["tools"])
        press(c, "Use this look")
        until(
            c.page, lambda: "it can't be confirmed for this event" in c.section().inner_text(), "no"
        )
        assert len(call(d_url, token, "/v1/test/r131-d")["tools"]) == tools  # no outfit_plan call
        press(c, "Undo")
        until(c.page, lambda: row(c, "outer").get_attribute("data-piece") == T.blazer, "undo")
        assert [
            s["piece"] for s in last(c)["figures"][0]["look"]["slots"] if s["slot"] == "outer"
        ] == [T.blazer]
    finally:
        c.close()


def test_avt09_remove_takes_the_watch_off_the_figure_and_the_list_and_undo_puts_it_back(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        row(c, "watch").get_by_role("button", name="Change").click()
        press(c, "Remove")
        until(c.page, lambda: row(c, "watch").count() == 0, "the watch removed")
        assert "watch" not in shown_pieces(last(c)["figures"][0])
        looks = [r["url"] for r in c.sent if "/v1/tryon/look?pieces=" in r["url"]]
        assert "watch" not in looks[-1] and T.watch not in looks[-1]  # read fresh without it
        press(c, "Undo")
        until(c.page, lambda: row(c, "watch").get_attribute("data-piece") == T.watch, "undo")
        assert shown_pieces(last(c)["figures"][0])["watch"] == [T.watch]
    finally:
        c.close()


def test_avt10_toggles_close_the_jacket_untuck_and_a_kurta_says_it_is_worn_out(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        press(c, "Close the jacket")
        slots = {s["slot"]: s for s in last(c)["figures"][0]["look"]["slots"]}
        assert slots["outer"]["variant"] == "closed" and slots["outer"]["piece"] == T.blazer
        press(c, "Untuck")
        slots = {s["slot"]: s for s in last(c)["figures"][0]["look"]["slots"]}
        assert slots["top"]["variant"] == "untucked" and last(c)["opts"]["tucked"] is False
        c.page.locator("#hpp-wardrobe .wd-plan").nth(1).get_by_role(
            "button", name="Show in 3D"
        ).click()
        until(
            c.page, lambda: shown_pieces(last(c)["figures"][0]).get("top") == [T.kurta], "festive"
        )
        assert "A kurta is worn out." in c.section().inner_text()
        assert c.section().get_by_role("button", name="Tuck in").count() == 0
    finally:
        c.close()


def test_a_shirt_over_a_mundu_drawn_tucked_says_so_and_offers_no_tuck_in_section_and_card(
    browser: Any, d_url: str, token: str
) -> None:
    # INTEGRATION-B section 8, "Needs I1" 1: B's show() answers forced {top: 'tucked'} when it can
    # only draw the top tucked (a shirt over a wrap); D says so and switches the tuck control off
    reset(d_url, token)
    c = Page(browser, d_url, token)

    def as_a_mundu(route: Any) -> None:  # the look's bottom is a white mundu, worn untucked
        r = route.fetch()
        look = r.json()
        look["tucked"] = False
        for s in look["slots"]:
            if s["slot"] == "bottom":
                s.update(template="wrap", words="white mundu", variants=[])
        route.fulfill(response=r, json=look)

    c.page.route("**/v1/tryon/look?*", as_a_mundu)
    words = "Drawn tucked into the white mundu"
    try:
        opened(c)
        until(c.page, lambda: words in c.section().inner_text(), "the section says it")
        assert last(c)["opts"]["tucked"] is False  # what he asked stays his
        tuck = c.section().locator(".tr-style").get_by_role("button", name="Tuck in")
        assert tuck.count() == 0
        assert c.section().locator(".tr-style").get_by_role("button", name="Untuck").count() == 0
        c.ask()
        until(c.page, lambda: words in c.card().inner_text(), "the card says it")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_an_emptied_status_line_takes_no_room(browser: Any, d_url: str, token: str) -> None:
    # review D-1 L3: H.note() set the status's class and dropped tr-status (":empty" hides it)
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        status = c.section().locator(".tr-view p[role='status']")
        until(c.page, lambda: status.inner_text() == "", "Preparing said, then emptied")
        assert "tr-status" in (status.get_attribute("class") or "").split()
        assert status.evaluate("e => getComputedStyle(e).display") == "none"
    finally:
        c.close()


def test_try_on_unavailable_for_now_says_so_and_tries_again_and_off_hides_it(
    browser: Any, d_url: str, token: str
) -> None:
    # review D-1 L4: a 503 is "unavailable", not "off": the section stays, says so, tries again;
    # L12: a look that fails to load leaves no "Loading the look..." beside its error
    reset(d_url, token)
    c = Page(browser, d_url, token)
    down = {"error": "unavailable", "detail": "Try-on is starting."}
    c.page.route("**/v1/tryon", lambda r: r.fulfill(status=503, json=down))
    try:
        c.open()
        c.open_panel("helpers")
        c.page.locator("#hpt-wardrobe").click()
        sec = c.section()
        until(c.page, lambda: "Try it on can’t load right now." in sec.inner_text(), "said")
        assert sec.is_visible()
        c.page.unroute("**/v1/tryon")
        broken = {"error": "unavailable", "detail": "The look didn't load."}
        c.page.route("**/v1/tryon/look?*", lambda r: r.fulfill(status=500, json=broken))
        sec.get_by_role("button", name="Try again").click()
        until(c.page, lambda: "The look didn't load." in sec.inner_text(), "the look's error")
        assert "Loading the look" not in sec.inner_text()
        c.page.unroute("**/v1/tryon/look?*")
    finally:
        c.close()


def test_avt11_lists_a_formal_and_a_festive_look_with_both_lists_and_their_readiness(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        press(c, "Compare")
        press(c, "Tomorrow · 19:00 · festive")
        until(c.page, lambda: len(last(c)["figures"]) == 2, "two figures in one show")
        a, b = last(c)["figures"]
        assert shown_pieces(a)["top"] == [T.striped] and shown_pieces(b)["top"] == [T.kurta]
        cols = c.section().locator(".tr-pair .tr-col")
        assert cols.count() == 2
        for i in (0, 1):
            items = cols.nth(i).locator(".tr-item[data-piece]")
            assert items.count() >= 3
            for j in range(items.count()):
                assert "Ready" in items.nth(j).inner_text()  # each piece's readiness word
        press(c, "Save this comparison")
        until(c.page, lambda: c.posts("/v1/tryon/saved"), "saved")
        sent = json.loads(c.posts("/v1/tryon/saved")[0]["body"])
        assert [x["plan"] for x in sent["looks"]] == [PLAN, FESTIVE]
        until(c.page, lambda: "A saved comparison" in c.section().inner_text(), "the list")
    finally:
        c.close()


def test_avt14_share_the_caption_has_fixed_words_and_never_a_private_label_or_id(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        press(c, "Save a picture of this look")
        until(c.page, lambda: c.engine()["snapshots"], "the snapshot")
        cap = c.engine()["snapshots"][-1]["caption"]
        assert cap == [
            "Tue 17 Nov 2026 · 10:00",
            "Navy shirt · Charcoal trousers · Charcoal blazer",
            "Brown dress shoe · Black belt · Grey watch",
            "Base layer (covered)",
        ]
        joined = " ".join(cap)
        assert "wi_" not in joined and "vest" not in joined.lower()
        shot = c.section().locator("img.tr-shot")
        until(
            c.page,
            lambda: (shot.get_attribute("src") or "").startswith("data:image/png"),
            "preview",
        )
        with c.page.expect_download() as dl:
            press(c, "Save to Downloads")
        assert dl.value.suggested_filename == "jarvis-look-2026-11-17.png"
        c.section().locator("#trOwnLabels").check()
        press(c, "Close")
        press(c, "Save a picture of this look")
        until(c.page, lambda: len(c.engine()["snapshots"]) == 2, "the second snapshot")
        own = c.engine()["snapshots"][-1]["caption"]
        assert "Navy striped shirt" in " ".join(own) and own[-1] == "Base layer (covered)"
    finally:
        c.close()


PRIVACY = {
    "categories": [
        {
            "id": "tryon_all", "section": "Try-on", "label": "All your try-on data",
            "what": "Your figure, measurements, photo, YES, pictures and garment photos.",
            "delete": "passkey", "count": 3, "rev": "r1", "available": True,
            "note": "Copies inside JARVIS's own daily backups stay locked and are gone within "
            "7 days.",
        }
    ],
    "passkey_in_force": False,
}  # fmt: skip


def test_ops05_button_deletes_through_privacy_empties_the_viewer_and_keeps_the_catalog(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        before = call(d_url, token, "/v1/wardrobe")
        c.page.route("**/v1/privacy", lambda r: r.fulfill(json=PRIVACY))

        def delete(route: Any) -> None:
            reset(d_url, token, figure=False)  # A's erase_all, as the fake server can do it
            route.fulfill(json={"deleted": 3, "remaining": 0})

        c.page.route("**/v1/privacy/tryon_all/delete", delete)
        press(c, "Delete all my try-on data")
        c.page.locator(".pv-dlg").wait_for()
        assert "gone within 7 days" in c.page.locator(".pv-dlg").inner_text()
        c.page.locator("#pvType").fill("DELETE")
        c.page.locator("#pvGo").click()
        view = c.section().locator(".tr-view")
        until(c.page, lambda: view.get_attribute("data-why") == "nofigure", "No figure yet")
        assert "No figure yet: type your measurements." in c.section().inner_text()
        assert c.engine()["live"] == 0  # the viewer is empty: no stage
        after = call(d_url, token, "/v1/wardrobe")
        assert after["rev"] == before["rev"] and after["pieces"] == before["pieces"]
        assert BLAZER_PHOTO in json.dumps(after)  # the wardrobe's own photos stay
    finally:
        c.close()
