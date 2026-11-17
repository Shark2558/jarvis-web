# tests/browser/test_r131_d_seeme.py -- R13.1 Part D: "See it on me" for a garment he is thinking
# of buying, in a real Chromium (docs/plans/r13-1-try-on.md D11-D13, D22; BRIEF-D section 3):
#   - D22: the garment's type and colour come from fixed lists (no free text, no web address); a
#     photo with a face is refused on the device and nothing is sent; a picture shared in waits
#     for his type and colour and that press sends nothing
#   - his photo: one person passes (the real SSD and UltraFace on a drawn figure), two are refused
#   - AVT-12: YES typed once (anything else changes nothing), the estimate's .bdialog (Cancel
#     sends NOTHING), Make the picture posts exactly {garment, pieces, confirm_cost, inr_shown,
#     request_id}; the picture says "Generated 2D style preview", the new garment "not in your
#     wardrobe" and his pieces sent; the catalog is unchanged
# The door is served with INTEGRATION-D's three proposed lines (r131_fakes_d.patched_door). Drawn
# pictures only (r13_fakes_d.Picture): never a photo of anyone.
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from r13_fakes_d import Picture
from r131_fakes import T
from r131_fakes_d import patched_door
from test_r131_d_card import Page, browser, call, d_url, drawn, reset, until

from jarvis.wardrobe.model import COLOURS
from jarvis.wardrobe.tryon.model import NEW_TYPES

__all__ = ["browser", "d_url"]
pytestmark = pytest.mark.browser
SLOW_S = 120.0  # the on-device models load once a page (ORT, 9.5 MB)


def seeme(c: Page) -> Any:
    return c.section().locator(".tr-me")


def ready(browser: Any, url: str, token: str, **kw: Any) -> Page:
    c = Page(browser, url, token, **kw)
    c.page.route("**/static/console-r7-send.js*", lambda r: r.fulfill(
        body=patched_door(), content_type="application/javascript"))  # fmt: skip
    c.open()
    c.wardrobe()
    until(c.page, lambda: drawn(c), "the section's figure")
    until(c.page, lambda: "Your photo" in seeme(c).inner_text(), "See it on me")
    return c


def png(tmp: Path, name: str, pic: Picture) -> str:
    path = tmp / f"{name}.png"
    path.write_bytes(pic.png())
    return str(path)


def me_alone() -> Picture:  # one drawn figure, head to feet
    return Picture(480, 720, (205, 220, 240)).figure(240, 40, 2.2)


def a_shirt() -> Picture:  # a shirt laid flat: no person, no face
    return Picture(640, 480, (232, 228, 220)).shirt(220, 100, 1.0)


def text(c: Page) -> str:
    return str(seeme(c).inner_text())


def add_photo(c: Page, path: str) -> None:
    seeme(c).locator("#trMyPhoto").set_input_files(path)


def add_garment(c: Page, path: str, kind: str = "shirt", colour: str = "navy") -> None:
    seeme(c).locator("#trGarment").set_input_files(path)
    until(c.page, lambda: seeme(c).locator("select[aria-label='What it is']").count() == 1, "lists")
    seeme(c).locator("select[aria-label='What it is']").select_option(kind)
    seeme(c).locator("select[aria-label='Its colour']").select_option(colour)
    seeme(c).get_by_role("button", name="Check and add this garment").click()


def test_d22_garment_type_and_colour_come_from_lists_and_a_face_is_refused(
    browser: Any, d_url: str, token: str, tmp_path: Path
) -> None:
    reset(d_url, token)
    c = ready(browser, d_url, token)
    try:
        assert seeme(c).locator("input[type='url'], input[type='text']").count() == 0  # no address
        seeme(c).locator("#trGarment").set_input_files(png(tmp_path, "shirt", a_shirt()))
        until(c.page, lambda: seeme(c).locator("select").count() == 2, "the two lists")
        kinds = seeme(c).locator("select[aria-label='What it is'] option")
        assert kinds.evaluate_all("l => l.map(o => o.value)") == list(NEW_TYPES)
        colours = seeme(c).locator("select[aria-label='Its colour'] option")
        assert colours.evaluate_all("l => l.map(o => o.value)") == list(COLOURS)
        seeme(c).get_by_role("button", name="Cancel").click()
        face = Picture(640, 480, (120, 150, 170)).face(320, 220, 200).shirt(200, 330, 0.6)
        add_garment(c, png(tmp_path, "model", face))
        words = "This photo shows a person: crop it to the garment"
        until(c.page, lambda: words in text(c), "the face refused", SLOW_S)
        assert not c.posts("/v1/seeme/garments")  # nothing sent
        assert call(d_url, token, "/v1/seeme/garments")["garments"] == []
    finally:
        c.close()


