# tests/browser/test_vitals_board.py -- R5.1 Part B (D1, D2) in a real browser: the Vitals board
# blends into the panel's theme. Automatic items render grouped, with WORDS on their status chips;
# a manual_unavailable answer still shows them with a plain note (never "couldn't open the Vitals
# list"); a 503 is a styled note with no add form; the "Track something JARVIS can't see" form is
# closed by default, puts every label ABOVE its input, shows no id field and sends a derived id;
# "Stop tracking" asks first. No overlapping controls, no sideways scroll at phone width, 44 px
# touch targets on phones, AA contrast on Night and Day, zero console errors and CSP violations.
from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from test_brief import CONTRAST_JS, SETTLE_JS  # same directory (pytest prepend import)
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

BOARD = "#vitals-board"
WORDS = {"ok": "OK", "amber": "Watch", "red": "Act now", "unknown": "Unknown"}


def item(pid: str, label: str, status: str, group: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": pid,
        "label": label,
        "kind": "key",
        "source": "auto",
        "limit": None,
        "used": None,
        "unit": "",
        "reset_at": None,
        "expires_at": None,
        "note": "",
        "status": status,
        "percent": None,
        "reason": "",
        "impact": "",
        "fix": "",
        "group": group,
    }
    base.update(kw)
    return base


ITEMS = [
    item(
        "brain_claude",
        "Claude (paid AI) key",
        "red",
        "keys",
        reason="was refused",
        impact="If this stops: paid AI replies stop; JARVIS answers with the free brain.",
        fix="Add credit or make a new key in the Anthropic console.",
    ),
    item("google_link", "Google sign-in", "ok", "keys", note="Connected."),
    item(
        "github_token",
        "GitHub token",
        "amber",
        "keys",
        limit=5000,
        used=1250,
        unit="calls this hour",
        percent=25.0,
        reset_at="2026-11-10T13:00:00+00:00",
        expires_at="2026-11-15T00:00:00+00:00",
        reason="expires in 5 days",
        impact="If this stops: JARVIS can't read your GitHub.",
        fix="Make a new token on GitHub and connect it again in the Connectors panel.",
    ),
    item(
        "telegram_bot",
        "Telegram bot",
        "unknown",
        "keys",
        reason="hasn't been checked yet",
        note="Run a systems check to test it.",
    ),
    item(
        "web_credits",
        "Web search allowance",
        "amber",
        "allowances",
        kind="quota",
        limit=1000,
        used=850,
        unit="credits",
        percent=85.0,
        reset_at="2026-12-01T00:00:00+05:30",
        reason="is at 85% of its limit",
        impact="If this stops: JARVIS can't search the web until the credits reset.",
        fix="Wait for the monthly reset.",
    ),
    item(
        "allowance_tts_chirp3-hd",
        "Voice (Chirp 3 HD)",
        "ok",
        "allowances",
        kind="allowance",
        limit=1000000,
        used=12000,
        unit="characters",
        percent=1.2,
    ),
    item(
        "ai_spend",
        "AI spend this month",
        "ok",
        "bills",
        kind="billing",
        limit=500,
        used=120,
        unit="₹",
        percent=24.0,
    ),
    item(
        "insurance",
        "Car insurance",
        "ok",
        "bills",
        kind="billing",
        source="manual",
        expires_at="2027-03-01T23:59:59+05:30",
    ),
]


