# tests/browser/test_usage.py — slice 7b in a real browser: rupees only (no "$" anywhere on the
# page or in the Brief's confirm dialog), this month's spend and its bar states in Vitals, the
# "Set limit" confirm rules (raise / remove ask and send confirm_raise; lower does not), the 402
# budget_reached note in the conversation, and AA contrast of the spend block on Night and Day.
from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from test_brief import CONTRAST_JS, SETTLE_JS  # same directory (pytest prepend import)
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

RATE = {"inr_per_usd": 95.24, "as_of": "2026-11-01", "source": "default"}
REACHED = (
    "This month's limit of ₹500 is used up (₹512.40 spent). Raise it in Vitals, or switch to the "
    "free brain."
)


def usage(
    used: float = 38.12,
    limit: int | None = 500,
    *,
    brains: list[dict[str, Any]] | None = None,
    rate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A UsageView exactly as GET /v1/usage answers it (src/jarvis/billing/service.py)."""
    pct = None if limit is None else round(used / limit * 100, 2)
    return {
        "month": "2026-11",
        "used_inr": used,
        "limit_inr": limit,
        "remaining_inr": None if limit is None else round(max(0.0, limit - used), 2),
        "percent": pct,
        "warn": pct is not None and pct >= 80,
        "reached": pct is not None and pct >= 100,
        "calls": 12,
        "by_brain": brains
        if brains is not None
        else [{"brain": "anthropic", "label": "Claude", "used_inr": used}],
        "rate": rate or RATE,
    }


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class FakeUsage:
    """Answers GET /v1/usage and PUT /v1/usage/budget like the server (confirm rule included)."""

    def __init__(self, page: Any, view: dict[str, Any]) -> None:
        self.view = copy.deepcopy(view)
        self.puts: list[dict[str, Any]] = []
        self.gets = 0
        page.route("**/v1/usage", self._get)
        page.route("**/v1/usage/budget", self._put)

    def _get(self, route: Any) -> None:
        self.gets += 1
        _json(route, 200, self.view)

    def _put(self, route: Any) -> None:
        req = route.request
        body = json.loads(req.post_data or "{}")
        self.puts.append({"body": body, "headers": dict(req.headers), "method": req.method})
        old, new = self.view["limit_inr"], body.get("monthly_limit_inr")
        unknown = self.view.get("limit_unreadable") is True  # any change needs the confirm
        raise_ = unknown or (old is not None and (new is None or new > old))
        if raise_ and body.get("confirm_raise") is not True:
            _json(route, 422, {"error": "invalid_budget", "detail": "confirm to raise it"})
            return
        self.view = usage(self.view["used_inr"], new)
        _json(route, 200, self.view)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory(viewport: dict[str, int] = DESKTOP, store: dict[str, str] | None = None) -> Console:
        c = Console(browser, server_url, token, viewport)
        if store:
            lines = [
                f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});" for k, v in store.items()
            ]
            c.page.add_init_script("".join(lines))
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _vitals(c: Console) -> Any:
    c.open_panel("vitals")
    spend = c.page.locator("#spend")
    spend.wait_for()
    return spend


def _quiet(c: Console, *statuses: str) -> list[str]:
    return [e for e in c.errors if not any(f"status of {s}" in e for s in statuses)]


# ---- rupees only ---------------------------------------------------------------------------------
NO_DOLLAR_JS = """() => [document.body.innerText, document.body.textContent]"""


def test_no_dollar_sign_anywhere_on_the_page_or_in_the_brief_dialog(
    make: Callable[..., Console],
) -> None:
    """The real server (mock brain on Claude model ids, so the brief's cost note is a priced one):
    a reply, every panel open, Vitals, and the Brief's AI confirm dialog — rupees, never '$'."""
    c = make()
    c.open()
    c.send("how much does this cost")
    for panel in (
        "chat",
        "brief",
        "approvals",
        "activity",
        "history",
        "integrations",
        "vitals",
        "construct",
    ):
        if not c.page.locator(f"#p-{panel}").is_visible():
            c.open_panel(panel)
    c.page.locator('#spend[data-state="none"]').wait_for()
    assert "₹" in str(c.page.locator("#sMonth").text_content())
    assert "₹" in str(c.page.locator("#sCost").text_content())
    assert "per US dollar" in str(c.page.locator("#sRate").text_content())
    inner, everything = c.page.evaluate(NO_DOLLAR_JS)
    assert "$" not in inner and "$" not in everything
    # the Brief's AI summary confirm shows the server's own cost note
    c.page.locator("#briefAi").wait_for()
    c.page.locator("#briefAi").click()
    dialog = c.page.locator("#briefDialog")
    dialog.wait_for(state="visible")
    words = str(dialog.text_content())
    assert "₹" in words and "a month" in words and "$" not in words
    c.page.keyboard.press("Escape")
    # the appearance menu too
    c.page.locator("#themeBtn").click()
    c.page.locator("#themeMenu").wait_for(state="visible")
    assert "$" not in str(c.page.evaluate("document.body.innerText"))
    assert c.errors == []


def test_rail_and_vitals_say_last_reply_by(make: Callable[..., Console]) -> None:
    c = make()
    c.open()
    c.send("hello")
    _vitals(c)
    assert c.page.locator("#p-vitals .kv span", has_text="Last reply by").count() == 1
    assert c.page.locator(".rail-r .k", has_text="Last reply by").count() == 1
    assert c.page.locator("#p-vitals .kv span", has_text="Model").count() == 0
    assert c.page.locator("#p-vitals .kv span", has_text="This conversation").count() == 1


# ---- the month figure and its bar ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("view", "state", "word", "width", "note"),
    [
        (usage(38.12, None), "none", "No limit set", None, ""),
        (usage(38.12, 500), "ok", "7% used", "7.6%", ""),
        (
            usage(412.0, 500),
            "warn",
            "82% used",
            "82.4%",
            "Over 80% of this month's limit is used.",
        ),
        (usage(512.4, 500), "reached", "Limit reached", "100%", "This month's limit is used up"),
    ],
)
def test_month_figure_bar_and_state_words(
    make: Callable[..., Console],
    view: dict[str, Any],
    state: str,
    word: str,
    width: str | None,
    note: str,
) -> None:
    c = make()
    FakeUsage(c.page, view)
    c.open()
    spend = _vitals(c)
    c.page.locator(f'#spend[data-state="{state}"]').wait_for()
    assert c.page.locator("#spendState").text_content() == word  # words, never colour alone
    fig = str(c.page.locator("#sMonth").text_content())
    assert fig.startswith("≈ ₹") and "$" not in fig
    of = str(c.page.locator("#sMonthOf").text_content())
    bar = c.page.locator("#sBar")
    if width is None:
        assert of == "" and bar.is_hidden()
    else:
        assert of == "of ₹500" and bar.is_visible()
        assert bar.locator("i").evaluate("el => el.style.width") == width
        assert bar.get_attribute("role") == "progressbar"
        assert "of ₹500 used" in str(bar.get_attribute("aria-valuetext"))
    got_note = str(c.page.locator("#spendNote").text_content())
    assert got_note.startswith(note) if note else got_note == ""
    if state == "reached":
        assert "until 1 Dec" in got_note or "until Dec 1" in got_note
    assert "Claude ≈ ₹" in str(c.page.locator("#sBrains").text_content())
    assert str(c.page.locator("#sRate").text_content()).startswith("₹95.24 per US dollar")
    assert "$" not in str(spend.text_content())
    assert c.errors == []


def test_a_failed_load_says_so_and_retries(make: Callable[..., Console]) -> None:
    c = make()
    down = {"on": True}
    c.page.route(
        "**/v1/usage",
        lambda r: (
            _json(r, 503, {"error": "x", "detail": "Firestore is waking up."})
            if down["on"]
            else _json(r, 200, usage())
        ),
    )
    c.open()
    _vitals(c)
    c.page.locator('#spend[data-state="error"]').wait_for()
    assert c.page.locator("#sMonth").text_content() == "—"  # never a made-up ₹0
    assert "Firestore is waking up." in str(c.page.locator("#spendNote").text_content())
    assert c.page.locator("#limitBtn").get_attribute("aria-disabled") == "true"
    down["on"] = False
    c.page.locator("#spendRetry").click()
    c.page.locator('#spend[data-state="ok"]').wait_for()
    assert _quiet(c, "503") == []


# ---- the limit: lower saves at once, raise / remove ask first ------------------------------------
def test_lower_saves_without_confirm_and_raise_asks_and_sends_confirm_raise(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeUsage(c.page, usage(38.12, 500))
    c.open()
    _vitals(c)
    page = c.page
    page.locator('#spend[data-state="ok"]').wait_for()
    # keyboard: Set limit opens the form with the current limit, focused
    page.locator("#limitBtn").focus()
    page.keyboard.press("Enter")
    page.locator("#limitForm").wait_for(state="visible")
    assert page.locator("#limitBtn").get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.activeElement.id") == "limitIn"
    assert page.locator("#limitIn").input_value() == "500"
    # lowering: one PUT, no confirm_raise, no dialog
    page.locator("#limitIn").fill("300")
    page.keyboard.press("Enter")
    page.locator("#sMonthOf", has_text="of ₹300").wait_for()
    assert [p["body"] for p in fake.puts] == [{"monthly_limit_inr": 300}]
    assert fake.puts[0]["method"] == "PUT"
    assert fake.puts[0]["headers"].get("x-requested-with") == "JARVIS"
    assert fake.puts[0]["headers"].get("authorization") == "Bearer " + c.token
    assert page.locator("#briefDialog").get_attribute("open") is None
    assert page.locator("#limitDialog").get_attribute("open") is None
    assert page.locator("#limitForm").is_hidden()
    assert page.evaluate("document.activeElement.id") == "limitBtn"
    assert "Monthly limit set to ₹300." in str(page.locator("#limitNote").text_content())
    # raising: the dialog asks; "Not now" (and Esc) send nothing
    page.locator("#limitBtn").click()
    page.locator("#limitIn").fill("1,000")
    page.locator("#limitSave").click()
    dialog = page.locator("#limitDialog")
    dialog.wait_for(state="visible")
    words = str(dialog.text_content())
    assert "Raise the monthly limit to ₹1,000?" in words and "₹700 more than now" in words
    assert "$" not in words
    assert page.evaluate("document.activeElement.id") == "limitDialogNo"  # the safe choice
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") == "limitDialogYes"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") == "limitDialogNo"  # focus stays inside
    page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    assert page.locator("#p-vitals").is_visible()  # Esc closed the dialog, not the panel
    page.locator("#limitSave").click()
    dialog.wait_for(state="visible")
    page.locator("#limitDialogNo").click()
    assert len(fake.puts) == 1
    # …and "Raise" sends the confirmation
    page.locator("#limitSave").click()
    page.locator("#limitDialogYes").click()
    page.locator("#sMonthOf", has_text="of ₹1,000").wait_for()
    assert fake.puts[-1]["body"] == {"monthly_limit_inr": 1000, "confirm_raise": True}
    assert len(fake.puts) == 2
    assert c.errors == []


def test_remove_asks_first_and_sends_null_with_confirm_raise(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeUsage(c.page, usage(10.0, 200))
    c.open()
    _vitals(c)
    page = c.page
    page.locator('#spend[data-state="ok"]').wait_for()
    page.locator("#limitBtn").click()
    page.locator("#limitRemove").click()
    dialog = page.locator("#limitDialog")
    dialog.wait_for(state="visible")
    assert "Remove the monthly limit?" in str(dialog.text_content())
    page.locator("#limitDialogNo").click()
    assert fake.puts == []
    page.locator("#limitRemove").click()
    page.locator("#limitDialogYes").click()
    page.locator('#spend[data-state="none"]').wait_for()
    assert fake.puts[-1]["body"] == {"monthly_limit_inr": None, "confirm_raise": True}
    assert page.locator("#spendState").text_content() == "No limit set"
    assert c.errors == []


def test_an_unreadable_limit_says_so_and_any_new_limit_asks_first(
    make: Callable[..., Console],
) -> None:
    """The server couldn't read the stored limit (fail closed): paid replies are paused, and as
    nobody knows what the limit was, even a small new one goes through the confirmation."""
    c = make()
    view = usage(38.12, None)
    view["limit_unreadable"] = True
    fake = FakeUsage(c.page, view)
    c.open()
    _vitals(c)
    page = c.page
    page.locator('#spend[data-state="unreadable"]').wait_for()
    assert page.locator("#spendState").text_content() == "Limit unreadable"
    note = str(page.locator("#spendNote").text_content())
    assert "can't read" in note and "paid AI" in note and "$" not in note
    assert page.locator("#sBar").is_hidden() and page.locator("#sMonthOf").text_content() == ""
    page.locator("#limitBtn").click()
    page.locator("#limitForm").wait_for(state="visible")
    assert page.locator("#limitIn").input_value() == ""
    assert page.locator("#limitRemove").is_hidden()
    page.locator("#limitIn").fill("300")
    page.keyboard.press("Enter")
    dialog = page.locator("#limitDialog")
    dialog.wait_for(state="visible")
    words = str(dialog.text_content())
    assert "Set the monthly limit to ₹300?" in words and "can't read" in words
    assert "$" not in words
    page.locator("#limitDialogNo").click()
    assert fake.puts == []
    page.locator("#limitSave").click()
    dialog.wait_for(state="visible")
    page.locator("#limitDialogYes").click()
    page.locator('#spend[data-state="ok"]').wait_for()
    assert fake.puts == [
        {
            "body": {"monthly_limit_inr": 300, "confirm_raise": True},
            "headers": fake.puts[0]["headers"],
            "method": "PUT",
        }
    ]
    assert c.errors == []


def test_a_stale_page_reloads_after_a_refused_lower_so_the_next_save_asks(
    make: Callable[..., Console],
) -> None:
    """The limit was lowered on another device: this page's "lower" is really a raise. The
    server refuses it; the page reloads the month, so saving again asks first."""
    c = make()
    fake = FakeUsage(c.page, usage(38.12, 500))
    c.open()
    _vitals(c)
    page = c.page
    page.locator('#spend[data-state="ok"]').wait_for()
    fake.view = usage(38.12, 200)  # changed elsewhere; this page still shows ₹500
    page.locator("#limitBtn").click()
    page.locator("#limitIn").fill("400")
    page.keyboard.press("Enter")
    page.locator("#limitErr", has_text="confirm").wait_for()
    assert [p["body"] for p in fake.puts] == [{"monthly_limit_inr": 400}]
    page.locator("#sMonthOf", has_text="of ₹200").wait_for()  # reloaded after the refusal
    assert page.locator("#limitForm").is_visible()
    page.locator("#limitSave").click()
    page.locator("#limitDialog").wait_for(state="visible")
    page.locator("#limitDialogYes").click()
    page.locator("#sMonthOf", has_text="of ₹400").wait_for()
    assert fake.puts[-1]["body"] == {"monthly_limit_inr": 400, "confirm_raise": True}
    assert _quiet(c, "422") == []


@pytest.mark.parametrize("bad", ["0", "abc", "100001", "12.5", "-4"])
def test_bad_limits_are_refused_before_any_request(make: Callable[..., Console], bad: str) -> None:
    c = make()
    fake = FakeUsage(c.page, usage(10.0, 200))
    c.open()
    _vitals(c)
    c.page.locator('#spend[data-state="ok"]').wait_for()
    c.page.locator("#limitBtn").click()
    c.page.locator("#limitIn").fill(bad)
    c.page.keyboard.press("Enter")
    err = c.page.locator("#limitErr")
    err.wait_for()
    assert "₹1 to ₹1,00,000" in str(err.text_content())
    assert c.page.locator("#limitIn").get_attribute("aria-invalid") == "true"
    assert fake.puts == []


def test_esc_in_the_form_cancels_and_keeps_the_panel(make: Callable[..., Console]) -> None:
    c = make()
    FakeUsage(c.page, usage(10.0, 200))
    c.open()
    _vitals(c)
    c.page.locator('#spend[data-state="ok"]').wait_for()
    c.page.locator("#limitBtn").click()
    c.page.locator("#limitIn").fill("50")
    c.page.locator("#limitCancel").focus()
    c.page.keyboard.press("Escape")
    assert c.page.locator("#limitForm").is_hidden() and c.page.locator("#p-vitals").is_visible()
    assert c.page.evaluate("document.activeElement.id") == "limitBtn"


def test_the_real_server_round_trip(make: Callable[..., Console]) -> None:
    """No fakes: lower, raise with the confirm, remove with the confirm; the server agrees."""
    c = make()
    c.open()
    _vitals(c)
    page = c.page
    page.locator('#spend[data-state="none"]').wait_for()
    page.locator("#limitBtn").click()
    page.locator("#limitIn").fill("250")
    page.keyboard.press("Enter")
    page.locator("#sMonthOf", has_text="of ₹250").wait_for()
    page.locator("#limitBtn").click()
    page.locator("#limitIn").fill("400")
    page.keyboard.press("Enter")
    page.locator("#limitDialogYes").click()
    page.locator("#sMonthOf", has_text="of ₹400").wait_for()
    page.locator("#limitBtn").click()
    page.locator("#limitRemove").click()
    page.locator("#limitDialogYes").click()
    page.locator('#spend[data-state="none"]').wait_for()
    assert c.errors == []


# ---- the conversation at the limit ---------------------------------------------------------------
def test_budget_reached_is_a_jarvis_note_in_the_conversation(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeUsage(c.page, usage(512.4, 500))
    c.page.route(
        "**/v1/chat", lambda r: _json(r, 402, {"error": "budget_reached", "detail": REACHED})
    )
    c.open()
    gets = fake.gets
    c.page.locator("#input").fill("one more question")
    c.page.locator("#send").click()
    note = c.page.locator("#log .sys.limit")
    note.wait_for()
    assert note.text_content() == REACHED  # the server's words, as text
    assert note.get_attribute("role") == "status"
    assert c.page.locator("#log .sys.error").count() == 0  # not a crash
    assert c.page.locator("#typing").count() == 0
    c.page.wait_for_timeout(300)
    assert fake.gets > gets  # Vitals reloads the month after the refusal
    assert _quiet(c, "402") == []


def test_a_reply_shows_its_cost_in_rupees(make: Callable[..., Console]) -> None:
    c = make()
    reply = {
        "session_id": "sess_x",
        "reply": "Here you are, Sir.",
        "tool_calls": 0,
        "pending_approvals": [],
        "trace_id": "t",
        "model": "claude-sonnet-5-5",
        "brain": "mock",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        },
        "cost_usd": 0.0049,
        "cost_inr": 0.4667,
        "total_cost_usd": 0.0102,
        "total_cost_inr": 0.9714,
        "latency_ms": 900,
        "turn_count": 2,
    }
    c.page.route("**/v1/chat", lambda r: _json(r, 200, reply))
    c.page.route("**/v1/sessions?limit=30", lambda r: _json(r, 200, []))
    c.open()
    c.page.locator("#input").fill("cost?")
    c.page.locator("#send").click()
    meta = c.page.locator(".row.jarvis .meta").last
    meta.wait_for()
    text = str(meta.text_content())
    assert "≈ ₹0.47" in text and "$" not in text
    _vitals(c)
    assert c.page.locator("#sCost").text_content() == "≈ ₹0.97"  # the conversation so far
    assert c.errors == []


# ---- design: contrast on both surfaces, phone width ----------------------------------------------
@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize(
    "view",
    [
        usage(38.12, 500),
        usage(412.0, 500),
        usage(512.4, 500),
        {**usage(38.12, None), "limit_unreadable": True},
    ],
)
def test_spend_block_meets_aa_contrast(
    make: Callable[..., Console], surface: str, view: dict[str, Any]
) -> None:
    c = make(store={"jarvis_surface": surface})
    FakeUsage(c.page, view)
    c.open()
    _vitals(c)
    c.page.locator('#spend:not([data-state="loading"])').wait_for()
    c.page.locator("#limitBtn").click()  # the form is measured too
    c.page.locator("#limitIn").fill("x")
    c.page.keyboard.press("Enter")
    c.page.locator("#limitErr").wait_for()
    c.page.evaluate(SETTLE_JS, "#p-vitals")
    found = c.page.evaluate(CONTRAST_JS, "#p-vitals")
    assert len(found) > 20
    low = [f for f in found if f["ratio"] < 4.5]
    assert low == [], low
    if view["limit_inr"] == 500 and view["used_inr"] < 400:  # the raise dialog too
        c.page.locator("#limitIn").fill("900")
        c.page.keyboard.press("Enter")
        c.page.locator("#limitDialog").wait_for(state="visible")
        c.page.evaluate(SETTLE_JS, "#limitDialog")
        found = c.page.evaluate(CONTRAST_JS, "#limitDialog")
        assert len(found) >= 4 and [f for f in found if f["ratio"] < 4.5] == []


@pytest.mark.parametrize("surface", ["night", "day"])
def test_limit_note_in_chat_meets_aa_contrast(make: Callable[..., Console], surface: str) -> None:
    c = make(store={"jarvis_surface": surface})
    c.page.route(
        "**/v1/chat", lambda r: _json(r, 402, {"error": "budget_reached", "detail": REACHED})
    )
    c.open()
    c.page.locator("#input").fill("hi")
    c.page.locator("#send").click()
    c.page.locator("#log .sys.limit").wait_for()
    c.page.evaluate(SETTLE_JS, "#log")
    found = [f for f in c.page.evaluate(CONTRAST_JS, "#log") if "limit of" in f["text"]]
    assert found and all(f["ratio"] >= 4.5 for f in found), found


def test_phone_vitals_fit_without_horizontal_scroll(make: Callable[..., Console]) -> None:
    c = make(PHONE)
    FakeUsage(c.page, usage(412.0, 500))
    c.open()
    c.open_panel("vitals")
    c.page.locator('#spend[data-state="warn"]').wait_for()
    c.page.locator("#limitBtn").click()
    c.page.wait_for_timeout(200)
    widths = c.page.evaluate(
        "[document.documentElement.scrollWidth, document.body.scrollWidth, window.innerWidth,"
        " document.getElementById('p-vitals').scrollWidth,"
        " document.getElementById('p-vitals').clientWidth]"
    )
    assert widths[0] <= widths[2] and widths[1] <= widths[2], widths
    assert widths[3] <= widths[4] + 1, widths  # nothing inside the panel overflows sideways
    assert c.page.locator("#limitSave").is_visible() and c.page.locator("#limitCancel").is_visible()
    assert c.errors == []


def test_paths_used_are_the_consoles_own(make: Callable[..., Console]) -> None:
    c = make()
    seen: list[str] = []
    c.page.on("request", lambda r: seen.append(urlsplit(r.url).path))
    FakeUsage(c.page, usage())
    c.open()
    _vitals(c)
    c.page.locator('#spend[data-state="ok"]').wait_for()
    assert "/v1/usage" in seen
    assert all(not p.startswith("//") for p in seen)
