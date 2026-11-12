# tests/browser/test_r11_1_c_photos.py -- R11.1 Part C in a browser (plan D0, D14, D15, D21-C): the
# real console with "Unnamed groups" in the Faces panel and a Photos import's progress line in the
# Connectors panel. /v1/facegroups*, /v1/faces* and /v1/connectors* are answered by the test (shapes:
# src/jarvis/api/fix_photos.py, api/faces.py, photos/api.py). Pins: at 1440x900 and 390x844, on Night
# and Day, both pieces pass the visual gate (tests/browser/ui_checks.py) with no JS error and no CSP
# violation; a group is a number and a photo count, never a picture; Name asks through the Faces
# panel's consent form and sends it with the CSRF header (someone already added sends their id
# only); Forget asks first and says "not done yet" until the laptop confirmed; the import line shows
# the server's words, steps on Continue, and Stop asks first. Review C-code H1: before sign-in the block
# asks the server nothing, even with both panels restored as open from the last visit. Review C-code M9:
# a Privacy "Face groups" delete while the laptop is away is shown as NOT done.
# ruff: noqa: E501  (the consent statements and the long page assertions, as tests/browser/test_faces.py)
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, MOCK_CONNECTORS, install_mocks

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser

VIEWPORTS = {"desktop": DESKTOP, "phone": PHONE}
SURFACES = ("night", "day")
SETTLE_MS = 700
A = "fp_3a9c12ab34cd"
G4, G7, G9 = "c_00000000000004", "c_00000000000007", "c_00000000000009"
HOSTILE = '<img src=x onerror="window.__pwned=1">'
STATEMENTS = {
    "version": "fc1",
    "adult": "<name> agreed that the camera at my home may recognise their face and greet them by name; their face pictures stay on my laptop; they can ask me to delete them at any time",
    "child": "<name> is under 18 and I am their parent or legal guardian (or have their parent's agreement)",
}
PERSON = {
    "id": A,
    "name": "Anjali",
    "relation": "friend",
    "child": False,
    "vip": False,
    "state": "enrolled",
    "consent_at": "2026-10-01T10:00:00+00:00",
    "consent_version": "fc1",
    "renewal_due": False,
    "pictures": 4,
    "laptop_code": A,
}


def until(page: Any, check: Any, what: str = "condition") -> None:
    """Poll from Python: Playwright's wait_for_function evals a string, which the CSP forbids."""
    for _ in range(100):
        if check():
            return
        page.wait_for_timeout(50)
    raise AssertionError("timed out waiting for " + what)


def _group(gid: str, n: int, photos: int) -> dict[str, Any]:
    return {"id": gid, "n": n, "photos": photos, "first": 1793000000, "last": 1794300000}


def _progress(status: str, photos: int, line: str, **more: Any) -> dict[str, Any]:
    base = {
        "status": status,
        "photos": photos,
        "total": 2000,
        "faces_found": 41,
        "unknown": 7,
        "skipped": 0,
        "over": 0,
        "line": line,
        "picker_uri": "",
        "recognised": [],
    }
    return {**base, **more}


