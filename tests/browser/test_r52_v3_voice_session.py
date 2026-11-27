# tests/browser/test_r52_v3_voice_session.py -- R5.2 V3 (docs/plans/r5-2-voice.md 3.3): Voice ->
# "Your voice" and the voice session pop-up in a real browser, on a fake microphone. The
# /v1/voice/profile routes are mocked with page.route (I1 wires the real ones); the module and its
# stylesheet are the ones console-r7.js loads and the /static allow-list serves. The main path:
# start, record the lines (each clip a WAV), a break between blocks, the rupee question mid-session
# answered with a typed YES (the refused clip is sent again), score, the results, then "Delete my
# recordings" after a confirm. Text meets AA contrast in Night and Day. With R52_SHOTS=<dir> the
# section and the pop-up are saved as screenshots in both surfaces.
from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_brief import CONTRAST_JS, SETTLE_JS  # same directory (pytest prepend import)
from test_console import DESKTOP, PHONE, Console
from test_voice import speechlike_wav

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser

P = "/v1/voice/profile"
PROMPTS = [
    {"id": "b1_comm_01", "block": 1, "kind": "command", "text": "Jarvis, stop talking.",
     "how": "", "compare": True, "wake": False},
    {"id": "b1_wake_01", "block": 1, "kind": "wake", "text": "Hey Jarvis",
     "how": "from across the room", "compare": False, "wake": True},
    {"id": "b2_plac_01", "block": 2, "kind": "places", "text": "What's the weather in Mumbai?",
     "how": "", "compare": True, "wake": False},
    {"id": "b2_wake_01", "block": 2, "kind": "wake", "text": "Hey Jarvis", "how": "quietly",
     "compare": False, "wake": True},
]  # fmt: skip
ASK = (
    "Comparing with Google's listening takes about 20 minutes, and this month's free minutes "
    "don't cover it: about ₹2.29 a minute, at most about ₹46. Type YES to include Google, or go "
    "on without it."
)
RANKING = [
    {"engine": "google", "label": "Google (with your words)", "wer_pct": 1.4, "commands_pct": 100,
     "prompts": 80, "median_ms": 420, "on_laptop": False, "chosen": False},
    {"engine": "laptop-whisper-small", "label": "Laptop: Whisper small", "wer_pct": 2.1,
     "commands_pct": 100, "prompts": 80, "median_ms": 380, "on_laptop": True, "chosen": True},
    {"engine": "browser", "label": "This browser", "wer_pct": 7.9, "commands_pct": 92.5,
     "prompts": 80, "median_ms": None, "on_laptop": False, "chosen": False},
]  # fmt: skip


class FakeProfile:
    """The /v1/voice/profile routes as the handlers answer them; every request kept."""

    def __init__(self, page: Any) -> None:
        self.state, self.done, self.mode, self.scored = "none", [], "free", False
        self.calls: list[tuple[str, str, Any]] = []
        self.asked = False
        page.route(re.compile(r".*/v1/voice/profile(/.*)?$"), self._route)

    def profile(self) -> dict[str, Any]:
        chosen = self.scored
        return {
            "state": "done" if chosen else self.state,
            "session_id": None,
            "chosen": "laptop-whisper-small" if chosen else None,
            "chosen_label": "Laptop: Whisper small" if chosen else "",
            "ranking": RANKING if chosen else [],
            "meets_bar": True if chosen else None,
            "corrections": [{"heard": "java's", "meant": "Jarvis", "seen": 4}] if chosen else [],
            "corrections_on": True,
            "clips": len(self.done),
            "compare_seconds": 15.0,
            "measured_at": None,
            "order": ["laptop-whisper-small", "google", "browser"],
            "order_labels": ["Laptop: Whisper small", "Google (with your words)", "This browser"],
            "laptop_ready": True,
        }

    def session(self) -> dict[str, Any]:
        words = {"free": "Google hears the comparison lines inside this month's free minutes: ₹0.",
                 "yes": "You said YES: Google hears the comparison lines at about ₹2.29 a minute, "
                        "at most about ₹46.", "needs_yes": ASK}[self.mode]  # fmt: skip
        live = self.state != "none"
        return {
            "state": self.state,
            "minutes": 20,
            "blocks": [],
            "prompts": PROMPTS if live else [],
            "done": list(self.done),
            "next": None,
            "total": len(PROMPTS) if live else 0,
            "compare": {"mode": self.mode, "words": words, "yes_word": "YES"},
            "reason": "",
            "words_added": ["Quillon"] if self.scored else [],
        }

    def _json(self, route: Any, body: Any, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body),
                      headers={"Cache-Control": "no-store"})  # fmt: skip

    def _route(self, route: Any) -> None:
        req = route.request
        path = req.url.split("/v1/voice/profile", 1)[1].split("?")[0]
        body = json.loads(req.post_data) if req.post_data else None
        self.calls.append((req.method, path, body))
        if req.method == "GET" and path == "":
            return self._json(route, self.profile())
        if req.method == "GET" and path == "/session":
            return self._json(route, self.session())
        if path == "/session/start":
            if body and body.get("yes") == "YES":
                self.mode = "yes"
            if self.state == "none":
                self.state = "recording"
            return self._json(route, self.session())
        if path.startswith("/session/clips/"):
            pid = path.rsplit("/", 1)[1]
            if pid == "b2_plac_01" and self.mode != "yes":
                self.asked = True
                return self._json(route, {"error": "needs_yes", "detail": ASK}, 402)
            if pid not in self.done:
                self.done.append(pid)
            return self._json(route, {"prompt_id": pid, "seconds": 2.1, "clips": len(self.done),
                                      "done": len(self.done), "total": 4, "next": None,
                                      "compare": self.mode})  # fmt: skip
        if path == "/session/score":
            self.state, self.scored = "done", True
            return self._json(route, {"state": "done", "reason": "", "words_added": ["Quillon"],
                                      "job": None, "profile": self.profile()})  # fmt: skip
        if path == "/recordings/delete":
            n, self.done, self.state = len(self.done), [], "none"
            gone = f"Deleted {n} recordings from your laptop."
            return self._json(route, {"clips": n, "wakeword_files": 0, "words": gone})
        return self._json(route, {"error": "not_found", "detail": "No such route."}, 404)


