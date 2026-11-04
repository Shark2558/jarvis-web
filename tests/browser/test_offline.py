# tests/browser/test_offline.py -- R1 C in a real browser: Integrations -> Offline mode and the
# reply marker. The page is the real console and the real server, with its real console-offline
# tags (R1 I1); /v1/offline* is answered by the test (page.route).
# Covers: the steps and the form when nothing is set up; Save sends url + key + model through the
# console's transport with the CSRF header and empties the key field; Test shows the plain-words
# result; the On switch says On / Off in words; Remove asks first; a server without the feature says
# so; the marker "Offline mode - answered by your laptop (model)" appears only when the reply says
# offline, hostile model names stay text; the Vitals line; a 390 px phone has no horizontal scroll.
# 0 JS errors and 0 CSP reports throughout.
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
HOST = "my-laptop.tail1234.ts.net"
KEY = "Zk3y-laptop-secret-0123456789abcdef"
HOSTILE = '<img src=x onerror="window.__pwned=1">'


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Fake:
    """The test's /v1/offline: a tiny stateful stand-in for the real service."""

    def __init__(self, *, available: bool = True) -> None:
        self.s: dict[str, Any] = {
            "available": available,
            "configured": False,
            "enabled": False,
            "host": None,
            "model": None,
            "state": "off",
            "last_ok_at": None,
            "last_used_at": None,
        }
        self.puts: list[dict[str, Any]] = []
        self.deletes = 0
        self.tests = 0

    def view(self) -> str:
        return json.dumps(self.s)

    def attach(self, page: Any) -> None:
        def main(route: Any) -> None:
            req = route.request
            if req.method == "GET":
                return route.fulfill(status=200, content_type="application/json", body=self.view())
            if req.method == "PUT":
                body = req.post_data_json
                self.puts.append({"body": body, "csrf": req.headers.get("x-requested-with")})
                if "url" in body:
                    self.s.update(configured=True, host=HOST)
                if "model" in body:
                    self.s["model"] = body["model"]
                if "enabled" in body:
                    self.s["enabled"] = body["enabled"]
                self.s["state"] = "standby" if self.s["enabled"] else "off"
                return route.fulfill(status=200, content_type="application/json", body=self.view())
            if req.method == "DELETE":
                self.deletes += 1
                self.s.update(configured=False, enabled=False, host=None, model=None, state="off")
                return route.fulfill(status=200, content_type="application/json", body=self.view())
            return route.fallback()

        def test(route: Any) -> None:
            self.tests += 1
            self.s["last_ok_at"] = "2026-11-05T09:00:00+00:00"
            body = {
                "ok": True,
                "models": [self.s["model"]],
                "detail": f"Your laptop answered (model {self.s['model']}).",
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        page.route("**/v1/offline", main)
        page.route("**/v1/offline/test", test)


def _console(
    browser: Any, server_url: str, token: str, fake: Fake, viewport: dict[str, int]
) -> Console:
    c = Console(browser, server_url, token, viewport)
    fake.attach(c.page)
    c.open()
    return c


def test_set_up_test_switch_on_and_remove(browser: Any, server_url: str, token: str) -> None:
    fake = Fake()
    c = _console(browser, server_url, token, fake, DESKTOP)
    try:
        c.open_panel("integrations")
        sec = c.page.locator("#offlineSet")
        sec.wait_for()
        c.page.locator("#offlineForm").wait_for()
        assert "Off" in str(sec.locator(".istate").text_content())
        steps = c.page.locator("#offlineSteps li").all_text_contents()
        assert len(steps) == 4 and "Ollama" in steps[0] and "start-unix.sh" in steps[2]
        # Save: url + key + model, through the console's transport, key field emptied
        c.page.locator("#offlineUrl").fill(f"https://{HOST}")
        c.page.locator("#offlineKey").fill(KEY)
        c.page.locator("#offlineModel").fill("qwen2.5:7b")
        assert c.page.locator("#offlineKey").get_attribute("type") == "password"
        c.page.locator("#offlineSave").click()
        c.page.locator("#offlineStatus").wait_for()
        assert fake.puts[-1]["body"] == {
            "url": f"https://{HOST}",
            "key": KEY,
            "model": "qwen2.5:7b",
        }
        assert fake.puts[-1]["csrf"] == "JARVIS"
        body = str(sec.text_content())
        assert HOST in body and "qwen2.5:7b" in body and KEY not in body
        assert "Switched off" in str(c.page.locator("#offlineStatus").text_content())
        assert KEY not in c.page.content()
        # Test: plain words
        c.page.locator("#offlineTestBtn").click()
        c.page.locator(
            "#offlineTest", has_text="Your laptop answered (model qwen2.5:7b)."
        ).wait_for()
        assert fake.tests == 1
        # the switch says On / Off in words
        sw = c.page.locator("#offlineSwitch")
        assert (
            sw.get_attribute("aria-pressed") == "false"
            and sw.locator(".st").text_content() == "Off"
        )
        sw.click()
        c.page.locator('#offlineSwitch[aria-pressed="true"]').wait_for()
        assert c.page.locator("#offlineSwitch .st").text_content() == "On"
        assert fake.puts[-1]["body"] == {"enabled": True}
        assert "Standby" in str(sec.locator(".istate").text_content())
        # Remove asks first; Not now keeps it, Remove forgets it
        c.page.locator("#offlineRemove").click()
        c.page.locator("#offlineDialog[open]").wait_for()
        assert c.page.evaluate("document.activeElement.id") == "offlineDialogNo"
        c.page.locator("#offlineDialogNo").click()
        assert fake.deletes == 0 and c.page.locator("#offlineDialog").count() == 0
        c.page.locator("#offlineRemove").click()
        c.page.locator("#offlineDialogYes").click()
        c.page.locator("#offlineForm").wait_for()
        assert fake.deletes == 1
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_server_error_is_shown_in_plain_words(browser: Any, server_url: str, token: str) -> None:
    fake = Fake()
    c = _console(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.route(
            "**/v1/offline",
            lambda r: (
                r.fulfill(
                    status=422,
                    content_type="application/json",
                    body=json.dumps(
                        {"error": "invalid_url", "detail": "The address must start with https://."}
                    ),
                )
                if r.request.method == "PUT"
                else r.fallback()
            ),
        )
        c.open_panel("integrations")
        c.page.locator("#offlineForm").wait_for()
        c.page.locator("#offlineUrl").fill("http://10.0.0.5")
        c.page.locator("#offlineSave").click()
        c.page.locator("#offlineNote", has_text="must start with https://").wait_for()
        assert c.page.locator("#offlineForm").count() == 1  # still there to fix
    finally:
        c.close()


def test_a_server_without_the_feature_says_so(browser: Any, server_url: str, token: str) -> None:
    fake = Fake(available=False)
    c = _console(browser, server_url, token, fake, DESKTOP)
    try:
        c.open_panel("integrations")
        sec = c.page.locator("#offlineSet")
        sec.locator(".warn").wait_for()
        assert "Not available" in str(sec.locator(".istate").text_content())
        assert "token key" in str(sec.locator(".warn").text_content())
        assert c.page.locator("#offlineForm").count() == 0
    finally:
        c.close()


MARK_JS = "([id, resp]) => window.JarvisOffline.mark(document.getElementById(id), resp)"
ROWS_JS = """() => {
  for (const id of ['row1', 'row2']) {
    const n = document.createElement('div'); n.id = id; document.body.appendChild(n);
  }
  document.getElementById('row1').textContent = 'Two meetings today.';
}"""
MARKER = "Offline mode \u2014 answered by your laptop"


def test_the_reply_marker_and_the_vitals_line(browser: Any, server_url: str, token: str) -> None:
    fake = Fake()
    fake.s.update(configured=True, enabled=True, host=HOST, model="qwen2.5:7b", state="standby")
    c = _console(browser, server_url, token, fake, DESKTOP)
    try:
        c.open_panel("vitals")  # the real #vOffline line lives in Vitals
        c.page.evaluate(ROWS_JS)
        c.page.evaluate("window.JarvisOffline.refresh()")
        c.page.locator("#vOffline", has_text="Offline mode: standby").wait_for()
        reply = {"offline": True, "model": "qwen2.5:7b"}
        assert c.page.evaluate(MARK_JS, ["row1", reply]) is True
        assert c.page.locator("#row1 .offmark").text_content() == MARKER + " (qwen2.5:7b)"
        c.page.evaluate(MARK_JS, ["row1", reply])  # once only
        assert c.page.locator("#row1 .offmark").count() == 1
        c.page.locator("#vOffline", has_text="Offline mode: active").wait_for()
        # not offline -> no marker; a hostile model name stays text and is not shown
        assert c.page.evaluate(MARK_JS, ["row2", {"offline": False}]) is False
        assert c.page.locator("#row2 .offmark").count() == 0
        c.page.evaluate(MARK_JS, ["row2", {"offline": True, "model": HOSTILE}])
        assert c.page.locator("#row2 .offmark").text_content() == MARKER
        assert c.page.evaluate("window.__pwned") is None
        assert c.page.locator("#row2 img").count() == 0
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_phone_has_no_horizontal_scroll(browser: Any, server_url: str, token: str) -> None:
    fake = Fake()
    c = _console(browser, server_url, token, fake, PHONE)
    try:
        c.open_panel("integrations")
        c.page.locator("#offlineForm").wait_for()
        assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        inp = c.page.locator("#offlineUrl").bounding_box()
        assert inp is not None and inp["height"] >= 44
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