class Fake:
    """A stateful stand-in for the three APIs the two pieces talk to."""

    def __init__(self, page: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.groups = [_group(G4, 4, 23), _group(G7, 7, 3), _group(G9, 9, 112)]
        self.laptop = "online"
        self.names_waiting = 0
        self.forgets_waiting = 0
        self.forget_done = True
        self.extra: dict[str, Any] = {}
        self.people = [dict(PERSON)]
        known = [{"name": "Anjali", "child": False}, {"name": "Mini", "child": True}]
        self.job = _progress("reading", 310, "310 of 2,000 read · 41 faces found", recognised=known)
        self.steps = 0
        for pattern in ("**/v1/facegroups", "**/v1/facegroups/**", "**/v1/faces", "**/v1/faces/**"):
            page.route(pattern, self.serve)
        page.route("**/v1/connectors", self.connectors)
        page.route("**/v1/connectors/photos/import", self.connectors)

    def _json(self, route: Any, status: int, body: Any) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def view(self) -> dict[str, Any]:
        return {
            "available": True,
            "reason": "",
            "laptop": self.laptop,
            "heard_at": "2026-11-12T04:30:00+00:00",
            "groups": self.groups,
            "strays": 5,
            "named": 1,
            "engine_ready": True,
            "folder": "on",
            "read": 1204,
            "keep_days": 90,
            "names_waiting": self.names_waiting,
            "forgets_waiting": self.forgets_waiting,
            "local_url": "http://localhost:8098/faces",
            **self.extra,
        }

    def connectors(self, route: Any) -> None:
        r = route.request
        if r.method == "GET":
            body = {**MOCK_CONNECTORS, "photos": {"connected": True, "reason": ""}}
            return self._json(route, 200, body)
        self.calls.append({"method": r.method, "path": urlsplit(r.url).path, "body": None})
        return self._json(route, 200, {**self.job, "unknown": [], "unknown_faces": 7})

    def serve(self, route: Any) -> None:
        r, path = route.request, urlsplit(route.request.url).path
        body = r.post_data_json if r.post_data else None
        self.calls.append(
            {
                "method": r.method,
                "path": path,
                "body": body,
                "csrf": r.headers.get("x-requested-with"),
            }
        )
        if path == "/v1/faces/local":
            return self._json(
                route, 200, {"url": "http://localhost:8098/faces", "laptop_online": True}
            )
        if path == "/v1/faces":
            return self._json(
                route,
                200,
                {
                    "available": True,
                    "people": self.people,
                    "total": len(self.people),
                    "limit": 30,
                    "statements": STATEMENTS,
                },
            )
        if path == "/v1/facegroups":
            return self._json(route, 200, {"part": "photos", "ready": "ready"})
        if path == "/v1/facegroups/groups":
            return self._json(route, 200, self.view())
        if path.endswith("/name"):
            return self._name(route, path.split("/")[4], body or {})
        if path.endswith("/forget"):
            return self._forget(route, path.split("/")[4])
        if path == "/v1/facegroups/import/step":
            self.steps += 1
            done = self.job["photos"] + 10
            self.job = _progress("reading", done, f"{done} of 2,000 read · 41 faces found")
            return self._json(route, 200, self.job)
        if path == "/v1/facegroups/import" and r.method == "DELETE":
            self.job = _progress("no_session", 0, "", total=0, faces_found=0, unknown=0)
            return self._json(route, 200, self.job)
        if path == "/v1/facegroups/import":
            return self._json(route, 200, self.job)
        return self._json(route, 404, {"error": "not_found", "detail": "no"})

    def _name(self, route: Any, gid: str, body: dict[str, Any]) -> None:
        if "person_id" not in body and body.get("confirm") is not True:
            words = "Tick the consent statement first: JARVIS names nobody without it."
            return self._json(route, 422, {"error": "consent_missing", "detail": words})
        self.groups = [g for g in self.groups if g["id"] != gid]
        if "person_id" not in body:
            self.people.append({**PERSON, "id": "fp_0000000000aa", "name": body["name"]})
        pid = body.get("person_id", "fp_0000000000aa")
        return self._json(route, 200, {"person_id": pid, "at_home": True, "contact_matched": False})

    def _forget(self, route: Any, gid: str) -> None:
        self.groups = [g for g in self.groups if g["id"] != gid]
        if not self.forget_done:
            self.forgets_waiting += 1
            self.laptop = "offline"
        left = len(self.groups) + 5
        return self._json(
            route, 200, {"done": self.forget_done, "forgotten": int(self.forget_done), "left": left}
        )

    def posts(self, suffix: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] != "GET" and c["path"].endswith(suffix)]


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(
    browser: Any, url: str, token: str, panel: str, *, vp: str = "desktop", surface: str = "night"
) -> tuple[Console, Fake]:
    c = Console(browser, url, token, VIEWPORTS[vp])
    install_mocks(c.page)
    fake = Fake(c.page)  # after the shared mocks: the newest route answers first
    c.open()
    if surface == "day":
        c.page.locator("#themeBtn").click()
        c.page.locator('label[for="jx-s-day"]').click()
        c.page.keyboard.press("Escape")
    assert c.page.locator("html").get_attribute("data-surface") == surface
    c.open_panel(panel)
    ready = "#fgList li.trow" if panel == "faces" else "#photosLine"
    c.page.locator(ready).first.wait_for()
    c.page.wait_for_timeout(SETTLE_MS)
    return c, fake


def _gate(c: Console, sel: str, vp: str, what: str) -> None:
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), f"{sel} is not in the page"
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


