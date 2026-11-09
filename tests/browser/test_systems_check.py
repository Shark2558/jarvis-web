# tests/browser/test_systems_check.py -- R5.1 D6 (docs/plans/r5-1-observations.md): the systems
# check pop-up and the tidied Systems card, in a real browser. The stream is mocked with page.route
# (an NDJSON body). The pop-up's scripts and stylesheet are the ones console.html links and the
# /static allow-list serves (I1); nothing is injected.
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from test_brief import CONTRAST_JS, SETTLE_JS  # same directory (pytest prepend import)
from test_console import DESKTOP, PHONE, Console

pytestmark = pytest.mark.browser

NOW = time.time()
SYSTEMS = [
    ("brain", "the AI brain", "ok", "the last AI call worked"),
    ("docs", "the document store", "ok", "the document store answers"),
    ("google", "Google", "degraded", "a Google service is switched off"),
    ("telegram", "Telegram", "down", "the bot token was refused"),
    ("home", "the home bridge", "skipped", "not set up"),
]
SPOKEN = (
    "Systems check complete, Sir. I checked 4 systems: the AI brain, the document store, Google "
    "and Telegram. The AI brain and the document store are working. Telegram is not answering "
    "— alerts and Telegram chat won't reach you. Google is degraded — calendar, email, "
    "reminders and Drive stop working. AI spend is ₹120 of ₹500 this month, 24 percent. "
    "GitHub token expires in 3 days — the service using it stops working. Shall I set a "
    "reminder to fix this?"
)
CONCERNS = [
    {"key": "telegram", "label": "Telegram", "severity": "down",
     "impact": "alerts and Telegram chat won't reach you",
     "fix": "Check the Telegram bot and its pairing in Integrations."},
    {"key": "google", "label": "Google", "severity": "degraded",
     "impact": "calendar, email, reminders and Drive stop working",
     "fix": "Reconnect Google in Integrations."},
    {"key": "vitals.github", "label": "GitHub token", "severity": "amber",
     "impact": "the service using it stops working", "fix": "Renew it before it runs out."},
]  # fmt: skip
CLOSING = (
    "Closing this window, Sir. Whenever you'd like a fresh check, "
    "just ask and I'll update the status."
)


def row(key: str, name: str, status: str, reason: str) -> dict[str, Any]:
    return {"key": key, "name": name, "status": status, "reason": reason, "at": NOW}


DONE: dict[str, Any] = {
    "type": "done",
    "overall": "down",
    "spoken": "Attention: Telegram is not answering. Google is degraded.",
    "checked_at": NOW,
    "systems": [row(*s) for s in SYSTEMS if s[2] != "skipped"],
    "briefing": {
        "spoken": SPOKEN,
        "lines": [SPOKEN],
        "concerns": CONCERNS,
        "spend": "AI spend is ₹120 of ₹500 this month, 24 percent.",
    },
}


def stream_body(done: bool = True) -> str:
    events: list[dict[str, Any]] = [
        {"type": "plan", "systems": [{"key": k, "name": n} for k, n, _, _ in SYSTEMS]}
    ]
    events += [{"type": "result", **row(*s)} for s in (SYSTEMS if done else SYSTEMS[:2])]
    if done:
        events.append(DONE)
    return "".join(json.dumps(e) + "\n" for e in events)


class Fake:
    """The health routes, mocked; every request body kept."""

    def __init__(self, page: Any, *, stream_status: int = 200, done: bool = True) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.stream_status, self.done = stream_status, done
        self.remind_answer = {"outcome": "executed", "line": "Reminder set for tomorrow, 10:00."}
        self.hold_remind = False
        self.hold_stream = False  # the stream's answer is sent later by the test
        self.held: list[Any] = []
        self.held_streams: list[Any] = []
        page.route("**/v1/health/run/stream", self._stream)
        page.route("**/v1/health/remind", self._remind)
        page.route("**/v1/health/run", self._run)
        page.route("**/v1/health", self._last)

    def _body(self, route: Any) -> Any:
        raw = route.request.post_data
        return json.loads(raw) if raw else None

    def _stream(self, route: Any) -> None:
        self.calls.append(("stream", self._body(route)))
        if self.hold_stream:
            self.held_streams.append(route)
            return
        if self.stream_status != 200:
            route.fulfill(status=self.stream_status, content_type="application/json", body="{}")
            return
        route.fulfill(status=200, content_type="application/x-ndjson", body=stream_body(self.done))

    def _remind(self, route: Any) -> None:
        self.calls.append(("remind", self._body(route)))
        if self.hold_remind:  # answered later by the test
            self.held.append(route)
            return
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(self.remind_answer)
        )

    def _run(self, route: Any) -> None:
        self.calls.append(("run", self._body(route)))
        body = {k: v for k, v in DONE.items() if k != "type"}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def _last(self, route: Any) -> None:
        if route.request.method != "GET":
            route.fallback()
            return
        body = {k: v for k, v in DONE.items() if k != "type"}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def named(self, name: str) -> list[Any]:
        return [b for n, b in self.calls if n == name]