@pytest.fixture(scope="module")
def browser(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    mic = tmp_path_factory.mktemp("voice") / "speech.wav"
    speechlike_wav(mic)
    args = [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-audio-capture={mic}",
    ]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        yield b
        b.close()


def _console(browser: Any, url: str, token: str, surface: str, viewport: dict[str, int]) -> Console:
    c = Console(browser, url, token, viewport)
    c.page.route(  # the real wake-word module is tested on its own
        "**/static/console-wakeword.js",
        lambda r: r.fulfill(status=200, content_type="text/javascript", body=""),
    )
    c.page.add_init_script(
        f"localStorage.setItem('jarvis_surface', {json.dumps(surface)});"
        "localStorage.setItem('jarvis_voice_session_browser_v1', 'off');"
    )
    return c


DISABLED_JS = """(root) => [...document.querySelectorAll(root + ' button:disabled')]
  .map(b => b.textContent.trim().slice(0, 50))"""


def _contrast(c: Console, root: str) -> list[Any]:
    """Text under AA (4.5:1), disabled buttons aside (WCAG exempts them; they say so by fading)."""
    c.page.evaluate(SETTLE_JS, root)
    found = c.page.evaluate(CONTRAST_JS, root)
    off = set(c.page.evaluate(DISABLED_JS, root))
    return [f for f in found if f["ratio"] < 4.5 and f["text"] not in off]


def _shot(c: Console, name: str, target: str) -> None:
    out = os.environ.get("R52_SHOTS")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        c.page.locator(target).screenshot(path=str(Path(out) / f"{name}.png"))


def _record_line(c: Console, pid: str) -> None:
    before = c.page.evaluate("id => window.__puts.filter(x => x === id).length", pid)
    c.page.locator("#vsRecord").click()
    c.page.wait_for_function(
        "([n, id]) => window.__puts && window.__puts.filter(x => x === id).length > n",
        arg=[before, pid],
        timeout=20_000,
    )


SPY_PUTS = """
window.__puts = [];
const _f = window.fetch;
window.fetch = function (u, o) {
  const m = /\\/session\\/clips\\/([a-z0-9_]+)$/.exec(String(u));
  const p = _f.apply(this, arguments);
  if (m) p.then(() => window.__puts.push(m[1]), () => {});
  return p;
};
"""


@pytest.mark.parametrize("surface", ["night", "day"])
def test_the_voice_session_main_path(
    browser: Any, server_url: str, token: str, surface: str
) -> None:
    c = _console(browser, server_url, token, surface, DESKTOP)
    c.page.add_init_script(SPY_PUTS)
    fake = FakeProfile(c.page)
    try:
        c.open()
        c.open_panel("voice")
        sec = c.page.locator("#vSlotProfile")
        sec.get_by_text("No voice session yet").wait_for()
        start = c.page.locator("#vProfileStart")
        assert start.inner_text().casefold() == "start the voice session"
        start.click()
        dlg = c.page.locator("#vsDlg")
        dlg.wait_for(state="visible")
        c.page.locator("#vsStart").wait_for()
        dlg.get_by_text("free minutes: ₹0").wait_for()
        _shot(c, f"session-intro-{surface}", "#vsDlg")
        assert not _contrast(c, "#vsDlg"), _contrast(c, "#vsDlg")
        assert c.page.locator("#vsBrowser").get_attribute("aria-pressed") == "false"
        c.page.locator("#vsWords").fill("Quillon")
        c.page.locator("#vsStart").click()
        c.page.locator("#vsLine").wait_for()
        assert c.page.locator("#vsLine").inner_text() == "Jarvis, stop talking."
        assert "for the comparison" in dlg.inner_text().casefold()
        _shot(c, f"session-record-{surface}", "#vsDlg")
        assert not _contrast(c, "#vsDlg"), _contrast(c, "#vsDlg")
        _record_line(c, "b1_comm_01")
        c.page.locator("#vsLine").filter(has_text="Hey Jarvis").wait_for()
        assert "from across the room" in dlg.inner_text()
        _record_line(c, "b1_wake_01")
        c.page.locator("#vsContinue").wait_for()  # the break after block 1
        assert "Block 1 done" in dlg.inner_text()
        c.page.locator("#vsContinue").click()
        c.page.locator("#vsRecord").click()  # 402: the rupee question, the clip kept
        c.page.locator("#vsYes").wait_for(timeout=20_000)
        assert "at most about ₹46" in dlg.inner_text() and fake.asked
        _shot(c, f"session-ask-{surface}", "#vsDlg")
        assert not _contrast(c, "#vsDlg"), _contrast(c, "#vsDlg")
        c.page.locator("#vsYes").fill("YES")
        c.page.locator("#vsYesGo").click()
        c.page.locator("#vsLine").filter(has_text="Hey Jarvis").wait_for()
        assert fake.done == ["b1_comm_01", "b1_wake_01", "b2_plac_01"]
        _record_line(c, "b2_wake_01")
        c.page.locator("#vsScore").wait_for()
        c.page.locator("#vsScore").click()
        c.page.locator("#vsDone").wait_for()
        text = dlg.inner_text().casefold()
        assert (
            "laptop: whisper small" in text and "quillon" in text and "chosen over google" in text
        )
        _shot(c, f"session-results-{surface}", "#vsDlg")
        assert not _contrast(c, "#vsDlg"), _contrast(c, "#vsDlg")
        c.page.locator("#vsDone").click()
        dlg.wait_for(state="hidden")
        c.page.get_by_text("Best for your voice: Laptop: Whisper small.").wait_for()
        _shot(c, f"panel-results-{surface}", "#vSlotProfile")
        assert not _contrast(c, "#vSlotProfile"), _contrast(c, "#vSlotProfile")
        c.page.locator("#vProfileDelete").click()
        c.page.locator("#vsDeleteGo").click()
        c.page.get_by_text("Deleted 4 recordings from your laptop.").wait_for()
        starts = [b for m, p, b in fake.calls if p == "/session/start"]
        assert starts[0] == {"words": ["Quillon"]} and starts[1] == {"yes": "YES"}
        puts = [b for m, p, b in fake.calls if p.startswith("/session/clips/")]
        assert len(puts) == 5 and all(set(b) == {"audio"} for b in puts)  # browser listening off
        assert all(base64.b64decode(b["audio"])[:4] == b"RIFF" for b in puts)
        assert ("POST", "/recordings/delete", {"confirm": "DELETE"}) in fake.calls
        refused = ("402", "/v1/voice/profile")  # the rupee question's answer, by design
        assert not [e for e in c.errors if not all(x in e for x in refused)], c.errors
        assert not c.csp_violations()
    finally:
        c.close()


def test_the_section_fits_a_phone_on_the_real_routes(
    browser: Any, server_url: str, token: str
) -> None:
    c = _console(browser, server_url, token, "night", PHONE)  # I1: the real, wired routes
    try:
        c.open()
        c.open_panel("voice")
        c.page.locator("#vSlotProfile").get_by_text("No voice session yet").wait_for()
        assert c.page.locator("#vProfileStart").is_enabled()
        assert c.page.locator("#vProfileTrain").is_hidden()  # no scored session yet
        width = c.page.evaluate("document.documentElement.scrollWidth")
        assert width <= PHONE["width"]
        assert not c.errors and not c.csp_violations()
    finally:
        c.close()