def _new_field_is_clean(c: Console, vp: str) -> None:
    """The naming dialog is the Faces panel's own (R3), unchanged; this part added one field to
    it, "Who is this?". The gate's probes are read for that field only: the dialog's title and
    its Cancel / OK row are R3's and do not pass the generic probes when measured open (see
    INTEGRATION-C.md, "Found on the way")."""
    who = c.page.locator("#facesWho")
    who.wait_for()
    c.page.wait_for_timeout(SETTLE_MS)  # the dialog's own entry, then every finite animation
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, "#facesDialog")
    found = [
        (kind, item)
        for kind, items in res.items()
        if isinstance(items, list)
        for item in items
        if "facesWho" in json.dumps(item) or "Who is this" in json.dumps(item)
    ]
    assert found == [], found
    assert c.page.get_by_label("Who is this?").count() == 1  # a visible label, before the control
    box, view = who.bounding_box(), VIEWPORTS[vp]
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= view["width"]
    if vp == "phone":
        assert box["height"] >= 44
    assert who.locator("option").all_inner_texts() == ["A new person", "Anjali"]


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_unnamed_groups_pass_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c, fake = _open(browser, server_url, token, "faces", vp=vp, surface=surface)
    try:
        fake.names_waiting, fake.forgets_waiting = 1, 2
        c.page.evaluate("window.JarvisFixes.parts.photos.refresh()")
        c.page.locator("#fgWaits").get_by_text("1 name waits").wait_for()
        _gate(c, "#p-faces", vp, f"faces/groups {vp} {surface}")
        text = c.page.locator("#facesGroups").inner_text()
        assert "UNNAMED GROUPS" in text.upper() and "Group 4" in text and "23 photos" in text
        assert "112 photos" in text and "First seen" in text and "3 to name" in text.lower()
        assert "http://localhost:8098/faces" in text and "forgotten after 90 days" in text
        assert "1,204 pictures read" in text and "not done until it confirms" in text
        c.page.get_by_role("button", name="Name group 4").click()
        _new_field_is_clean(c, vp)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_import_line_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c, _ = _open(browser, server_url, token, "connectors", vp=vp, surface=surface)
    try:
        _gate(c, "#p-connectors", vp, f"connectors/import {vp} {surface}")
        box = c.page.locator("#photosImport")
        assert "of 2,000 read" in box.inner_text() and "41 faces found" in box.inner_text()
        assert "under Unnamed groups" in box.inner_text()
        assert "Recognised: Anjali, a child from your family." in box.inner_text()  # never "Mini"
        c.page.get_by_role("button", name="Stop import").click()  # the two-step row, measured
        c.page.get_by_role("button", name="Keep importing").wait_for()
        _gate(c, "#p-connectors", vp, f"connectors/stop row {vp} {surface}")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_group_is_a_number_and_a_count_never_a_picture(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token, "faces")
    try:
        fake.groups = [_group(G4, 4, 23), {"id": HOSTILE, "n": 1, "photos": 1}, _group(G4, 5, 2)]
        c.page.evaluate("window.JarvisFixes.parts.photos.refresh()")
        until(c.page, lambda: c.page.locator("#fgList li.trow").count() == 1, "one valid row")
        section = c.page.locator("#facesGroups")
        assert section.locator("img, canvas, video, picture, svg").count() == 0
        assert c.page.evaluate("window.__pwned") is None
        fake.groups, fake.laptop = [], "offline"
        c.page.evaluate("window.JarvisFixes.parts.photos.refresh()")
        c.page.locator("#fgState").get_by_text("isn't reachable").wait_for()
        said = c.page.inner_text("#fgState")
        assert "this is what it last said (" in said and "Nov 2026" in said
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_naming_a_new_person_goes_through_the_consent_statement(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token, "faces")
    try:
        page = c.page
        page.get_by_role("button", name="Name group 4").click()
        page.locator("#facesWho").wait_for()
        assert "Who is group 4?" in page.inner_text("#facesDialog")
        page.fill("#facesName", "Ravi")
        assert page.inner_text("#facesStatement").startswith("Ravi agreed that the camera")
        page.click("#facesDialog button:has-text('Name')")  # no tick: the server's words are shown
        until(page, lambda: "Tick the consent" in page.inner_text("#fgNote"), "consent words")
        assert len(fake.groups) == 3 and page.locator("#fgList li.trow").count() == 3
        page.get_by_role("button", name="Name group 4").click()
        page.locator("#facesWho").wait_for()
        page.fill("#facesName", "Ravi")
        page.check("#facesConsent")
        page.click("#facesDialog button:has-text('Name')")
        until(page, lambda: page.locator("#fgList li.trow").count() == 2, "the group to go")
        post = fake.posts("/name")[-1]
        assert post["path"] == f"/v1/facegroups/groups/{G4}/name" and post["csrf"] == "JARVIS"
        assert post["body"] == {
            "name": "Ravi",
            "relation": "family",
            "child": False,
            "vip": False,
            "given_by": "self",
            "consent_version": "fc1",
            "confirm": True,
        }
        assert "now recognise this person" in page.inner_text("#fgNote")
        until(page, lambda: "Ravi" in page.inner_text("#facesList"), "the new person in Faces")
        # the browser logs the refused request (the 422 this test asked for) and nothing else
        assert [e for e in c.errors if "422" not in e or "/name" not in e] == []
        assert c.csp_violations() == []
    finally:
        c.close()