LOADED = "() => !!window.JarvisSystemsCheck && !!window.JarvisSystemsVoice"

# the shared speaker, recorded: say() keeps the text, end() finishes "speech" after `ms`
SPEAKER = """() => {
  const sp = window.JarvisVoice.speaker, fns = [];
  window.__said = [];
  sp.on = (k, fn) => { if (k === 'state') fns.push(fn); };
  sp.say = (t) => { window.__said.push(String(t)); };
  sp.unlock = () => {};
  window.__endSpeech = () => fns.forEach(f => f({ speaking: false, reason: 'done' }));
  sp.end = () => {};  // the test says when the speech has ended
}"""
EVENTS = (
    "window.__log = [];"
    "document.addEventListener('jarvis:event', e => window.__log.push(e.detail.text));"
)
SILENT = {"jarvis_voice_device_v1": json.dumps({"speak": "never"})}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def make(
    browser: Any, server_url: str, token: str
) -> Iterator[Callable[..., tuple[Console, Fake]]]:
    made: list[Console] = []

    def factory(
        viewport: dict[str, int] = DESKTOP, store: dict[str, str] | None = None, **fake: Any
    ) -> tuple[Console, Fake]:
        c = Console(browser, server_url, token, viewport)
        if store:
            put = "localStorage.setItem({}, {});"
            c.page.add_init_script(
                "".join(put.format(json.dumps(k), json.dumps(v)) for k, v in store.items())
            )
        c.page.add_init_script(EVENTS)
        f = Fake(c.page, **fake)
        c.open()
        c.page.wait_for_function(LOADED)  # the page's own deferred scripts
        made.append(c)
        return c, f

    yield factory
    for c in made:
        c.close()


def open_check(c: Console, close_after_ms: int | None = None) -> Any:
    if close_after_ms is None:
        c.open_panel("integrations")
        c.page.locator("#systemsCard .btn", has_text="Run").click()
    else:
        c.page.evaluate(f"window.JarvisSystemsCheck.open({{closeAfterMs: {close_after_ms}}})")
    dlg = c.page.locator("#sysCheck")
    dlg.wait_for(state="visible")
    c.page.locator("#sysCheck .sccount").wait_for(state="attached")
    return dlg


def done(c: Console) -> None:
    c.page.locator('#sysCheck[data-phase="done"]').wait_for(state="attached")


# ---- the flow ------------------------------------------------------------------------------------
def test_each_system_ticks_with_a_symbol_and_a_word_then_the_briefing_shows(make: Any) -> None:
    c, f = make(store=SILENT)
    open_check(c)
    done(c)
    rows = c.page.locator("#sysCheck .scrow")
    assert rows.count() == 5
    words = {r.get_attribute("data-key"): r.locator(".scword").text_content() for r in rows.all()}
    assert words == {"brain": "OK", "docs": "OK", "google": "Degraded", "telegram": "Down",
                     "home": "Not set up"}  # fmt: skip
    for r in rows.all():  # a drawn symbol beside each word, never an emoji or colour alone
        assert r.locator(".scicon svg").count() == 1
    assert "The AI brain" in str(rows.first.text_content())
    reason = c.page.locator('#sysCheck .scrow[data-key="telegram"] .screason').text_content()
    assert reason == "the bot token was refused"
    assert c.page.locator("#sysCheck .scsaid").text_content() == SPOKEN
    assert "₹120 of ₹500" in str(c.page.locator("#sysCheck .scspend").text_content())
    concerns = c.page.locator("#sysCheck .scconcern")
    assert concerns.count() == 3
    first = str(concerns.first.text_content())
    assert "Alerts and Telegram chat won't reach you." in first and "Telegram bot" in first
    assert f.named("stream") == [{"force": True}]
    assert c.page.locator("#systemsCard").get_attribute("data-state") == "down"  # the card too
    assert c.csp_violations() == [] and c.errors == []