def board(**over: Any) -> dict[str, Any]:
    b: dict[str, Any] = {
        "overall": "red",
        "items": copy.deepcopy(ITEMS),
        "spend": {"used_inr": 120, "limit_inr": 500, "text": "₹120 of ₹500 this month"},
        "manual_unavailable": False,
        "manual_note": "",
    }
    b.update(over)
    return b


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class FakeVitals:
    """GET /v1/vitals, PUT /v1/vitals/keys and DELETE /v1/vitals/keys/{id} like the server."""

    def __init__(self, page: Any, view: dict[str, Any] | None, *, status: int = 200) -> None:
        self.view = copy.deepcopy(view)
        self.status = status
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[str] = []
        self.taken_once = False  # the first create answers 409: the name was taken meanwhile
        page.route("**/v1/vitals", self._get)
        page.route("**/v1/vitals/keys", self._put)
        page.route("**/v1/vitals/keys/*", self._delete)

    def _get(self, route: Any) -> None:
        if self.status != 200:
            _json(route, self.status, {"detail": "Vitals is not available on this server."})
            return
        _json(route, 200, self.view)

    def _put(self, route: Any) -> None:
        body = json.loads(route.request.post_data or "{}")
        self.puts.append({"body": body, "headers": dict(route.request.headers)})
        assert self.view is not None
        if self.taken_once and body.get("create"):
            self.taken_once = False
            self.view["items"].append(item(body["id"], "Other tab", "ok", "bills", source="manual"))
            _json(route, 409, {"detail": "That name is taken."})
            return
        self.view["items"].append(item(body["id"], body["label"], "ok", "bills", source="manual"))
        _json(route, 200, {"saved": body["id"]})

    def _delete(self, route: Any) -> None:
        self.deletes.append(route.request.url.rsplit("/", 1)[1])
        _json(route, 200, {"removed": True})


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory(viewport: dict[str, int] = DESKTOP, surface: str = "night") -> Console:
        c = Console(browser, server_url, token, viewport)
        c.page.add_init_script(f"localStorage.setItem('jarvis_surface', {json.dumps(surface)});")
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _open(c: Console) -> Any:
    c.open()
    c.open_panel("vitals")
    root = c.page.locator(BOARD)
    root.locator(".vt-row, .bnote.bad:not(:empty)").first.wait_for()  # loaded, or refused
    return root


def _quiet(c: Console) -> list[str]:
    return [e for e in c.errors if "status of 503" not in e]


def _settle(c: Console) -> None:
    c.page.evaluate(SETTLE_JS, BOARD)


# ---- grouped automatic items, words on chips ----
def test_automatic_items_render_grouped_with_words_on_chips(make: Callable[..., Console]) -> None:
    c = make()
    FakeVitals(c.page, board())
    root = _open(c)

    heads = [t.strip() for t in root.locator(".vt-group h4").all_text_contents()]
    assert heads == ["Keys & connections", "Allowances & quotas", "Bills"]
    for it in ITEMS:
        row = root.locator(f'.vt-row[data-id="{it["id"]}"]')
        if it["id"] == "ai_spend":  # already the "This month" block above: never repeated
            assert row.count() == 0
            continue
        assert row.count() == 1, it["id"]
        chip = row.locator(".vt-chip")
        assert chip.text_content() == WORDS[it["status"]]
        assert chip.get_attribute("data-status") == it["status"]
    red = root.locator('.vt-row[data-id="brain_claude"]')
    assert "Claude (paid AI) key was refused." in red.inner_text()
    assert "If this stops" in red.inner_text() and "Anthropic console" in red.inner_text()
    ok = root.locator('.vt-row[data-id="google_link"]')
    assert "If this stops" not in ok.inner_text()  # impact/fix only when it needs attention
    web = root.locator('.vt-row[data-id="web_credits"]')
    assert "850 of 1,000 credits · 85%" in web.inner_text()
    assert web.locator(".mbar i").get_attribute("style") == "width: 85%;"
    assert "AI spend:" not in root.inner_text()
    overall = root.locator(".vt-sub .vt-chip")
    assert overall.text_content() == "Act now" and overall.get_attribute("data-status") == "red"
    assert root.locator(".rhead h3").text_content() == "Keys, allowances & bills"
    assert c.csp_violations() == [] and _quiet(c) == []


# ---- manual records unreadable, and the server down ----
def test_manual_unavailable_still_shows_the_automatic_items_and_a_note(
    make: Callable[..., Console],
) -> None:
    c = make()
    note = "The items you track yourself can't be read just now; everything else is shown."
    FakeVitals(c.page, board(manual_unavailable=True, manual_note=note))
    root = _open(c)

    assert root.locator(".vt-row").count() >= 6
    assert root.locator(".bnote", has_text="track yourself can't be read").is_visible()
    assert "couldn't open the Vitals list" not in c.page.locator("#p-vitals").inner_text()
    assert not root.locator(".vt-add").is_visible()  # nothing can be saved while it is down
    assert c.csp_violations() == [] and _quiet(c) == []