def test_a_child_is_named_with_a_guardians_yes(browser: Any, server_url: str, token: str) -> None:
    c, fake = _open(browser, server_url, token, "faces")
    try:
        page = c.page
        page.get_by_role("button", name="Name group 7").click()
        page.locator("#facesWho").wait_for()
        page.fill("#facesName", "Mini")
        page.check("#facesChild")
        assert "under 18" in page.inner_text("#facesStatement")
        page.check("#facesConsent")
        page.click("#facesDialog button:has-text('Name')")
        until(page, lambda: bool(fake.posts("/name")), "the request")
        body = fake.posts("/name")[-1]["body"]
        assert body["child"] is True and body["given_by"] == "parent_guardian"
    finally:
        c.close()


def test_someone_already_added_is_not_asked_for_consent_again(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token, "faces")
    try:
        page = c.page
        page.get_by_role("button", name="Name group 9").click()
        page.locator("#facesWho").wait_for()
        assert page.is_visible("#facesStatement")
        page.select_option("#facesWho", A)
        assert not page.is_visible("#facesStatement") and not page.is_visible("#facesConsent")
        page.click("#facesDialog button:has-text('Name')")
        until(page, lambda: bool(fake.posts("/name")), "the request")
        post = fake.posts("/name")[-1]
        assert post["path"] == f"/v1/facegroups/groups/{G9}/name"
        assert post["body"] == {"person_id": A}
    finally:
        c.close()


def test_forget_asks_first_and_is_done_only_when_the_laptop_confirmed(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token, "faces")
    try:
        page = c.page
        page.get_by_role("button", name="Forget group 7").click()
        page.locator("#facesDialog").get_by_text("photos themselves are not touched").wait_for()
        page.click("#facesDialog button:has-text('Cancel')")
        assert fake.posts("/forget") == [] and page.locator("#fgList li.trow").count() == 3
        page.get_by_role("button", name="Forget group 7").click()
        page.click("#facesDialog button:has-text('Forget')")
        until(page, lambda: "your laptop confirmed it" in page.inner_text("#fgNote"), "done")
        post = fake.posts("/forget")[-1]
        assert post["path"] == f"/v1/facegroups/groups/{G7}/forget" and post["csrf"] == "JARVIS"
        fake.forget_done = False  # the laptop went to sleep
        page.get_by_role("button", name="Forget group 4").click()
        page.click("#facesDialog button:has-text('Forget')")
        until(page, lambda: "Not done yet" in page.inner_text("#fgNote"), "the honest answer")
        page.locator("#fgWaits").get_by_text("not done until it confirms").wait_for()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_import_line_steps_on_continue_and_stop_asks_first(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token, "connectors")
    try:
        page = c.page
        assert "310 of 2,000 read" in page.inner_text("#photosLine")
        page.get_by_role("button", name="Continue now").click()
        until(page, lambda: "320 of 2,000 read" in page.inner_text("#photosLine"), "a step")
        assert fake.posts("/import/step")[-1]["csrf"] == "JARVIS"
        fake.job = _progress(
            "laptop_offline",
            320,
            "320 of 2,000 read · 41 faces found · paused: laptop not reachable",
        )
        page.get_by_role("button", name="Import chosen photos").click()  # the card's own button
        until(
            page, lambda: "paused: laptop not reachable" in page.inner_text("#photosLine"), "pause"
        )
        assert "carries on by itself when it is back" in page.inner_text("#photosHint")
        page.get_by_role("button", name="Stop import").click()
        assert not [x for x in fake.calls if x["method"] == "DELETE"]  # asked first
        page.get_by_role("button", name="Keep importing").click()
        page.get_by_role("button", name="Stop import").click()
        page.locator("#photosImport").get_by_role("button", name="Stop", exact=True).click()
        until(page, lambda: not page.is_visible("#photosImport"), "the line to go")
        assert [x["path"] for x in fake.calls if x["method"] == "DELETE"] == [
            "/v1/facegroups/import"
        ]
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_while_the_panel_is_open_the_import_steps_by_itself(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token, "connectors")
    try:
        c.page.wait_for_timeout(6000)  # one 5-second turn of the module's own timer
        assert fake.steps >= 1 and "of 2,000 read" in c.page.inner_text("#photosLine")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