def test_it_speaks_the_briefing_then_counts_down_and_closes_with_a_notice(make: Any) -> None:
    c, _ = make()
    c.page.evaluate(SPEAKER)
    open_check(c, close_after_ms=1500)
    done(c)
    assert c.page.evaluate("window.__said") == [SPOKEN]
    count = c.page.locator("#sysCheck .sccount")
    c.page.wait_for_timeout(2500)  # longer than the countdown: it must not have started
    assert "Closing in" not in str(count.text_content())  # not while JARVIS is still speaking
    assert c.page.locator("#sysCheck").is_visible()
    c.page.evaluate("window.__endSpeech()")
    count.filter(has_text="Closing in").wait_for(timeout=3000)
    c.page.locator("#sysCheck").wait_for(state="hidden", timeout=4000)
    assert c.page.evaluate("window.__said")[-1] == CLOSING
    assert CLOSING in c.page.evaluate("window.__log")
    assert c.errors == []


def test_untouched_it_closes_after_ten_seconds_by_default(make: Any) -> None:
    c, _ = make(store=SILENT)
    open_check(c)
    done(c)
    count = c.page.locator("#sysCheck .sccount", has_text="Closing in")
    count.wait_for(timeout=2000)
    first = int(str(count.text_content()).split()[2])  # "Closing in 10 s" (9 on a slow machine)
    assert first in (10, 9)
    began = time.monotonic()
    c.page.locator("#sysCheck").wait_for(state="hidden", timeout=14000)
    took = time.monotonic() - began
    assert first - 2 <= took <= first + 2.5, took
    assert CLOSING in c.page.evaluate("window.__log")


@pytest.mark.parametrize("how", ["move", "key", "click"])
def test_any_interaction_cancels_the_countdown(make: Any, how: str) -> None:
    c, _ = make(store=SILENT)
    open_check(c, close_after_ms=6000)
    done(c)
    c.page.locator("#sysCheck .sccount", has_text="Closing in").wait_for()
    box = c.page.locator("#sysCheck .sclist").bounding_box()
    assert box is not None
    if how == "move":
        c.page.mouse.move(box["x"] + 20, box["y"] + 10)
        c.page.mouse.move(box["x"] + 40, box["y"] + 20)
    elif how == "key":
        c.page.keyboard.press("Shift")
    else:
        c.page.mouse.click(box["x"] + 20, box["y"] + 10)
    c.page.locator("#sysCheck .sccount", has_text="Kept open").wait_for(timeout=3000)
    c.page.wait_for_timeout(6500)  # past the 6 s countdown
    assert c.page.locator("#sysCheck").is_visible()


def test_esc_closes_and_focus_returns_to_run(make: Any) -> None:
    c, _ = make(store=SILENT)
    open_check(c)
    done(c)
    c.page.keyboard.press("Escape")
    c.page.locator("#sysCheck").wait_for(state="hidden")
    focused = c.page.evaluate("document.activeElement && document.activeElement.textContent")
    assert focused is not None and "Run" in focused


def test_tab_stays_inside_the_dialog(make: Any) -> None:
    c, _ = make(store=SILENT)
    open_check(c)
    done(c)
    for _ in range(25):
        c.page.keyboard.press("Tab")
        inside = c.page.evaluate("!!document.activeElement.closest('#sysCheck')")
        assert inside


def test_close_button_and_run_again(make: Any) -> None:
    c, f = make(store=SILENT)
    open_check(c)
    done(c)
    c.page.locator("#sysCheckAgain").click()
    for _ in range(100):  # the page's CSP has no unsafe-eval, so no wait_for_function(string)
        if len(f.named("stream")) == 2:
            break
        c.page.wait_for_timeout(50)
    done(c)
    assert len(f.named("stream")) == 2
    assert c.page.locator("#sysCheck .scrow").count() == 5  # rebuilt, not doubled
    c.page.locator("#sysCheckClose").click()
    c.page.locator("#sysCheck").wait_for(state="hidden")


