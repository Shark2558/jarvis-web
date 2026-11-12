# tests/browser/test_r11_1_b_files.py -- R11.1 Part B in a real browser against the real backend
# (mock brain): the file picker offers the new kinds from the script's own list (the page is
# unchanged); an Excel file, a deck and a zip attach and are read; a big picture is made smaller in
# the browser before it leaves; a picked folder goes up as ONE bundle of its readable files; a
# spoken message shows "Heard / Understood as" and sends the understood words with the heard ones
# beside them; an unsure one gets one question and is not sent; a costly reply shows its rupee
# estimate first and sends the chosen tier. The Conversation panel with all of it passes the visual
# gate at 1440x900 and 390x844, Night and Day, with no JS errors or CSP violations.
from __future__ import annotations

import base64
import io
import json
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r11_1_fakes_b import make_png, make_pptx, make_zip, study_plan_xlsx  # noqa: E402

from jarvis.documents.imagecheck import _jpeg_size  # noqa: E402

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ESTIMATE = {
    "show": True,
    "tier": "balanced",
    "inr": 13.86,
    "stronger_tier": "strong",
    "stronger_inr": 27.71,
    "suggest": "strong",
    "line": "About ₹14 on the balanced tier; about ₹28 on the stronger tier.",
}
SPEAK = (
    "(text, opts) => window.JarvisChat.send(text, Object.assign({ channel: 'voice' }, opts || {}))"
)
# A file or a folder bundle is sent as a Blob, whose bytes the browser does not show a test from
# outside: this keeps a copy of every upload's body and headers inside the page.
UPLOAD_SPY = """(() => {
  const real = window.fetch; window.__uploads = [];
  window.fetch = async function (url, opts) {
    try {
      const up = String(url).endsWith('/v1/attachments') && opts && opts.method === 'POST';
      if (up && opts.body && opts.body.arrayBuffer) {
        const buf = new Uint8Array(await opts.body.arrayBuffer()); let bin = '';
        for (let i = 0; i < buf.length; i += 0x8000) {
          bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        }
        const headers = {};
        Object.keys(opts.headers || {}).forEach((k) => {
          headers[k.toLowerCase()] = String(opts.headers[k]);
        });
        window.__uploads.push({ headers, b64: btoa(bin) });
      }
    } catch (_) {}
    return real.apply(this, arguments);
  };
})();"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Page(Console):
    """A console that remembers every upload and chat request it made."""

    def __init__(self, browser: Any, url: str, token: str, viewport: dict[str, int]) -> None:
        super().__init__(browser, url, token, viewport)
        self.chats: list[dict[str, Any]] = []
        self.page.add_init_script(UPLOAD_SPY)
        self.page.on("request", self._seen)

    def _seen(self, req: Any) -> None:
        if req.method == "POST" and req.url.endswith("/v1/chat"):
            self.chats.append(json.loads(req.post_data))

    @property
    def uploads(self) -> list[dict[str, Any]]:
        seen = self.page.evaluate("window.__uploads")
        return [{"headers": u["headers"], "body": base64.b64decode(u["b64"])} for u in seen]

    def attach(self, name: str, data: bytes, mime: str = "application/octet-stream") -> Any:
        self.page.locator("#attachInput").set_input_files(
            files=[{"name": name, "mimeType": mime, "buffer": data}]
        )
        chip = self.page.locator(
            '#attachChips .achip[data-state="ready"]', has_text=name.split(".")[0]
        )
        chip.wait_for(timeout=20_000)
        return chip

    def pretend_uploads(self, **counts: Any) -> None:
        """Answer every upload in the page itself (the server allows six a minute per owner):
        a waiting file with these counts. A chat that names such a file is sent on without it."""
        made: list[str] = []

        def upload(route: Any) -> None:
            if route.request.method != "POST":
                route.fulfill(status=204)
                return
            made.append("doc_" + f"{len(made):020x}")
            name = unquote(route.request.headers.get("x-jarvis-filename", "file.txt"))
            ref = {
                "id": made[-1], "name": name, "kind": "txt", "size": 70_000, "pages": None,
                "words": 10_000, "chars": 70_000, "truncated": False, "sheets": None, "rows": None,
                "slides": None, "files": None, "skipped": 0, "pictures": 0, **counts,
            }  # fmt: skip
            route.fulfill(status=201, content_type="application/json", body=json.dumps(ref))

        def chat(route: Any) -> None:
            body = json.loads(route.request.post_data)
            body.pop("attachments", None)
            route.continue_(post_data=json.dumps(body))

        self.page.route("**/v1/attachments**", upload)
        self.page.route("**/v1/chat", chat)

    def speak(self, text: str, **opts: Any) -> None:
        self.page.evaluate(f"([t, o]) => ({SPEAK})(t, o)", [text, opts])

    def reply(self, nth: int = 0) -> str:
        row = self.page.locator(".row.jarvis .bubble:not(.typing)").nth(nth)
        row.wait_for()
        return str(row.text_content())


@pytest.fixture
def console(browser: Any, server_url: str, token: str) -> Iterator[Page]:
    c = Page(browser, server_url, token, DESKTOP)
    c.open()
    c.page.wait_for_function("window.JarvisFixes && window.JarvisFixes.parts.files")
    yield c
    c.close()


def _clean(c: Page) -> None:
    assert c.errors == [] and c.csp_violations() == []


# ---- the picker and the new kinds ----------------------------------------------------------------


def test_the_picker_offers_the_new_kinds_from_the_scripts_own_list(console: Page) -> None:
    accept = str(console.page.locator("#attachInput").get_attribute("accept"))
    for ext in (".pdf", ".xlsx", ".xlsm", ".xls", ".pptx", ".png", ".jpg", ".zip"):
        assert ext in accept.split(","), ext
    title = str(console.page.locator("#attachBtn").get_attribute("title"))
    assert "Excel" in title and "up to 10 files" in title and "10 MB each" in title
    folder = console.page.locator("#attachFolderBtn")
    assert folder.is_visible() and folder.get_attribute("aria-label") == "Attach a folder"
    _clean(console)


def test_an_excel_file_a_deck_and_a_zip_attach_and_are_read(console: Page) -> None:
    sheet = console.attach("Study plan.xlsx", study_plan_xlsx(60), XLSX)
    assert "2 sheets · 63 rows" in str(sheet.locator(".ameta").text_content())
    deck = console.attach("Pitch.pptx", make_pptx([(["Made-up pitch"], []), (["Two"], [])]))
    assert "2 slides" in str(deck.locator(".ameta").text_content())
    packed = console.attach("bundle.zip", make_zip({"a.txt": b"alpha words", "x.gif": b"GIF89a"}))
    assert "1 file, 1 not read" in str(packed.locator(".ameta").text_content())
    reply = console.send("What is in these?")  # the mock brain echoes what it was given
    assert "Sheet 1 of 2: Plan" in reply and "Made-up pitch" in reply and "alpha words" in reply
    assert len(console.chats[-1]["attachments"]) == 3
    assert console.page.locator(".row.user .meta .afile").count() == 3
    _clean(console)


def test_a_big_picture_is_made_smaller_before_it_leaves_the_browser(console: Page) -> None:
    big = make_png(3000, 2000, text=b"GPS-LAT-12.97-LON-77.59")
    chip = console.attach("Board photo.png", big, "image/png")
    assert "picture" in str(chip.locator(".ameta").text_content())
    (up,) = console.uploads
    body = up["body"]
    assert body.startswith(b"\xff\xd8\xff") and b"GPS-LAT" not in body
    assert _jpeg_size(body) == (1568, 1045)
    assert unquote(up["headers"]["x-jarvis-filename"]) == "Board photo.jpg"
    assert len(body) < 900 * 1024 and "Board photo.jpg" in str(chip.text_content())
    same = console.page.evaluate(
        """async (b64) => {
          const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
          const file = new File([bytes], 'icon.png', { type: 'image/png' });
          return (await window.JarvisFixes.parts.files.shrink(file)) === file;
        }""",
        base64.b64encode(make_png(16, 16)).decode(),
    )
    assert same is True  # small enough already: it goes as it is (the server cleans it)
    _clean(console)


def test_a_folder_goes_up_as_one_bundle_of_its_readable_files(
    console: Page, tmp_path: Path
) -> None:
    root = tmp_path / "My plans"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("alpha plan words", encoding="utf-8")
    (root / "sub" / "b.csv").write_text("k,v\n1,2\n", encoding="utf-8")
    (root / "logo.gif").write_bytes(b"GIF89a")
    (root / "inner.zip").write_bytes(make_zip({"x.txt": b"x"}))
    (root / ".hidden.txt").write_text("not for anyone", encoding="utf-8")
    console.page.locator("#attachFolderInput").set_input_files(str(root))
    chip = console.page.locator('#attachChips .achip[data-state="ready"]', has_text="My plans")
    chip.wait_for(timeout=20_000)
    assert "2 files" in str(chip.locator(".ameta").text_content())
    (up,) = console.uploads
    assert up["headers"]["x-jarvis-folder"] == "1"
    assert unquote(up["headers"]["x-jarvis-filename"]) == "My plans"
    with zipfile.ZipFile(io.BytesIO(up["body"])) as zf:
        assert zf.testzip() is None and zf.namelist() == ["a.txt", "sub/b.csv"]
        assert zf.read("a.txt") == b"alpha plan words"
    said = str(console.page.locator("#attachErr").text_content())
    assert "logo.gif (not a kind JARVIS reads)" in said
    assert "inner.zip (an archive inside a folder is never opened)" in said and "hidden" not in said
    assert "alpha plan words" in console.send("What do the plans say?")
    _clean(console)


# ---- heard / understood as -----------------------------------------------------------------------


def test_heard_and_understood_as_show_under_a_spoken_message(console: Page) -> None:
    console.speak("Tu D calender", alternatives=["to the calendar"], confidence=0.71)
    console.reply()
    row = console.page.locator(".row.user").first
    assert row.locator(".bubble").text_content() == "To the calendar"
    lines = [str(t) for t in row.locator(".r111f-heard .bfine").all_text_contents()]
    assert lines == ["Heard: Tu D calender", "Understood as: To the calendar"]
    (chat,) = console.chats
    assert (chat["message"], chat["heard"], chat["channel"]) == (
        "To the calendar",
        "Tu D calender",
        "voice",
    )
    console.page.reload()  # the stored turn still shows what was heard (display only)
    console.page.locator(".row.user .r111f-heard").wait_for()
    again = console.page.locator(".row.user .r111f-heard .bfine").all_text_contents()
    assert list(again) == lines
    _clean(console)


def test_words_heard_right_show_no_extra_line(console: Page) -> None:
    console.speak("What is on my calendar tomorrow?")
    console.reply()
    assert console.page.locator(".r111f-heard").count() == 0
    assert "heard" not in console.chats[0] and console.chats[0]["channel"] == "voice"
    _clean(console)


def test_an_unsure_spoken_message_gets_one_question_and_is_not_sent(console: Page) -> None:
    console.speak("add it 2 the calendar")
    assert console.reply() == "Did you mean “add it to the calendar”, Sir?"
    assert console.chats == []  # nothing reached the Brain
    user = console.page.locator(".row.user").first
    assert user.locator(".bubble").text_content() == "add it 2 the calendar"
    assert "Not sent" in str(user.locator(".meta").text_content())
    _clean(console)


# ---- the rupee estimate before a costly reply ----------------------------------------------------


def _long_file(c: Page, chars: int = 70_000) -> None:
    c.attach("long notes.txt", ("made-up words " * (chars // 14)).encode(), "text/plain")


def test_a_costly_reply_shows_its_estimate_and_sends_the_chosen_tier(console: Page) -> None:
    asked: list[dict[str, Any]] = []

    def estimate(route: Any) -> None:
        asked.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", body=json.dumps(ESTIMATE))

    console.page.route("**/v1/input/estimate", estimate)
    console.pretend_uploads()
    _long_file(console)
    console.page.locator("#input").fill("Summarise it")
    console.page.locator("#send").click()
    box = console.page.locator("#r111fCost")
    box.wait_for()
    assert ESTIMATE["line"] in str(box.text_content()) and "$" not in str(box.text_content())
    assert console.chats == [] and asked[0]["message"] == "Summarise it"
    assert asked[0]["attachments"] == ["doc_" + "0" * 20]
    strong = box.get_by_role("button", name="Send on the stronger tier")
    assert "primary" in str(strong.get_attribute("class"))  # the tier it suggests
    assert (
        console.page.evaluate("document.activeElement.textContent") == "Send on the stronger tier"
    )
    strong.click()
    console.reply()
    (chat,) = console.chats
    assert chat["tier"] == "strong" and chat["message"] == "Summarise it"
    assert chat["attachments"] == ["doc_" + "0" * 20]
    assert console.page.locator("#r111fCost").count() == 0
    _clean(console)


def test_cancel_puts_the_words_back_and_sends_nothing(console: Page) -> None:
    console.page.route(
        "**/v1/input/estimate",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(ESTIMATE)),
    )
    console.pretend_uploads()
    _long_file(console)
    console.page.locator("#input").fill("Summarise it")
    console.page.locator("#send").click()
    console.page.locator("#r111fCost").get_by_role("button", name="Cancel").click()
    assert console.page.locator("#input").input_value() == "Summarise it"
    assert console.chats == [] and console.page.locator("#r111fCost").count() == 0
    assert console.page.locator("#attachChips .achip").count() == 1  # the file is still waiting
    _clean(console)


def test_below_five_rupees_nothing_is_shown_and_the_message_just_goes(console: Page) -> None:
    # the real backend and its real estimate: 45,000 characters is large enough to ask about and
    # comes to about four rupees on the balanced tier, so nothing is shown
    _long_file(console, 45_000)
    with console.page.expect_response("**/v1/input/estimate") as seen:
        reply = console.send("Summarise it")
    answer = seen.value.json()
    assert answer["show"] is False and answer["line"] == "" and 3.5 < answer["inr"] < 5
    assert "made-up words" in reply and console.page.locator("#r111fCost").count() == 0
    assert "tier" not in console.chats[0]
    _clean(console)


# ---- the visual gate -----------------------------------------------------------------------------


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_conversation_with_all_of_it_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c = Page(browser, server_url, token, DESKTOP if vp == "desktop" else PHONE)
    try:
        c.open()
        c.page.wait_for_function("window.JarvisFixes && window.JarvisFixes.parts.files")
        if surface == "day":
            c.page.locator("#themeBtn").click()
            c.page.locator('label[for="jx-s-day"]').click()
            c.page.keyboard.press("Escape")
        c.page.route(
            "**/v1/input/estimate",
            lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(ESTIMATE)
            ),
        )
        c.speak("Add D csb file Tu D calender")  # a "Heard / Understood as" row in the thread
        c.reply()
        c.speak("add it 2 the calendar")  # ... and a question that was asked first
        c.reply(1)
        c.pretend_uploads(kind="xlsx", sheets=2, rows=63)
        c.attach("Study plan for the made-up certification 2027.xlsx", study_plan_xlsx(3), XLSX)
        _long_file(c)
        c.page.locator("#input").fill("Summarise these")
        c.page.locator("#send").click()
        c.page.locator("#r111fCost").wait_for()  # the cost line with its three choices
        assert c.page.locator("#attachFolderBtn").is_visible() == (vp == "desktop")
        c.page.wait_for_timeout(600)
        c.page.evaluate(FINISH_ANIMATIONS_JS)
        sel = "#p-chat"
        res = c.page.evaluate(DOM_CHECKS_JS, sel)
        _assert_clean(
            res,
            c.page.evaluate(NAMELESS_JS, sel),
            c.page.evaluate(WRAP_JS, sel),
            vp,
            f"files {vp} {surface}",
        )
        widths = c.page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert widths[0] <= widths[1], widths
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
