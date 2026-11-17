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
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from r13_fakes_d import Picture
from r131_fakes import T, jpeg
from r131_fakes_d import WATCH_PHOTO, patched_door
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


# ---- set up through the fake server's own routes (no on-device check needed for these) ----------
def put_bytes(url: str, token: str, path: str, data: bytes) -> Any:
    req = urllib.request.Request(url + path, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "image/jpeg")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def with_photo_yes_and(url: str, token: str, kind: str, colour: str) -> dict[str, Any]:
    """His photo and YES kept, and one new garment: as if he had done it on an earlier day."""
    put_bytes(url, token, "/v1/seeme/photo", jpeg(600, 1200))
    call(url, token, "/v1/seeme/consent", {"typed": "YES", "template_version": "c2"})
    got: dict[str, Any] = put_bytes(
        url, token, f"/v1/seeme/garments?type={kind}&colour={colour}", jpeg(512, 512)
    )
    return got


def use(c: Page, words: str) -> None:
    row = seeme(c).locator(".hp-row", has_text=words).first
    row.get_by_role("button", name="Use this one").click()


def test_avt12_card_lists_his_pieces_sent_and_not_in_the_picture_with_their_thumbnails(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    with_photo_yes_and(d_url, token, "trousers", "black")  # pairs with his striped shirt
    c = ready(browser, d_url, token)

    def plus_a_watch(route: Any) -> None:  # a picture whose answer also names a piece left out
        r = route.fetch()
        pic = r.json()
        pic["not_sent"] = [{"piece": T.watch, "slot": "watch", "words": "grey watch",
                            "why": "not_a_garment", "photo": WATCH_PHOTO}]  # fmt: skip
        route.fulfill(response=r, json=pic)

    c.page.route("**/v1/seeme/pictures", plus_a_watch)
    try:
        use(c, "new black trousers")
        until(c.page, lambda: "With your navy shirt." in text(c), "the pairing")
        seeme(c).get_by_role("button", name="See it on me", exact=True).click()
        dlg = c.page.locator("dialog.bdialog.tr-dlg")
        until(c.page, lambda: "Make 1 picture?" in (dlg.text_content() or ""), "the confirm")
        dlg.get_by_role("button", name="Make the picture").click()
        until(c.page, lambda: "Generated 2D style preview" in text(c), "the picture")
        sent = seeme(c).locator(".tr-sent img.tr-thumb")
        until(c.page, lambda: sent.count() == 1, "his piece's thumbnail")
        assert sent.first.get_attribute("data-photo") == "wh_00000000b001"  # the shirt's front
        left = seeme(c).locator(".tr-notsent img.tr-thumb")
        assert left.count() == 1 and left.first.get_attribute("data-photo") == WATCH_PHOTO
        assert "Not in the picture: grey watch" in text(c)
        until(c.page, lambda: (sent.first.get_attribute("src") or "").startswith("data:image/"),
              "the thumbnail drawn")  # fmt: skip
    finally:
        c.close()


def test_d22_pairing_lists_every_piece_it_would_send_and_never_one_in_the_garments_slot(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    with_photo_yes_and(d_url, token, "shirt", "white")
    c = ready(browser, d_url, token)
    pairing = {"pieces": [{"piece": T.rain_jacket, "words": "navy jacket"},
                          {"piece": T.white, "words": "white shirt"}],
               "not_sent": [], "words": "With your navy jacket."}  # fmt: skip

    def pair(route: Any) -> None:
        gid = route.request.url.split("garment=", 1)[1]
        route.fulfill(json={**pairing, "garment": gid})

    c.page.route("**/v1/seeme/pair?*", pair)
    try:  # the festive look has no outer layer: the jacket is in none of its slots
        c.page.locator("#hpp-wardrobe .wd-plan").nth(1).get_by_role(
            "button", name="Show in 3D"
        ).click()
        until(c.page, lambda: drawn(c, 2), "the festive look")
        use(c, "a new white shirt")
        until(c.page, lambda: "With your navy jacket." in text(c), "the pairing")
        ticks = seeme(c).locator("label.wd-tick", has=c.page.locator("input[type='checkbox']"))
        shown = ticks.evaluate_all(
            "l => l.filter(x => x.querySelector('input').checked).map(x => x.textContent)"
        )
        assert any("navy jacket" in t for t in shown)  # shown, though not in this look
        assert not any("white shirt" in t for t in ticks.all_inner_texts())  # its own slot
        seeme(c).get_by_role("button", name="See it on me", exact=True).click()
        dlg = c.page.locator("dialog.bdialog.tr-dlg")
        until(c.page, lambda: "Make 1 picture?" in (dlg.text_content() or ""), "the confirm")
        [est] = [r for r in c.sent if "/v1/seeme/estimate" in r["url"]]
        assert est["url"].endswith("&pieces=" + T.rain_jacket)  # exactly what is shown
        dlg.get_by_role("button", name="Cancel").click()
        assert not c.posts("/v1/seeme/pictures")
    finally:
        c.close()


def test_seeme_settings_lower_the_limit_at_once_and_raise_it_only_after_the_rupees_are_shown(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = ready(browser, d_url, token)
    try:
        cap = seeme(c).locator("input[name='cap']")
        assert cap.input_value() == "300"
        cap.fill("200")
        seeme(c).get_by_role("button", name="Save the limit").click()
        until(c.page, lambda: c.posts("/v1/seeme/settings"), "lowered")
        assert json.loads(c.posts("/v1/seeme/settings")[0]["body"]) == {"cap_inr": 200}
        until(c.page, lambda: "Your limit is ₹200 a month, GST included." in text(c), "said")
        seeme(c).locator("input[name='cap']").fill("500")
        seeme(c).get_by_role("button", name="Save the limit").click()
        dlg = c.page.locator("dialog.bdialog.tr-dlg")
        until(c.page, lambda: "Raise your See it on me limit to ₹500 a month?" in (
            dlg.text_content() or ""), "the confirm")  # fmt: skip
        assert "about 56 pictures" in (dlg.text_content() or "")  # at the typical ₹8.90
        dlg.get_by_role("button", name="Cancel").click()
        assert len(c.posts("/v1/seeme/settings")) == 1  # Cancel sends nothing
        seeme(c).get_by_role("button", name="Save the limit").click()
        dlg.get_by_role("button", name="Raise the limit").click()
        until(c.page, lambda: len(c.posts("/v1/seeme/settings")) == 2, "raised")
        assert json.loads(c.posts("/v1/seeme/settings")[1]["body"]) == {
            "cap_inr": 500, "confirm_cost": True}  # fmt: skip
        until(c.page, lambda: call(d_url, token, "/v1/seeme")["month"]["cap_inr"] == 500, "kept")
        seeme(c).locator("button.bsw[aria-label='See it on me pictures']").click()
        until(c.page, lambda: "See it on me is off." in text(c), "off")
        assert json.loads(c.posts("/v1/seeme/settings")[2]["body"]) == {"on": False}
        assert seeme(c).locator("button.bsw[aria-label='See it on me pictures']").count() == 1
        assert c.errors == [] and c.csp_violations() == []
    finally:
        back = {"on": True, "cap_inr": 300, "confirm_cost": True}  # as before, for the next test
        call(d_url, token, "/v1/seeme/settings", back, method="PUT")
        c.close()