# ---- the reminder --------------------------------------------------------------------------------
def test_reminder_choices_post_the_right_body_and_show_the_answer(make: Any) -> None:
    c, f = make(store=SILENT)
    open_check(c)
    done(c)
    c.page.locator('#sysCheck .scwhen button[data-when="tomorrow"]').click()
    c.page.locator("#sysCheck .scremnote", has_text="Reminder set for tomorrow, 10:00.").wait_for()
    assert f.named("remind") == [{"key": "telegram", "when": "tomorrow"}]
    c.page.locator("#sysRemKey").select_option("vitals.github")
    f.remind_answer = {"outcome": "awaiting_confirmation", "line": "Approve it in Approvals, Sir."}
    c.page.locator('#sysCheck .scwhen button[data-when="1h"]').click()
    c.page.locator("#sysCheck .scremnote", has_text="Approve it in Approvals").wait_for()
    assert f.named("remind")[-1] == {"key": "vitals.github", "when": "1h"}
    label = c.page.locator('label[for="sysRemKey"]').text_content()
    assert label and label.strip()


def test_the_open_conversation_goes_with_the_reminder(make: Any) -> None:
    c, f = make(store=SILENT)
    c.send("hello")
    sid = c.page.evaluate("window.JarvisApprovals.session()")
    assert sid
    open_check(c)
    done(c)
    c.page.locator('#sysCheck .scwhen button[data-when="evening"]').click()
    c.page.locator("#sysCheck .scremnote", has_text="Reminder set").wait_for()
    assert f.named("remind") == [{"key": "telegram", "when": "evening", "session_id": sid}]


# ---- fallbacks -----------------------------------------------------------------------------------
@pytest.mark.parametrize("status", [404, 405])
def test_without_the_stream_it_falls_back_to_run(make: Any, status: int) -> None:
    c, f = make(store=SILENT, stream_status=status)
    open_check(c)
    done(c)
    assert len(f.named("run")) == 1
    assert c.page.locator('#sysCheck .scrow[data-key="telegram"] .scword').text_content() == "Down"
    assert c.page.locator("#sysCheck .scsaid").text_content() == SPOKEN


def test_a_stream_that_ends_without_done_says_so(make: Any) -> None:
    c, _ = make(store=SILENT, done=False)
    open_check(c)
    c.page.locator("#sysCheck .scstatus", has_text="did not complete").wait_for()
    assert c.page.locator("#sysCheckAgain").is_enabled()
    words = c.page.locator("#sysCheck .scword").all_text_contents()
    assert words == ["OK", "OK", "Not checked", "Not checked", "Not checked"]  # never "Not set up"


# ---- the ways in ---------------------------------------------------------------------------------
def test_the_document_event_and_the_voice_command_open_it(make: Any) -> None:
    c, _ = make(store=SILENT)
    c.page.evaluate(
        "document.dispatchEvent(new CustomEvent('jarvis:systems-check', {detail: {via: 'typed'}}))"
    )
    c.page.locator("#sysCheck").wait_for(state="visible")
    c.page.keyboard.press("Escape")
    c.page.locator("#sysCheck").wait_for(state="hidden")
    got = c.page.evaluate(
        "window.JarvisVoiceCommands.handle('Jarvis, run a systems check', "
        "{source: 'voice', state: 'listening'})"
    )
    assert got["handled"] is True and got["id"] == "systems.check"
    c.page.locator("#sysCheck").wait_for(state="visible")
    typed = c.page.evaluate(
        "window.JarvisVoiceCommands.handle('run a systems check', "
        "{source: 'typed', state: 'listening'})"
    )
    assert typed["handled"] is False