# ---- review C-code H1: nothing is asked before sign-in -----------------------------------------------

RESTORE_OPEN = (
    "try { localStorage.setItem('jarvis_deck_v1', JSON.stringify("
    + json.dumps({"v": 1, "p": {"faces": {"open": True}, "connectors": {"open": True}}})
    + ")); } catch (e) {}"
)


def test_before_sign_in_the_block_asks_the_server_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.add_init_script(RESTORE_OPEN)  # last visit left Faces and Connectors open
        install_mocks(c.page)
        fake = Fake(c.page)
        c.page.goto(server_url + "/")
        c.page.locator("#tokIn").wait_for()  # the sign-in gate is up
        c.page.wait_for_timeout(1500)
        asked = [x["path"] for x in fake.calls if x["path"].startswith("/v1/facegroups")]
        assert asked == [], asked
        c.page.locator("#tokIn").fill(token)
        c.page.locator("#tokBtn").click()
        c.page.locator("#welcome").wait_for()
        until(
            c.page,
            lambda: any(x["path"] == "/v1/facegroups/groups" for x in fake.calls),
            "the groups to load once signed in",
        )
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_panel_says_what_could_not_be_read_and_which_names_were_lost(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token, "faces")
    try:
        fake.extra = {"skipped": 2, "names_lost": 1, "min_photos": 3, "store_ok": True}
        c.page.get_by_role("button", name="Forget group 7").click()  # any change reloads the list
        c.page.click("#facesDialog button:has-text('Forget')")
        until(c.page, lambda: "could not be read" in c.page.inner_text("#fgFolder"), "skipped")
        assert "2 files could not be read and were skipped" in c.page.inner_text("#fgFolder")
        assert "1 name could not be given: the group had gone" in c.page.inner_text("#fgWaits")
        fake.extra = {"store_ok": False}
        fake.forget_done = True
        c.page.get_by_role("button", name="Forget group 4").click()
        c.page.click("#facesDialog button:has-text('Forget')")
        until(c.page, lambda: "face store" in c.page.inner_text("#fgState"), "store state")
        assert "Nothing was deleted" in c.page.inner_text("#fgState")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


# ---- review C-code M9: a delete that waits for the laptop is shown as NOT done -------------------------


def test_a_privacy_delete_while_the_laptop_is_away_is_shown_as_not_done(
    browser: Any, server_url: str, token: str
) -> None:
    from test_privacy import STUB, Backend, cat

    from jarvis.facegroups.privacy import AS_HEARD, PENDING, PENDING_NOTE

    class Away(Backend):
        def handle(self, route: Any) -> None:
            if route.request.url.endswith("/delete"):  # the ask is kept; the laptop is away
                self.cats[0].update(note=PENDING, rev="rev-after")
            super().handle(route)

    row = cat("face_groups", section="Faces", label="Face groups", delete="confirm", note=AS_HEARD)
    be = Away([row])
    # R11.1 I1: the server says why rows are left (privacy.service.Deleted.pending)
    reply = {"deleted": 0, "category": "face_groups", "remaining": 2, "pending": PENDING_NOTE}
    be.delete_reply = (200, reply)
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.route("**/v1/privacy**", be.handle)
        c.open()
        c.page.evaluate(STUB)
        c.open_panel("privacy")
        c.page.locator("#pv-face_groups button", has_text="Delete").click()
        assert "finishes when it is back" in c.page.inner_text(".pv-dlg")  # said before the click
        c.page.locator("#pvGo").click()
        c.page.locator(".pv-dlg").wait_for(state="detached")
        note = c.page.locator("#pvNote")
        assert "bad" in str(note.get_attribute("class"))  # never the green "Deleted N."
        assert note.inner_text() == f"Face groups: {PENDING_NOTE}"  # not "Try again"
        until(c.page, lambda: "NOT done yet" in c.page.inner_text("#pv-face_groups"), "pending")
        assert c.errors == []
    finally:
        c.close()
