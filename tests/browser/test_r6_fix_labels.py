# tests/browser/test_r6_fix_labels.py -- orchestrator screenshot findings O1, O2 (R6 fixer): with this
# release's real facts the 3D show's labels overlapped (scene 9's centre cluster, scene 10's four free
# Gemini labels on the floor, scene 7's camera over the laptop) and scene 10's were cut short
# ("Claude Opus 5.5, outp..."). Every scene's labels now pass one screen-space de-collision pass in the
# label layer (nudged up or down; a label with no room is hidden and counted in a "+N more" label of
# the existing dim style), and scene 10's labels are two lines (the model / "input"|"output" + the
# rupees). Checked with reduced motion (one still per beat: the positions hold) and once in motion.
# ruff: noqa: E501 -- the facts are the real book's, one per line
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import _beats, _facts
from test_book_show import _begin, _clean, _need_3d, _show

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


HOME = _facts(
    ("The camera", "at home", None, "home"),
    ("Recognising faces", "stays at home", None, "home"),
    ("The devices", "at home", None, "home"),
    ("The laptop", "the home bridge", None, "edge"),
    ("The home bridge sends a signed event", "home.webhook:HomeWebhook.receive", 1, "step"),
    ("The signature is checked", "home.signing:verify", 2, "step"),
    ("A camera event becomes an alert", "camera.events:CameraEvents.handle", 3, "step"),
    ("One policy decides: ring, hold or stay silent", "notify.policy:decide", 4, "step"),
    ("The alert goes out", "notify.service:NotifyService.notify", 5, "step"),
    ("Telegram delivers it", "telegram.alerts:TelegramAlerts.send", 6, "step"),
    ("Your browsers get a notification", "webpush.service:PushService.send", 7, "step"),
)
LIBS = [
    ("openWakeWord models", "CC-BY-NC-SA-4.0", "voice", "non_commercial"),
    ("certifi", "MPL-2.0", "web", "copyleft"),
    ("onnxruntime-web", "MIT", "voice", ""),
    ("openWakeWord code (ported)", "Apache-2.0", "voice", ""),
    ("Orbitron", "OFL-1.1", "console", ""),
    ("Rajdhani", "OFL-1.1", "console", ""),
    ("Share Tech Mono", "OFL-1.1", "console", ""),
    ("three.js", "MIT", "3d", ""),
    ("annotated-doc", "MIT", "data", ""),
    ("annotated-types", "MIT", "data", ""),
    ("anthropic", "Apache-2.0", "ai", ""),
    ("anyio", "MIT", "web", ""),
    ("authlib", "BSD-3-Clause", "security", ""),
    ("cbor2", "MIT", "data", ""),
    ("cffi", "MIT-0", "security", ""),
    ("charset-normalizer", "MIT", "web", ""),
    ("click", "BSD-3-Clause", "web", ""),
    ("cryptography", "Apache-2.0 OR BSD-3-Clause", "security", ""),
    ("docstring-parser", "MIT", "ai", ""),
    ("fastapi", "MIT", "web", ""),
    ("google-api-core", "Apache 2.0", "google", ""),
    ("google-auth", "Apache 2.0", "google", ""),
    ("h11", "MIT", "web", ""),
    ("httpcore", "BSD-3-Clause", "web", ""),
    ("httpcore2", "BSD-3-Clause", "web", ""),
    ("httptools", "MIT", "web", ""),
    ("httpx", "BSD-3-Clause", "web", ""),
    ("httpx2", "BSD-3-Clause", "web", ""),
    ("idna", "BSD-3-Clause", "web", ""),
    ("requests", "Apache-2.0", "web", ""),
    ("sniffio", "MIT OR Apache-2.0", "web", ""),
    ("starlette", "BSD-3-Clause", "web", ""),
    ("truststore", "MIT", "web", ""),
]
STACK = _facts(*((name, lic, None, group, flag) for name, lic, group, flag in LIBS))
COSTS = _facts(
    ("Claude Opus 5.5, input", "₹380.96", 380.96, "model"),
    ("Claude Opus 5.5, output", "₹1,904.80", 1904.8, "model"),
    ("Claude Sonnet 5.5, input", "₹190.48", 190.48, "model"),
    ("Claude Sonnet 5.5, output", "₹952.40", 952.4, "model"),
    ("Claude Haiku 5.5, input", "₹9.52", 9.52, "model"),
    ("Claude Haiku 5.5, output", "₹47.62", 47.62, "model"),
    ("Gemini 3.8 Flash", "₹0.00", 0.0, "model"),
    ("Gemini 3.6 Flash", "₹0.00", 0.0, "model"),
    ("Gemini 3.5 Flash Lite", "₹0.00", 0.0, "model"),
    ("Gemini 3.1 Flash Lite", "₹0.00", 0.0, "model"),
)
SCENES = [
    {
        "n": 1,
        "id": "book",
        "title": "The build book",
        "beats": _beats(1, "Release R6 at a glance."),
    },
    {"n": 7, "id": "home", "title": "Home", "beats": _beats(7, "At home."), "facts": HOME},
    {
        "n": 9,
        "id": "stack",
        "title": "Stack and licences",
        "beats": _beats(9, "What I run on."),
        "facts": STACK,
    },
    {"n": 10, "id": "costs", "title": "Costs", "beats": _beats(10, "What I cost."), "facts": COSTS},
]
LAYOUT = """() => {
  const els = [...document.querySelectorAll('#shLabels .sh-lbl')].filter((e) => getComputedStyle(e).visibility !== 'hidden' && e.textContent);
  const r = els.map((e) => e.getBoundingClientRect()), over = [];
  for (let i = 0; i < r.length; i += 1) for (let j = i + 1; j < r.length; j += 1) {
    const a = r[i], b = r[j];
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) over.push([els[i].textContent, els[j].textContent]);
  }
  const stage = document.querySelector('#shLabels').getBoundingClientRect();
  const outside = r.filter((x) => x.left < stage.left - 1 || x.right > stage.right + 1 || x.top < stage.top - 1 || x.bottom > stage.bottom + 1).length;
  return { over, outside, shown: els.map((e) => e.textContent) };
}"""