def test_typing_the_phrase_in_the_composer_opens_it_with_no_ai_call(make: Any) -> None:
    """R5.1 I1 (console.js): the composer hands the whole phrase to the pop-up, clears the box and
    sends nothing to /v1/chat; any other message still goes to the chat."""
    c, _ = make(store=SILENT)
    chats: list[str] = []

    def chat(route: Any) -> None:
        chats.append(route.request.post_data or "")
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"session_id": "s1", "reply": "Noted, Sir.", "model": "mock"}),
        )

    c.page.route("**/v1/chat**", chat)
    box = c.page.locator("#input")
    box.fill("Jarvis, run a systems check.")
    box.press("Enter")
    c.page.locator("#sysCheck").wait_for(state="visible")
    assert box.input_value() == ""
    c.page.keyboard.press("Escape")
    c.page.locator("#sysCheck").wait_for(state="hidden")
    c.page.wait_for_timeout(300)
    assert chats == []  # no AI call for the phrase
    box.fill("check my systems design doc")
    box.press("Enter")
    c.page.wait_for_function("() => document.getElementById('input').value === ''")
    c.page.wait_for_timeout(500)
    assert len(chats) >= 1 and "systems design doc" in chats[0]
    assert not c.page.locator("#sysCheck").is_visible()


POSITIVE = [
    "run a systems check", "Run a systems check.", "systems check", "System check",
    "run diagnostics", "Jarvis, run a systems check", "hey jarvis systems check",
    "JARVIS: system status?", "run a system check", "Jarvis, system status",
    "hey jarvis system status",
]  # fmt: skip
NEGATIVE = [
    "check my systems design doc", "run a systems check on the Delhi server", "systems",
    "what is the system status of the order", "run the dishwasher", "",
    "jarvis", "diagnostics for the car", "system check please email Nilesh",
    "system status", "systems status", CLOSING, SPOKEN, "Closing this window, Sir.",
]  # fmt: skip


def test_matches_only_the_systems_check_phrases(make: Any) -> None:
    c, _ = make(store=SILENT)
    got = c.page.evaluate(
        "([p, n]) => [p.map(t => window.JarvisSystemsCheck.matches(t)), "
        "n.map(t => window.JarvisSystemsCheck.matches(t))]",
        [POSITIVE, NEGATIVE],
    )
    assert got[0] == [True] * len(POSITIVE)
    assert got[1] == [False] * len(NEGATIVE)


# ---- the Systems card ----------------------------------------------------------------------------
def test_the_systems_card_rows_are_tidy(make: Any) -> None:
    c, _ = make(store=SILENT)
    c.open_panel("integrations")
    card = c.page.locator("#systemsCard")
    card.locator(".event").first.wait_for()
    assert card.get_attribute("data-state") == "down"
    rows = card.locator(".event")
    assert rows.count() == 4
    tg = card.locator('.event[data-key="telegram"]')
    assert tg.locator(".dot.bad").count() == 1
    assert tg.locator(".v").text_content() == "Down"
    assert tg.locator(".what small").text_content() == "the bot token was refused"
    style = c.page.evaluate(
        "() => { const l = document.querySelector('#systemsCard .syslist');"
        " const s = getComputedStyle(l); return [s.listStyleType, s.paddingLeft]; }"
    )
    assert style == ["none", "0px"]
    assert not c.page.locator("#systemsCard .bnote").is_visible()  # empty note: no bar
    c.page.evaluate(SETTLE_JS, "#p-integrations")  # measured after the panel's opening scale
    run, speak = card.locator(".actions .btn").all()
    left, right = run.bounding_box(), speak.bounding_box()
    assert left is not None and right is not None
    gap = right["x"] - (left["x"] + left["width"])
    assert gap >= 8
    meta = str(card.locator(".bmade").text_content())
    assert meta.startswith("Checked ") and "/" not in meta


# ---- layout, contrast ----------------------------------------------------------------------------
OVERLAPS_JS = """(sel) => {
  const root = document.querySelector(sel);
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const inter = [...root.querySelectorAll('button, select, input, a[href]')].filter(vis);
  const texts = [...root.querySelectorAll('*')].filter(e => vis(e) &&
    [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
  const bad = [];
  for (const a of inter) { const ra = a.getBoundingClientRect();
    for (const b of [...inter, ...texts]) { if (a === b || a.contains(b) || b.contains(a)) continue;
      const rb = b.getBoundingClientRect();
      const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      const said = (e) => (e.textContent || e.id || '').trim().slice(0, 20);
      if (w > 1 && h > 1) bad.push(said(a) + ' / ' + said(b)); } }
  const r = root.getBoundingClientRect();
  const out = [...root.querySelectorAll('*')].filter(vis).filter(e => {
    const k = e.getBoundingClientRect(); return k.right > r.right + 1 || k.left < r.left - 1; })
    .map(e => e.className || e.tagName);
  const least = window.innerWidth < 900 ? 44 : 24;
  const small = inter.filter(e => e.getBoundingClientRect().height < least)
    .map(e => (e.textContent || e.id).trim().slice(0, 20));
  const hscroll = document.documentElement.scrollWidth > window.innerWidth;
  return { overlaps: bad, outside: out, small, hscroll };
}"""