def test_a_503_is_a_styled_note_with_no_add_form(make: Callable[..., Console]) -> None:
    c = make()
    FakeVitals(c.page, None, status=503)
    root = _open(c)

    bad = root.locator(".bnote.bad")
    bad.wait_for()
    assert "not available on this server" in bad.text_content()
    assert root.locator(".vt-row").count() == 0
    assert not root.locator(".vt-add").is_visible()
    assert "Track a key" not in root.inner_text()
    assert c.csp_violations() == [] and _quiet(c) == []


# ---- the manual form ----
def _disclose(root: Any) -> Any:
    btn = root.locator(".vt-add .dsc")
    assert btn.get_attribute("aria-expanded") == "false"
    assert not root.locator(".vt-form").is_visible()
    btn.click()
    assert btn.get_attribute("aria-expanded") == "true"
    form = root.locator(".vt-form")
    form.wait_for()
    return form


def test_manual_form_is_closed_by_default_labels_sit_above_and_the_id_is_derived(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeVitals(c.page, board())
    root = _open(c)
    assert root.locator(".vt-add .dsc .dl").text_content() == "Track something JARVIS can't see"

    form = _disclose(root)

    labels = form.locator("label")
    assert labels.count() >= 5
    for i in range(labels.count()):
        lab = labels.nth(i)
        control = c.page.locator("#" + str(lab.get_attribute("for")))
        lb, cb = lab.bounding_box(), control.bounding_box()
        assert lb and cb and lb["y"] + lb["height"] <= cb["y"] + 0.5, lab.text_content()
        assert "Id" not in str(lab.text_content())
    assert form.locator("select").count() == 1
    form.locator("label", has_text="Name").click()  # the label focuses its own input
    c.page.keyboard.type("Insurance")
    form.locator("select").select_option("billing")
    limit_id = form.locator("label", has_text="Limit").get_attribute("for")
    c.page.locator(f"#{limit_id}").fill("1")
    form.locator("button.primary", has_text="Save").click()
    c.page.locator(BOARD, has_text="Saved.").wait_for()

    body = fake.puts[0]["body"]
    assert body["id"] == "insurance-2"  # "insurance" is already an id on the board: suffixed
    assert body["label"] == "Insurance" and body["kind"] == "billing" and body["limit"] == 1
    assert fake.puts[0]["headers"]["x-requested-with"] == "JARVIS"
    assert c.csp_violations() == [] and _quiet(c) == []


def test_an_unused_name_becomes_a_plain_slug(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeVitals(c.page, board())
    root = _open(c)
    form = _disclose(root)

    c.page.locator("#" + str(form.locator("label", has_text="Name").get_attribute("for"))).fill(
        "Domain: jarvis-home.in renewal"
    )
    form.locator("button.primary").click()
    c.page.locator(BOARD, has_text="Saved.").wait_for()

    assert fake.puts[0]["body"]["id"] == "domain-jarvis-home-in-renewal"


def test_stop_tracking_asks_first_and_keep_cancels(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeVitals(c.page, board())
    root = _open(c)
    row = root.locator('.vt-row[data-id="insurance"]')

    row.locator("button", has_text="Stop tracking").click()
    confirm = row.locator(".confirm")
    confirm.wait_for()
    assert fake.deletes == []
    confirm.locator("button", has_text="Keep").click()
    assert row.locator(".confirm").count() == 0
    row.locator("button", has_text="Stop tracking").click()
    row.locator(".confirm .btn.danger").click()
    c.page.locator(BOARD, has_text="Stopped tracking Car insurance").wait_for()

    assert fake.deletes == ["insurance"]
    assert c.csp_violations() == [] and _quiet(c) == []


def test_edit_reuses_the_form_and_keeps_the_id(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeVitals(c.page, board())
    root = _open(c)

    root.locator('.vt-row[data-id="insurance"] button', has_text="Edit").click()
    form = root.locator(".vt-form")
    form.wait_for()
    name = c.page.locator("#" + str(form.locator("label", has_text="Name").get_attribute("for")))
    assert name.input_value() == "Car insurance"
    name.fill("Car insurance (new)")
    form.locator("button.primary").click()
    c.page.locator(BOARD, has_text="Saved.").wait_for()

    assert fake.puts[0]["body"]["id"] == "insurance"


def test_closing_the_form_ends_an_edit(make: Callable[..., Console]) -> None:
    """Edit, collapse, open again to add: a new item, never the one being edited."""
    c = make()
    fake = FakeVitals(c.page, board())
    root = _open(c)
    root.locator('.vt-row[data-id="insurance"] button', has_text="Edit").click()
    root.locator(".vt-form").wait_for()

    root.locator(".vt-add .dsc").click()  # collapse
    form = _disclose(root)  # and open again
    name = c.page.locator("#" + str(form.locator("label", has_text="Name").get_attribute("for")))
    assert name.input_value() == "" and "Add" in str(form.locator(".vt-ftitle").text_content())
    name.fill("Passport")
    form.locator("button.primary").click()
    c.page.locator(BOARD, has_text="Saved.").wait_for()

    assert fake.puts[0]["body"]["id"] == "passport"


# ---- layout: overlaps, overflow, touch targets ----
CONTROLS = """const controls = (sel) =>
  [...document.querySelectorAll(['button', 'input', 'select'].map(t => sel + ' ' + t).join(','))]
    .filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');"""
OVERLAP_JS = (
    "(sel) => {"
    + CONTROLS
    + """
  const boxes = controls(sel).map(e => [e, e.getBoundingClientRect()]);
  const hit = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 &&
    a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
  const out = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const [ea, a] = boxes[i], [eb, b] = boxes[j];
    if (hit(a, b)) out.push((ea.textContent || ea.id) + ' / ' + (eb.textContent || eb.id));
  }
  return out;
}"""
)
FIT_JS = """(sel) => {
  const root = document.querySelector(sel);
  const body = root.closest('.pbody'), edge = body.getBoundingClientRect().right + 0.5;
  const wide = [...root.querySelectorAll('*')]
    .filter(e => e.getClientRects().length && e.getBoundingClientRect().right > edge)
    .map(e => e.className || e.tagName);
  return {page: document.documentElement.scrollWidth - window.innerWidth,
          body: body.scrollWidth - body.clientWidth, wide};
}"""
SMALL_JS = (
    "(sel) => {"
    + CONTROLS
    + """
  return controls(sel).map(e => [e.textContent || e.id, e.getBoundingClientRect().height])
    .filter(([, h]) => h < 44);
}"""
)


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_no_overlap_and_no_sideways_scroll(make: Callable[..., Console], viewport: dict) -> None:
    c = make(viewport)
    FakeVitals(c.page, board())
    root = _open(c)
    root.locator('.vt-row[data-id="insurance"] button', has_text="Stop tracking").click()
    _disclose(root)
    _settle(c)

    assert c.page.evaluate(OVERLAP_JS, BOARD) == []
    fit = c.page.evaluate(FIT_JS, BOARD)
    assert fit["page"] <= 0 and fit["body"] <= 0 and fit["wide"] == [], fit
    if viewport is PHONE:
        assert c.page.evaluate(SMALL_JS, BOARD) == []
    assert c.csp_violations() == [] and _quiet(c) == []


def test_a_taken_name_reloads_and_retries_once_with_the_next_suffix(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeVitals(c.page, board())
    fake.taken_once = True
    root = _open(c)
    form = _disclose(root)

    c.page.locator("#" + str(form.locator("label", has_text="Name").get_attribute("for"))).fill(
        "Passport"
    )
    form.locator("button.primary").click()
    c.page.locator(BOARD, has_text="Saved.").wait_for()

    assert [p["body"]["id"] for p in fake.puts] == ["passport", "passport-2"]
    assert all(p["body"]["create"] is True for p in fake.puts)
    # the 409 itself is logged by the browser as a failed resource: that is the expected one
    assert c.csp_violations() == [] and [e for e in _quiet(c) if "409" not in e] == []


def test_edit_does_not_ask_for_create_only(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeVitals(c.page, board())
    root = _open(c)
    root.locator('.vt-row[data-id="insurance"] button', has_text="Edit").click()
    root.locator(".vt-form button.primary").click()
    c.page.locator(BOARD, has_text="Saved.").wait_for()

    assert "create" not in fake.puts[0]["body"]


def test_stopping_moves_focus_to_the_disclosure_and_a_failed_stop_says_so(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeVitals(c.page, board())
    root = _open(c)
    row = root.locator('.vt-row[data-id="insurance"]')
    row.locator("button", has_text="Stop tracking").click()
    row.locator(".confirm .btn.danger").click()
    c.page.locator(BOARD, has_text="Stopped tracking Car insurance").wait_for()
    assert c.page.evaluate("document.activeElement.className") == "dsc"
    assert fake.deletes == ["insurance"]

    c.page.route("**/v1/vitals/keys/*", lambda r: _json(r, 500, {"detail": "Storage is down."}))
    fake.view["items"].append(item("passport", "Passport", "ok", "bills", source="manual"))
    root.locator(".vt-sub button", has_text="Refresh").click()
    row = root.locator('.vt-row[data-id="passport"]')
    row.wait_for()
    row.locator("button", has_text="Stop tracking").click()
    row.locator(".confirm .btn.danger").click()
    err = root.locator("p.bnote.bad")
    err.filter(has_text="Couldn't stop tracking Passport").wait_for()
    assert "refresh" not in str(err.text_content())


def test_an_old_shadowed_record_can_be_stopped_but_not_edited(make: Callable[..., Console]) -> None:
    c = make()
    view = board()
    view["items"].append(item("home_link", "Home thing (old)", "ok", "bills", source="manual"))
    FakeVitals(c.page, view)
    root = _open(c)
    acts = root.locator('.vt-row[data-id="home_link"][data-status] .vt-acts')
    acts.last.wait_for()

    assert acts.last.locator("button", has_text="Edit").count() == 0
    assert acts.last.locator("button", has_text="Stop tracking").count() == 1


def test_on_a_phone_the_used_and_limit_inputs_are_wide_enough(make: Callable[..., Console]) -> None:
    c = make(PHONE)
    FakeVitals(c.page, board())
    root = _open(c)
    form = _disclose(root)
    widths = {}
    for text in ("Used so far", "Limit", "Unit"):
        fid = form.locator("label", has_text=text).get_attribute("for")
        widths[text] = c.page.locator(f"#{fid}").bounding_box()["width"]

    assert widths["Used so far"] >= 120 and widths["Limit"] >= 120, widths
    assert widths["Unit"] >= widths["Used so far"]


# ---- contrast ----
@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("accent", [None, "#FFFF00"])
def test_board_text_meets_aa_contrast(
    make: Callable[..., Console], surface: str, accent: str | None
) -> None:
    c = make(surface=surface)
    if accent:  # the hardest custom accent for the accent-ink group heads
        c.page.add_init_script(f"localStorage.setItem('jarvis_accent', {json.dumps(accent)});")
    FakeVitals(c.page, board())
    root = _open(c)
    root.locator('.vt-row[data-id="insurance"] button', has_text="Stop tracking").click()
    _disclose(root)
    _settle(c)

    found = c.page.evaluate(CONTRAST_JS, BOARD)
    assert len(found) > 30
    low = [f for f in found if f["ratio"] < 4.5]
    assert low == [], low
    assert c.csp_violations() == [] and _quiet(c) == []


@pytest.mark.parametrize("surface", ["night", "day"])
def test_notes_meet_aa_contrast(make: Callable[..., Console], surface: str) -> None:
    c = make(surface=surface)
    FakeVitals(c.page, board(manual_unavailable=True, manual_note="Can't be read just now."))
    _open(c)
    _settle(c)

    low = [f for f in c.page.evaluate(CONTRAST_JS, BOARD) if f["ratio"] < 4.5]
    assert low == [], low


def test_track_label_never_leaves_an_orphan_word_at_the_default_width(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVitals(c.page, board())
    root = _open(c)
    # The words of the label, measured line by line: a last line of one short word is an orphan.
    lines = root.locator(".vt-add .dsc .dl").evaluate(
        """el => {
          const r = document.createRange(), t = el.firstChild, rows = {};
          const words = t.textContent.split(' '); let at = 0;
          for (const w of words) {
            r.setStart(t, at); r.setEnd(t, at + w.length); at += w.length + 1;
            const b = r.getBoundingClientRect(), k = Math.round(b.top);
            (rows[k] = rows[k] || []).push(w);
          }
          return Object.keys(rows).sort((a, b) => a - b).map(k => rows[k]);
        }"""
    )
    assert lines, "label has no text"
    assert len(lines[-1]) >= 2 or len(lines) == 1, f"orphan word: {lines}"