def test_d22_garment_a_shared_picture_waits_for_his_words_and_that_press_sends_nothing(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token)
    try:
        c.open()
        c.page.evaluate(
            """async () => {
              const bytes = new Uint8Array([255, 216, 255, 217]);
              const f = new File([bytes], 'shop.jpg', { type: 'image/jpeg' });
              await window.JarvisTryOnCard.garment(f);
            }"""
        )
        until(c.page, lambda: c.section().locator(".tr-me select").count() == 2, "the lists", 60)
        assert c.page.locator("#hpp-wardrobe").is_visible()
        assert not c.posts("/v1/seeme")  # the hand-over itself sent nothing
        assert "shop.jpg" not in c.page.locator("#p-helpers").inner_text()  # never its file name
    finally:
        c.close()


def test_seeme_his_photo_one_person_passes_and_two_are_refused(
    browser: Any, d_url: str, token: str, tmp_path: Path
) -> None:
    reset(d_url, token)
    c = ready(browser, d_url, token)
    try:
        two = Picture(640, 480, (205, 220, 240)).figure(200, 40, 1.4).figure(440, 40, 1.4)
        add_photo(c, png(tmp_path, "two", two))
        until(c.page, lambda: "This photo should show only you." in text(c), "refused", SLOW_S)
        assert not c.posts("/v1/seeme/photo")
        add_photo(c, png(tmp_path, "me", me_alone()))
        until(c.page, lambda: "Your photo is kept, sealed." in text(c), "sent", SLOW_S)
        assert len(c.posts("/v1/seeme/photo")) == 1
        assert "can’t tell an adult from a child" in text(c)
        assert call(d_url, token, "/v1/seeme")["photo"]["kept"] is True
    finally:
        c.close()


def test_avt12_card_the_picture_is_a_labelled_2d_preview_of_a_new_garment_with_his_pieces(
    browser: Any, d_url: str, token: str, tmp_path: Path
) -> None:
    reset(d_url, token)
    before = call(d_url, token, "/v1/wardrobe")
    c = ready(browser, d_url, token)
    try:
        add_photo(c, png(tmp_path, "me", me_alone()))
        until(c.page, lambda: "Your photo is kept, sealed." in text(c), "his photo", SLOW_S)
        add_garment(c, png(tmp_path, "shirt", a_shirt()))
        until(c.page, lambda: "a new navy shirt, not in your wardrobe" in text(c), "added", SLOW_S)
        assert "With your charcoal trousers." in text(c)
        tick = seeme(c).locator("input[type='checkbox'][data-slot='bottom']")
        assert tick.is_checked()
        go = seeme(c).get_by_role("button", name="See it on me", exact=True)
        go.click()  # first: his YES, typed
        dlg = c.page.locator("dialog.bdialog.tr-dlg")
        dlg.wait_for()
        assert "Gemini 3.1 Flash Image, processed in the United States" in (
            dlg.text_content() or ""
        )
        dlg.locator("input").fill("yes")
        dlg.get_by_role("button", name="Agree").click()
        until(c.page, lambda: "Type YES in capitals" in text(c), "lower case refused")
        assert call(d_url, token, "/v1/seeme")["consent"]["given"] is False
        go.click()
        dlg.locator("input").fill("YES")
        dlg.get_by_role("button", name="Agree").click()
        until(
            c.page,
            lambda: "Make 1 picture?" in (dlg.text_content() or ""),
            "the estimate's confirm",
        )
        assert "₹8.90 with GST is typical" in (dlg.text_content() or "")
        assert "charcoal trousers" in (dlg.text_content() or "")
        dlg.get_by_role("button", name="Cancel").click()
        until(c.page, lambda: "Nothing was sent." in text(c), "cancelled")
        assert not c.posts("/v1/seeme/pictures")  # Cancel sends NOTHING
        go.click()
        until(c.page, lambda: "Make 1 picture?" in (dlg.text_content() or ""), "the confirm again")
        dlg.get_by_role("button", name="Make the picture").click()
        until(c.page, lambda: "Generated 2D style preview" in text(c), "the picture")
        [sent] = c.posts("/v1/seeme/pictures")
        body = json.loads(sent["body"])
        assert set(body) == {"garment", "pieces", "confirm_cost", "inr_shown", "request_id"}
        assert re.fullmatch(r"tg_[0-9a-f]{12}", body["garment"]) and body["pieces"] == [T.trousers]
        assert body["confirm_cost"] is True and body["inr_shown"] == 8.9
        assert re.fullmatch(r"tq_[0-9a-f]{16}", body["request_id"])
        t = text(c)
        assert "Generated 2D style preview — not a photo; the fit is not exact" in t
        assert "a new navy shirt, not in your wardrobe" in t and "₹8.52 with GST" in t
        assert "Your pieces in it: charcoal trousers." in t
        assert "Google adds Content Credentials (C2PA)" in t
        pic = seeme(c).locator("img.tr-pic").last
        until(c.page, lambda: (pic.get_attribute("src") or "").startswith("data:image/"), "shown")
        seeme(c).get_by_role("button", name="Keep", exact=True).click()
        until(c.page, lambda: c.posts("/keep"), "Keep")
        after = call(d_url, token, "/v1/wardrobe")
        assert after["rev"] == before["rev"] and after["pieces"] == before["pieces"]  # never his
        refused = "the server responded with a status of 422"  # the lower-case "yes", by design
        assert [e for e in c.errors if refused not in e] == [] and c.csp_violations() == []
    finally:
        c.close()