@pytest.mark.parametrize("viewport", [PHONE, DESKTOP], ids=["phone", "desktop"])
@pytest.mark.parametrize("surface", ["night", "day"])
def test_no_overlap_or_overflow_and_aa_contrast(
    make: Any, viewport: dict[str, int], surface: str
) -> None:
    c, _ = make(viewport=viewport, store={**SILENT, "jarvis_surface": surface})
    assert c.page.locator("html").get_attribute("data-surface") == surface
    open_check(c, close_after_ms=600000)
    done(c)
    c.page.evaluate(SETTLE_JS, "#sysCheck")
    box = c.page.locator("#sysCheck").bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= viewport["width"]
    for sel in ("#sysCheckClose", "#sysCheck .sccount", "#sysCheck .scx"):  # always in view
        b = c.page.locator(sel).bounding_box()
        assert b is not None and 0 <= b["y"] and b["y"] + b["height"] <= viewport["height"], sel
    found = c.page.evaluate(CONTRAST_JS, "#sysCheck")
    assert len(found) > 15
    low = [x for x in found if x["ratio"] < 4.5]
    assert low == [], low
    # the flowed layout (the sticky top and foot cover what scrolls under them, by design)
    c.page.evaluate("document.querySelector('#sysCheck').style.maxHeight = 'none'")
    got = c.page.evaluate(OVERLAPS_JS, "#sysCheck")
    assert got == {"overlaps": [], "outside": [], "small": [], "hscroll": False}, got
    c.page.keyboard.press("Escape")
    c.open_panel("integrations")
    c.page.locator("#systemsCard .event").first.wait_for()
    c.page.evaluate(SETTLE_JS, "#systemsCard")
    card = c.page.evaluate(CONTRAST_JS, "#systemsCard")
    assert [x for x in card if x["ratio"] < 4.5] == []
    got = c.page.evaluate(OVERLAPS_JS, "#systemsCard")
    assert got["overlaps"] == [] and got["outside"] == [] and got["small"] == [], got
    assert c.errors == [] and c.csp_violations() == []


# ---- review fixes --------------------------------------------------------------------------------
TYPED_YES = [
    "run a systems check", "Run a systems check.", "Jarvis, run a systems check",
    "hey jarvis system status",
    "system status", "Systems check!", "jarvis: run diagnostics?", "Run a system check",
]  # fmt: skip
TYPED_NO = [
    "run a systems check on the Delhi server", "what is the system status of the order",
    "system status of the order please", "ok jarvis run a systems check now", "jarvis",
    "can you run a systems check", "run a systems check, then email Nilesh", "",
    "run a systems check\nand tell me a joke", CLOSING,
]  # fmt: skip


def test_typed_text_must_be_the_whole_phrase(make: Any) -> None:
    c, _ = make(store=SILENT)
    got = c.page.evaluate(
        "([y, n]) => [y.map(t => window.JarvisSystemsCheck.matches(t, {typed: true})), "
        "n.map(t => window.JarvisSystemsCheck.matches(t, {typed: true}))]",
        [TYPED_YES, TYPED_NO],
    )
    assert got[0] == [True] * len(TYPED_YES)
    assert got[1] == [False] * len(TYPED_NO)


def test_voice_bare_system_status_needs_the_name_in_the_router_too(make: Any) -> None:
    c, _ = make(store=SILENT)
    bare = c.page.evaluate(
        "window.JarvisVoiceCommands.handle('system status', {source: 'voice', state: 'listening'})"
    )
    assert bare["handled"] is False
    named = c.page.evaluate(
        "window.JarvisVoiceCommands.handle('Jarvis, system status', "
        "{source: 'voice', state: 'listening'})"
    )
    assert named["handled"] is True and named["id"] == "systems.check"