# the 3D layer is on scene n and has placed every one of its labels: each is pinned (a transform) or
# hidden (no room, or behind the camera); a label just set and not yet placed has neither
PLACED = """() => window.JarvisBook3D.stats().scene === %d && [...document.querySelectorAll('#shLabels .sh-lbl')]
  .every((e) => e.style.visibility === 'hidden' || e.style.transform !== '')"""
# code re-review #4: count every time a label's words are replaced by the very same words
REWRITES = """() => { window.__same = 0; new MutationObserver((ms) => ms.forEach((m) => {
  const was = m.removedNodes[0], now = m.addedNodes[0];
  if (m.target !== m.currentTarget && was && now && was.data === now.data) window.__same += 1;
})).observe(document.getElementById('shLabels'), { subtree: true, childList: true }); }"""


def _hold(c: Any) -> None:
    """Pause the show, so a scene stays on screen while its labels are measured."""
    c.page.keyboard.press("Space")
    c.page.wait_for_function("() => !window.JarvisBookShow.state().playing")


def _goto(c: Any, n: int) -> dict[str, Any]:
    c.page.locator("#shChapters").click()
    title = next(s["title"] for s in SCENES if s["n"] == n)
    c.page.locator("#shChapterList button", has_text=title).click()
    c.page.wait_for_function(f"() => window.JarvisBookShow.state().scene === {n}")
    c.page.wait_for_function(PLACED % n)  # a condition, not a time (code re-review #5)
    return dict(c.page.evaluate(LAYOUT))


@pytest.fixture
def still(browser: Any, server_url: str, token: str) -> Iterator[Any]:
    c, _ = _show(browser, server_url, token, scenes=SCENES, reduced=True)
    _begin(c)
    _need_3d(c)
    _hold(c)
    yield c
    _clean(c)
    c.close()


@pytest.mark.parametrize("n", [7, 9, 10])
def test_no_two_labels_overlap_in_a_crowded_scene(still: Any, n: int) -> None:
    got = _goto(still, n)
    assert got["over"] == [], got["over"]
    assert got["outside"] == 0 and got["shown"]


def test_the_costs_labels_are_two_lines_and_never_cut(still: Any) -> None:
    shown = _goto(still, 10)["shown"]
    assert not [t for t in shown if "…" in t], shown
    assert "Claude Opus 5.5\noutput · ₹1,904.80" in shown
    assert "Gemini 3.1 Flash Lite\n₹0.00" in shown


def test_home_labels_are_never_cut(still: Any) -> None:
    shown = _goto(still, 7)["shown"]
    assert not [t for t in shown if "…" in t], shown
    assert "The home bridge sends a signed event\nhome.webhook:HomeWebhook.receive" in shown


def test_labels_with_no_room_are_counted_not_stacked(still: Any) -> None:
    got = _goto(still, 9)
    more = [t for t in got["shown"] if t.startswith("+") and t.endswith(" more")]
    assert len(more) <= 1
    flagged = [t for t in got["shown"] if "Non-commercial" in t or "Copyleft" in t]
    assert len(flagged) == 2  # the flagged licences always keep their label


def test_in_motion_the_labels_still_never_overlap(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _show(browser, server_url, token, scenes=SCENES)
    try:
        _begin(c)
        _need_3d(c)
        _hold(c)  # paused, the 3D loop still runs in full motion: the orbits keep turning
        for _ in range(3):
            got = _goto(c, 9)
            assert got["over"] == [], got["over"]
            c.page.wait_for_timeout(700)
        _clean(c)
    finally:
        c.close()


CROWDED = {"width": 900, "height": 560}  # scene 9's stack then leaves labels without room


def test_the_more_label_is_written_only_when_its_count_changes(
    browser: Any, server_url: str, token: str
) -> None:
    """Code re-review #4: "+N more" was rewritten (and measured after the label writes) on every
    drawn frame while any label was hidden; now its words change only with the count."""
    c, _ = _show(browser, server_url, token, CROWDED, scenes=SCENES, reduced=True)
    try:
        _begin(c)
        _need_3d(c)
        _hold(c)
        got = _goto(c, 9)
        assert [t for t in got["shown"] if t.startswith("+") and t.endswith(" more")], got
        c.page.evaluate(REWRITES)
        frames = c.page.evaluate("() => window.JarvisBook3D.stats().frames")
        c.page.evaluate("() => document.activeElement && document.activeElement.blur()")
        for _ in range(2):  # play, pause: each redraws the still scene (reduced motion)
            c.page.keyboard.press("Space")
        c.page.wait_for_function(f"() => window.JarvisBook3D.stats().frames >= {frames + 2}")
        assert c.page.evaluate("() => window.JarvisBookShow.state().scene") == 9
        assert c.page.evaluate("() => window.__same") == 0
        _clean(c)
    finally:
        c.close()