def test_the_closing_line_and_the_briefing_never_match_a_voice_command(make: Any) -> None:
    c, _ = make(store=SILENT)
    for line in (CLOSING, SPOKEN):
        got = c.page.evaluate(
            "t => [window.JarvisSystemsCheck.matches(t), window.JarvisSystemsCheck.matches(t, "
            "{named: true}), window.JarvisSystemsCheck.matches(t, {typed: true})]",
            line,
        )
        assert got == [False, False, False]
    handled = c.page.evaluate(
        "t => window.JarvisVoiceCommands.handle(t, {source: 'voice', state: 'listening'})", CLOSING
    )
    assert handled["handled"] is False


def test_no_voice_command_while_the_pop_up_speaks_or_for_two_seconds_after(make: Any) -> None:
    c, f = make()
    c.page.evaluate(SPEAKER)
    open_check(c, close_after_ms=600000)
    done(c)
    ask = (
        "window.JarvisVoiceCommands.handle('Jarvis, run a systems check', "
        "{source: 'voice', state: 'listening'})"
    )
    assert c.page.evaluate(ask)["handled"] is False  # the briefing is playing
    c.page.evaluate("window.__endSpeech()")
    assert c.page.evaluate(ask)["handled"] is False  # it only just ended
    assert len(f.named("stream")) == 1
    c.page.wait_for_timeout(2200)
    echo = c.page.evaluate(
        "t => window.JarvisSystemsCheck.canHear(t)", "shall I set a reminder to fix this"
    )
    assert echo is False  # mostly the pop-up's own words, a moment ago
    assert c.page.evaluate("window.JarvisSystemsCheck.canHear('what is the weather')") is True
    c.page.wait_for_timeout(1200)  # past the 3 s the mic loop allows for reverb
    assert c.page.evaluate(ask)["handled"] is True  # the owner, after the quiet
    c.page.locator("#sysCheck").wait_for(state="visible")


def test_clicking_during_speech_means_no_countdown_when_it_ends(make: Any) -> None:
    c, _ = make()
    c.page.evaluate(SPEAKER)
    open_check(c, close_after_ms=800)
    done(c)
    box = c.page.locator("#sysCheck .sclist").bounding_box()
    assert box is not None
    c.page.mouse.click(box["x"] + 20, box["y"] + 10)  # JARVIS is still speaking
    c.page.evaluate("window.__endSpeech()")
    c.page.wait_for_timeout(1800)  # well past the 800 ms countdown
    assert c.page.locator("#sysCheck").is_visible()
    assert c.page.locator("#sysCheck .sccount").text_content() == ""  # no countdown, no "Kept open"


def test_touching_it_while_it_is_still_checking_keeps_it_open_too(make: Any) -> None:
    c, f = make(store=SILENT)
    f.hold_stream = True
    c.page.evaluate("window.JarvisSystemsCheck.open({closeAfterMs: 700})")
    c.page.locator("#sysCheck").wait_for(state="visible")
    for _ in range(100):
        if f.held_streams:
            break
        c.page.wait_for_timeout(30)
    c.page.keyboard.press("Shift")  # before the answer is in
    f.held_streams[0].fulfill(status=200, content_type="application/x-ndjson", body=stream_body())
    done(c)
    c.page.wait_for_timeout(2000)
    assert c.page.locator("#sysCheck").is_visible()
    assert c.page.locator("#sysCheck .sccount").text_content() == ""


def test_a_failed_check_never_closes_itself_and_is_logged(make: Any) -> None:
    c, _ = make(store=SILENT, done=False)
    c.page.evaluate("window.JarvisSystemsCheck.open({closeAfterMs: 600})")
    c.page.locator("#sysCheck .scstatus", has_text="did not complete").wait_for()
    c.page.wait_for_timeout(1800)
    assert c.page.locator("#sysCheck").is_visible()
    assert c.page.locator("#sysCheck .sccount").text_content() == ""
    assert c.page.locator("#sysCheckAgain").is_enabled()
    assert "Systems check: the check did not complete" in c.page.evaluate("window.__log")


def test_remind_buttons_stay_off_while_the_request_is_in_flight(make: Any) -> None:
    c, f = make(store=SILENT)
    f.hold_remind = True
    open_check(c)
    done(c)
    c.page.locator('#sysCheck .scwhen button[data-when="1h"]').click()
    for _ in range(100):
        if f.held:
            break
        c.page.wait_for_timeout(30)
    c.page.evaluate(
        "() => { const s = document.getElementById('sysRemKey'); s.disabled = false; "
        "s.value = 'google'; s.dispatchEvent(new Event('change', {bubbles: true})); }"
    )
    states = c.page.locator("#sysCheck .scwhen button").evaluate_all("b => b.map(x => x.disabled)")
    assert states == [True, True, True]  # changing the select did not re-enable them
    c.page.evaluate("document.querySelectorAll('#sysCheck .scwhen button').forEach(b => b.click())")
    assert len(f.named("remind")) == 1
    f.held[0].fulfill(status=200, content_type="application/json", body=json.dumps(f.remind_answer))
    c.page.locator("#sysCheck .scremnote", has_text="Reminder set").wait_for()
    assert len(f.named("remind")) == 1


TALK = """() => {
  const sp = window.JarvisVoice.speaker, fns = [];
  window.__said = []; window.__stopped = 0; window.__talking = true;  // someone is already talking
  sp.on = (k, fn) => { if (k === 'state') fns.push(fn); };
  sp.say = (t) => { window.__said.push(String(t)); };
  sp.stop = () => { window.__stopped++; window.__talking = false; };
  sp.speaking = () => window.__talking; sp.unlock = () => {}; sp.end = () => {};
  window.__fire = () => fns.forEach(f => f({ speaking: false, reason: 'done' }));
}"""


def test_only_the_end_of_its_own_utterance_counts(make: Any) -> None:
    c, _ = make()
    c.page.evaluate(TALK)
    open_check(c, close_after_ms=500)
    done(c)
    assert c.page.evaluate("window.__stopped") >= 1  # it did not queue behind the other speech
    assert c.page.evaluate("window.__said")[0] == SPOKEN
    c.page.evaluate("window.__talking = true")  # the briefing is playing
    c.page.evaluate("window.__fire()")  # an end event of something else, speaker still talking
    c.page.wait_for_timeout(1200)
    assert c.page.locator("#sysCheck .sccount").text_content() == ""  # not counting down yet
    c.page.evaluate("window.__talking = false; window.__fire()")  # its own end
    c.page.locator("#sysCheck .sccount", has_text="Closing in").wait_for(timeout=2000)


def test_close_works_even_if_the_voice_breaks_on_the_way_out(make: Any) -> None:
    c, _ = make()
    c.page.evaluate(SPEAKER)
    open_check(c, close_after_ms=600000)
    done(c)
    c.page.evaluate("window.JarvisVoice = { get speaker() { throw new Error('boom'); } }")
    c.page.locator("#sysCheckClose").click()
    c.page.locator("#sysCheck").wait_for(state="hidden", timeout=2000)
    c.page.evaluate("window.JarvisSystemsCheck.open({closeAfterMs: 600000})")
    c.page.locator("#sysCheck").wait_for(state="visible")
    c.page.keyboard.press("Escape")
    c.page.locator("#sysCheck").wait_for(state="hidden", timeout=2000)


def test_the_countdown_is_announced_politely_once_and_the_numbers_stay_silent(make: Any) -> None:
    c, _ = make(store=SILENT)
    open_check(c)
    done(c)
    live = c.page.locator("#sysCheck [aria-live='polite']")
    assert live.count() == 1
    live.filter(has_text="Closing in 10 seconds").wait_for(timeout=3000)
    assert live.text_content() == ("Closing in 10 seconds — press any key or click to keep it open")
    assert c.page.locator("#sysCheck .sccount").get_attribute("aria-hidden") == "true"
    c.page.keyboard.press("Shift")
    live.filter(has_text="Kept open").wait_for()
    assert c.page.locator("#sysCheck [role='status']").count() >= 1  # the status line is still live


def test_it_never_closes_while_focus_is_in_a_form_control(make: Any) -> None:
    c, _ = make(store=SILENT)
    open_check(c, close_after_ms=3000)
    done(c)
    c.page.locator("#sysRemKey").focus()
    c.page.wait_for_timeout(4500)
    assert c.page.locator("#sysCheck").is_visible()
