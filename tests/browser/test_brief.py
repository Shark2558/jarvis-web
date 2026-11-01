# tests/browser/test_brief.py — the morning Brief panel (slice 7) in a real browser. The
# /v1/brief/* endpoints are faked with page.route (shapes: section "API" of
# docs/plans/phase4-slice7-morning-brief.md), so these tests pin the console's side of the
# contract on their own: rendering (text only), the confirm dialogs and the flags they send, the
# 429 message, the morning auto-open + seen call, the
# phone tab bar, Motion Off, and text contrast on Night and Day. The last section pins the
# console/deploy review fixes (late script, hidden tab, time picker, 401, offline, hostile text).
from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from test_console import DESKTOP, LINKED, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright, expect = _pw.sync_playwright, _pw.expect

pytestmark = pytest.mark.browser

TODAY = "2026-11-01"
HOSTILE = '<img src=x onerror="window.__pwned=1">Lunch'
AI_LABEL = "AI summary — written from your calendar and other people's emails; may be wrong"
COST_NOTE = "About ₹3 a month on the Claude brain (Haiku)."


# Shapes below are the backend's exact ones (src/jarvis/api/brief.py: TodayView, BriefView,
# SettingsView), as the backend builder reported them for slice 7.
def _event(title: str, start: str, end: str, **extra: Any) -> dict[str, Any]:
    return {
        "title": title,
        "start": start,
        "end": end,
        "all_day": False,
        "starts_earlier": False,
        "ends_later": False,
        "location": None,
        "attendees": 0,
        "has_video": False,
        "overlaps_with": [],
        **extra,
    }


def settings_view(**over: Any) -> dict[str, Any]:
    view: dict[str, Any] = {
        "enabled": True,
        "time": "07:00",
        "ai_summary": True,
        "inbox_delivery": True,
        "updated_at": "2026-10-31T18:00:00Z",
    }
    view.update(over)
    return view


def brief_record(**over: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "date": TODAY,
        "tz": "Asia/Kolkata",
        "status": "ready",
        "trigger": "scheduled",
        "created_at": "2026-11-01T01:30:05Z",  # 07:00 in Asia/Kolkata
        "seen_at": "2026-11-01T02:00:00Z",
        "data": {
            "date": TODAY,
            "tz": "Asia/Kolkata",
            "calendar": {
                "today": [
                    _event("Diwali leave (team)", "", "", all_day=True),
                    _event("Server migration", "", "06:30", starts_earlier=True),
                    _event(
                        "Stand-up",
                        "09:30",
                        "10:00",
                        location="Room 4",
                        attendees=6,
                        has_video=True,
                        overlaps_with=["Vendor call"],
                    ),
                    _event("Vendor call", "09:45", "10:15", overlaps_with=["Stand-up"]),
                    _event(HOSTILE, "13:00", "13:30"),
                    _event("Release window", "22:00", "", ends_later=True),
                ],
                "clashes": 1,  # the server's count (one overlapping pair)
                "free_blocks": [
                    {"start": "10:15", "end": "12:00", "minutes": 105},
                    {"start": "14:00", "end": "18:00", "minutes": 240},
                ],
                "tomorrow_first": _event("Flight to Delhi", "08:30", "10:45", location="BLR T2"),
            },
            "inbox": {
                "total": 14,
                "items": [
                    {
                        "from_name": "Priya Nair",
                        "from_address": "priya@example.com",
                        "subject": "Budget sign-off needed",
                        "date": "2026-11-01T06:42:00+05:30",
                        "when": "06:42",
                    },
                    {
                        "from_name": "",
                        "from_address": "billing@vendor.example",
                        "subject": "Invoice 4471",
                        "date": "",
                        "when": "yesterday 21:10",
                    },
                ],
            },
            "jarvis": {"approvals_waiting": 2},
            "sections_status": {"calendar": "ok", "inbox": "ok", "jarvis": "ok"},
        },
        "ai": {
            "lines": [
                "Stand-up and the vendor call overlap at 09:45.",
                "Priya needs a budget sign-off today.",
            ],
            "model": "claude-haiku-5-5",
            "cost_usd": 0.000043,
            "label": AI_LABEL,
        },
        "ai_note": None,
        "text": "Brief for Sun 1 Nov …",
        "error": None,
        "inbox": {"status": "delivered", "at": "2026-11-01T01:30:09Z", "message_id": "18f0"},
        "ai_calls_today": 1,
        "generations_left": 4,
    }
    record.update(over)
    return record


def today_state(**over: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "date": TODAY,
        "tz": "Asia/Kolkata",
        "status": "ready",
        "brief": brief_record(),
        "settings": settings_view(),
        "due_at": "2026-11-01T07:00:00+05:30",
        "google_connected": True,
        "ai_available": True,
        "inbox_available": True,
        "ai_cost_note": COST_NOTE,
    }
    state.update(over)
    return state


def refuse_settings(body: dict[str, Any]) -> str | None:
    """The backend's 422 rules for PUT /v1/brief/settings (plain-English detail, or None)."""
    if body.get("ai_summary") is True and body.get("confirm_spend") is not True:
        return "Switching on the AI summary needs your confirmation (confirm_spend)."
    if body.get("inbox_delivery") is True and body.get("confirm_inbox") is not True:
        return "Putting the brief in your inbox needs your confirmation (confirm_inbox)."
    return None


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


Answer = Callable[[Any, dict[str, Any]], None]


class FakeBrief:
    """Answers /v1/brief/* (and /v1/integrations) for one page; records every request.

    A path in `holding` is recorded but not answered (a slow server) until `release()`."""

    def __init__(
        self,
        page: Any,
        today: dict[str, Any],
        *,
        generate: Callable[[dict[str, Any]], tuple[int, Any]] | None = None,
        settings: Callable[[dict[str, Any]], tuple[int, Any]] | None = None,
        integrations: dict[str, Any] | None = LINKED,
    ) -> None:
        self.today = copy.deepcopy(today)
        self.calls: list[dict[str, Any]] = []
        self.holding: set[str] = set()
        self.held: list[tuple[Any, dict[str, Any], Answer]] = []
        self._generate = generate
        self._settings = settings
        page.route("**/v1/brief/today", self._handler(self._answer_today))
        page.route("**/v1/brief/generate", self._handler(self._answer_generate))
        page.route("**/v1/brief/seen", self._handler(self._answer_seen))
        page.route("**/v1/brief/settings", self._handler(self._answer_settings))
        if integrations is not None:
            page.route("**/v1/integrations", lambda r: _json(r, 200, integrations))

    def _record(self, route: Any) -> dict[str, Any]:
        req = route.request
        call = {
            "path": urlsplit(req.url).path,
            "method": req.method,
            "body": json.loads(req.post_data) if req.post_data else None,
            "headers": dict(req.headers),
        }
        self.calls.append(call)
        return call

    def _handler(self, answer: Answer) -> Callable[[Any], None]:
        def handle(route: Any) -> None:
            call = self._record(route)
            if call["path"] in self.holding:
                self.held.append((route, call, answer))
                return
            answer(route, call)

        return handle

    def release(self) -> None:
        """Stop holding and answer every held request, oldest first."""
        self.holding.clear()
        held, self.held = self.held, []
        for route, call, answer in held:
            answer(route, call)

    def to(self, path: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["path"] == path]

    def _answer_today(self, route: Any, call: dict[str, Any]) -> None:
        _json(route, 200, self.today)

    def _answer_generate(self, route: Any, call: dict[str, Any]) -> None:
        body = call["body"] or {}
        if self._generate is not None:
            _json(route, *self._generate(body))
            return
        # trigger=open makes nothing while the brief is switched off; anything else makes one
        if not (body.get("trigger") == "open" and not self.today["settings"]["enabled"]):
            trigger = body.get("trigger") or "manual"
            self.today = {
                **self.today,
                "status": "ready",
                "brief": brief_record(seen_at=None, trigger=trigger, generations_left=5),
            }
        _json(route, 200, self.today)  # TodayView, like GET /v1/brief/today

    def _answer_seen(self, route: Any, call: dict[str, Any]) -> None:
        date = (call["body"] or {}).get("date")
        _json(route, 200, {"ok": True, "date": date, "seen_at": "2026-11-01T03:00:00Z"})

    def _answer_settings(self, route: Any, call: dict[str, Any]) -> None:
        body = call["body"] or {}
        if self._settings is not None:
            _json(route, *self._settings(body))
            return
        refused = refuse_settings(body)
        if refused:
            _json(route, 422, {"error": "invalid_settings", "detail": refused})
            return
        fields = ("enabled", "time", "ai_summary", "inbox_delivery")
        merged = {**self.today["settings"], **{k: v for k, v in body.items() if k in fields}}
        merged["updated_at"] = "2026-11-01T03:00:00Z"
        self.today["settings"] = merged
        _json(route, 200, merged)  # SettingsView


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _console(
    browser: Any, url: str, token: str, viewport: dict[str, int], store: dict[str, str] | None
) -> Console:
    c = Console(browser, url, token, viewport)
    if store:  # device preferences (surface, accent, motion) set before any script runs
        put = "localStorage.setItem({}, {});"
        lines = [put.format(json.dumps(k), json.dumps(v)) for k, v in store.items()]
        c.page.add_init_script("".join(lines))
    return c


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory(viewport: dict[str, int] = DESKTOP, store: dict[str, str] | None = None) -> Console:
        c = _console(browser, server_url, token, viewport, store)
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _view(c: Console) -> Any:
    view = c.page.locator("#brief .bview")
    view.wait_for()
    return view


def _pressed(c: Console, sel: str) -> str | None:
    return c.page.locator(sel).get_attribute("aria-pressed")


def _settings(c: Console) -> None:
    """Open the Brief's Settings disclosure (collapsed by default since slice 8, D12)."""
    btn = c.page.locator("#briefSetBtn")
    if btn.get_attribute("aria-expanded") != "true":
        btn.click()
    c.page.locator("#briefSetBody").wait_for(state="visible")


def _local_date(c: Console) -> str:
    return str(
        c.page.evaluate(
            "new Intl.DateTimeFormat([], {weekday: 'short', day: 'numeric', month: 'short',"
            " timeZone: 'UTC'}).format(Date.UTC(2026, 10, 1)).replace(/,/g, '')"
        )
    )


def _errors_except(c: Console, status: str) -> list[str]:
    return [e for e in c.errors if f"status of {status}" not in e]


# ---- rendering ---------------------------------------------------------------------------------
def test_full_brief_renders_every_section_as_plain_text(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeBrief(c.page, today_state())
    c.open()
    c.open_panel("brief")
    text = str(_view(c).text_content())
    day = _local_date(c)  # "Sun 1 Nov" / "Sun Nov 1": the browser's own locale decides the order
    for words in (
        day,
        "Made 07:00",
        "Scheduled",
        "6 events · 1 clash",  # the server's clash count (one pair), not a recount
        "All day",
        "…–06:30",
        "Began on an earlier day",
        "22:00–…",
        "Runs past midnight",
        "09:30–10:00",
        "Room 4 · 6 attendees · Video call",
        "Clashes with Vendor call",
        "Clashes with Stand-up",
        "10:15–12:00",
        "14:00–18:00",
        "Flight to Delhi",
        "14 unread",
        "Priya Nair",
        "06:42",
        "Budget sign-off needed",
        "billing@vendor.example",
        "yesterday 21:10",
        "Showing 2 of about 14.",
        AI_LABEL,
        "Stand-up and the vendor call overlap at 09:45.",
        "Model: claude-haiku-5-5",
        "Delivered",
        "In your inbox since 07:00.",
    ):
        assert words in text, words
    # hostile calendar text is shown as text, never parsed
    assert HOSTILE in text
    assert c.page.locator("#p-brief img").count() == 0
    assert c.page.evaluate("window.__pwned") is None
    # the live approvals count (0 on this server) beats the 07:00 snapshot (2)
    c.page.locator("#brief", has_text="Nothing waiting for your approval.").wait_for()
    # the settings mirror the server
    assert _pressed(c, "#briefOn") == "true"
    assert _pressed(c, "#briefAi") == "true"
    assert _pressed(c, "#briefInbox") == "true"
    sel = c.page.locator("#briefTime")
    assert sel.input_value() == "07:00"
    options = sel.locator("option").all_text_contents()
    assert len(options) == 16 and options[0] == "04:00" and options[-1] == "11:30"
    assert c.page.locator("#brief .bdate").text_content() == day
    # beside Refresh: what is left today (the date is not repeated up there)
    assert c.page.locator("#briefMeta").text_content() == "4 refreshes left today"
    refresh = c.page.locator("#briefRefresh")
    assert refresh.get_attribute("aria-label") == "Refresh brief, 4 left today"
    assert refresh.get_attribute("aria-disabled") == "false"
    assert c.page.locator(".bchip", has_text="10:15–12:00").get_attribute("title") == (
        "105 minutes free"
    )
    # already seen and already made: nothing to report, nothing to make
    assert fake.to("/v1/brief/seen") == [] and fake.to("/v1/brief/generate") == []
    assert c.csp_violations() == []
    assert c.errors == []


@pytest.mark.parametrize(
    "connected, words",
    [(False, "Connect Google to allow this."), (True, "Reconnect Google to allow this.")],
)
def test_without_google_the_brief_says_how_to_connect(
    make: Callable[..., Console], connected: bool, words: str
) -> None:
    c = make()
    no_ai = "No AI summary today: it needs the Claude brain."
    rec = brief_record(
        ai=None, ai_note=no_ai, inbox={"status": "off", "at": None, "message_id": None}
    )
    status = "ok" if connected else "not_connected"
    rec["data"]["sections_status"] = {"calendar": status, "inbox": status, "jarvis": "ok"}
    if not connected:
        rec["data"]["calendar"] = {
            "today": [],
            "clashes": 0,
            "free_blocks": [],
            "tomorrow_first": None,
        }
        rec["data"]["inbox"] = {"total": 0, "items": []}
    state = today_state(
        brief=rec,
        google_connected=connected,
        ai_available=False,
        inbox_available=False,
        settings=settings_view(time="07:30", ai_summary=False, inbox_delivery=False),
    )
    fake = FakeBrief(c.page, state)
    c.open()
    c.open_panel("brief")
    text = str(_view(c).text_content())
    if not connected:
        assert "Connect Google to see your calendar here." in text
        assert "Connect Google to see your mail here." in text
        assert c.page.locator("#briefIntegCal").is_visible()
    assert "Gmail" not in text  # inbox delivery off: no delivery line
    assert no_ai in text  # ai_note says why there is no AI summary
    assert AI_LABEL not in text  # no AI lines, so no AI label
    settings = str(c.page.locator("#briefSettings").text_content())
    assert words in settings
    assert "needs the Claude brain" in settings
    _settings(c)
    for toggle in ("#briefAi", "#briefInbox"):
        assert c.page.locator(toggle).get_attribute("aria-disabled") == "true"
        assert _pressed(c, toggle) == "false"
    # an unavailable toggle stays focusable (its reason is read out) but asks and sends nothing
    c.page.locator("#briefAi").click(force=True)
    c.page.locator("#briefInbox").focus()
    c.page.keyboard.press("Enter")
    assert c.page.locator("#briefDialog").get_attribute("open") is None
    assert fake.to("/v1/brief/settings") == []
    # the way forward is one press away
    c.page.locator("#briefReconnect").click()
    c.page.locator("#p-integrations").wait_for(state="visible")
    assert c.errors == []


# ---- confirms ----------------------------------------------------------------------------------
def test_ai_summary_asks_first_and_sends_confirm_spend(make: Callable[..., Console]) -> None:
    c = make()
    state = today_state(settings=settings_view(ai_summary=False, inbox_delivery=False))
    fake = FakeBrief(c.page, state)
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    page = c.page
    # keyboard: the toggle opens the dialog; focus lands on the safe choice and stays inside
    page.locator("#briefAi").focus()
    page.keyboard.press("Enter")
    dialog = page.locator("#briefDialog")
    dialog.wait_for(state="visible")
    words = str(dialog.text_content())
    assert "Uses Claude; never the free brain." in words and COST_NOTE in words
    assert page.evaluate("document.activeElement.id") == "briefDialogNo"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") == "briefDialogYes"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") == "briefDialogNo"
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.id") == "briefDialogYes"
    # Esc = Not now: nothing is sent, the panel stays, focus returns to the toggle
    page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    assert page.locator("#p-brief").is_visible()
    assert page.evaluate("document.activeElement.id") == "briefAi"
    assert fake.to("/v1/brief/settings") == []
    page.locator("#briefAi").click()
    page.locator("#briefDialogNo").click()
    assert fake.to("/v1/brief/settings") == []
    # yes → one PUT with the spend confirmation, sent with the console's CSRF header
    page.locator("#briefAi").click()
    page.locator("#briefDialogYes").click()
    page.locator('#briefAi[aria-pressed="true"]').wait_for()
    puts = fake.to("/v1/brief/settings")
    assert len(puts) == 1
    assert puts[0]["method"] == "PUT"
    assert puts[0]["body"] == {"ai_summary": True, "confirm_spend": True}
    assert puts[0]["headers"].get("x-requested-with") == "JARVIS"
    assert puts[0]["headers"].get("authorization") == "Bearer " + c.token
    assert "AI summary on." in str(page.locator("#briefNote").text_content())
    # switching it off spends nothing, so it asks nothing
    page.locator("#briefAi").click()
    page.locator('#briefAi[aria-pressed="false"]').wait_for()
    assert fake.to("/v1/brief/settings")[-1]["body"] == {"ai_summary": False}
    assert c.errors == []


def test_inbox_delivery_confirm_names_the_address_and_sends_confirm_inbox(
    make: Callable[..., Console],
) -> None:
    c = make()
    state = today_state(settings=settings_view(ai_summary=False, inbox_delivery=False))
    fake = FakeBrief(c.page, state)
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    c.page.locator("#briefInbox").click()
    dialog = c.page.locator("#briefDialog")
    dialog.wait_for(state="visible")
    words = str(dialog.text_content())
    assert "owner@example.com" in words and "Nothing is sent to anyone." in words
    c.page.locator("#briefDialogYes").click()
    c.page.locator('#briefInbox[aria-pressed="true"]').wait_for()
    puts = fake.to("/v1/brief/settings")
    assert [p["body"] for p in puts] == [{"inbox_delivery": True, "confirm_inbox": True}]
    # the time picker saves on its own, no confirm (nothing is spent or written to Gmail)
    c.page.locator("#briefTime").select_option("06:30")
    c.page.locator("#briefNote", has_text="06:30").wait_for()
    assert fake.to("/v1/brief/settings")[-1]["body"] == {"time": "06:30"}
    assert c.errors == []


LIMIT = "You've made 6 briefs today, Sir; the next one comes with tomorrow's brief."


@pytest.mark.parametrize(
    "answer, words",
    [
        ({"error": "brief_limit", "detail": LIMIT}, LIMIT),  # the server's own sentence
        ({"error": "brief_limit"}, "Brief limit reached for today."),  # no detail: ours
    ],
)
def test_refresh_past_the_daily_limit_says_so_kindly(
    make: Callable[..., Console], answer: dict[str, str], words: str
) -> None:
    c = make()
    fake = FakeBrief(c.page, today_state(), generate=lambda body: (429, answer))
    c.open()
    c.open_panel("brief")
    _view(c)
    c.page.locator("#briefRefresh").click()
    c.page.locator("#briefNote", has_text=words).wait_for()
    assert [g["body"] for g in fake.to("/v1/brief/generate")] == [{"force": True}]
    assert c.page.locator("#brief .bview").is_visible()  # the brief already made stays
    assert _errors_except(c, "429") == []
    assert c.csp_violations() == []


def test_no_refreshes_left_says_so_beside_the_refresh_button(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeBrief(c.page, today_state(brief=brief_record(generations_left=0)))
    c.open()
    c.open_panel("brief")
    _view(c)
    expect(c.page.locator("#briefMeta")).to_have_text("No refreshes left today")
    refresh = c.page.locator("#briefRefresh")
    assert refresh.get_attribute("aria-disabled") == "true"
    refresh.click(force=True)
    c.page.wait_for_timeout(200)
    assert fake.to("/v1/brief/generate") == []
    assert c.errors == []


def test_a_refused_setting_shows_the_servers_reason(make: Callable[..., Console]) -> None:
    c = make()
    reason = "The brief time must be on the hour or half hour, between 04:00 and 11:30."
    fake = FakeBrief(
        c.page,
        today_state(),
        settings=lambda body: (422, {"error": "invalid_settings", "detail": reason}),
    )
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    c.page.locator("#briefTime").select_option("08:00")
    c.page.locator("#briefNote", has_text=reason).wait_for()
    assert [p["body"] for p in fake.to("/v1/brief/settings")] == [{"time": "08:00"}]
    expect(c.page.locator("#briefTime")).to_have_value("07:00")  # shows what is really saved
    assert _errors_except(c, "422") == []


def test_failed_brief_shows_the_reason_and_tries_again(make: Callable[..., Console]) -> None:
    c = make()
    why = "Google Calendar didn't answer in time."
    failed = brief_record(status="failed", data=None, ai=None, error=why, seen_at=None)
    fake = FakeBrief(c.page, today_state(status="failed", brief=failed))
    c.open()
    c.open_panel("brief")
    box = c.page.locator("#brief")
    box.locator("text=Today's brief didn't finish.").wait_for()
    assert why in str(box.text_content())
    expect(c.page.locator("#briefMeta")).to_have_text("Didn't finish")
    assert fake.to("/v1/brief/seen") == []  # a failed brief is not "seen"
    c.page.locator("#briefTryAgain").click()
    _view(c)
    assert [g["body"] for g in fake.to("/v1/brief/generate")] == [{"force": True}]
    assert c.errors == []


# ---- the morning: auto-open, generate-on-open, seen ----------------------------------------------
def test_unseen_brief_opens_itself_on_a_computer_and_is_marked_seen(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeBrief(c.page, today_state(brief=brief_record(seen_at=None)))
    c.open()
    c.page.locator("#p-brief").wait_for(state="visible")  # nobody clicked
    _view(c)
    c.page.wait_for_timeout(300)  # the seen call is fire-and-forget
    seen = fake.to("/v1/brief/seen")
    assert [s["body"] for s in seen] == [{"date": TODAY}]
    assert seen[0]["headers"].get("x-requested-with") == "JARVIS"
    assert c.page.locator("#briefBadge").is_hidden()
    assert c.page.locator('.dk[data-open="brief"]').get_attribute("aria-pressed") == "true"
    # it opened beside the conversation without taking the keyboard away
    focus_in_brief = "document.getElementById('p-brief').contains(document.activeElement)"
    assert c.page.evaluate(focus_in_brief) is False
    assert c.page.locator("#p-chat").is_visible()
    assert c.errors == []


def test_opening_the_panel_makes_todays_brief_once(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeBrief(c.page, today_state(status="none", brief=None))
    c.open()
    expect(c.page.locator("#briefMeta")).to_have_text("Due 07:00")  # panel still closed
    assert fake.to("/v1/brief/generate") == []  # nothing is made until the owner looks
    c.open_panel("brief")
    _view(c)
    assert [g["body"] for g in fake.to("/v1/brief/generate")] == [{"trigger": "open"}]
    assert "Made on opening" in str(c.page.locator("#brief .bmade").text_content())
    c.page.wait_for_timeout(200)
    assert len(fake.to("/v1/brief/seen")) == 1  # made while watching = seen
    # closing and reopening does not make another one
    c.page.locator('.dk[data-open="brief"]').click()
    c.page.locator("#p-brief").wait_for(state="hidden")
    c.open_panel("brief")
    c.page.wait_for_timeout(300)
    assert len(fake.to("/v1/brief/generate")) == 1
    assert c.errors == []


# ---- phone ---------------------------------------------------------------------------------------
def test_phone_badges_the_brief_tab_then_shows_one_panel(make: Callable[..., Console]) -> None:
    c = make(PHONE)
    fake = FakeBrief(c.page, today_state(brief=brief_record(seen_at=None)))
    c.open()
    page = c.page
    page.locator("#briefBadge").wait_for(state="visible")
    tab = page.locator('.dk[data-open="brief"]')
    assert tab.get_attribute("aria-label") == "Brief, new brief ready"
    assert page.locator("#p-chat").is_visible() and page.locator("#p-brief").is_hidden()
    assert fake.to("/v1/brief/seen") == []  # a badge is not "seen"
    # eight tabs (seven panels + More), all on screen, each a usable touch target with its label
    tabs = page.evaluate(
        """[...document.querySelectorAll('#dock .dk')].filter(b => b.getClientRects().length)
           .map(b => {
             const r = b.getBoundingClientRect();
             const label = [...b.querySelectorAll('span')].find(s => s.offsetWidth);
             return {name: b.dataset.open || b.id, w: r.width, h: r.height, left: r.left,
                     right: r.right, fits: !label || label.scrollWidth <= b.clientWidth};
           })"""
    )
    assert len(tabs) == 8 and tabs[-1]["name"] == "dockMore", tabs
    width = page.evaluate("window.innerWidth")
    for t in tabs:
        assert t["w"] >= 44 and t["h"] >= 44, t
        assert t["left"] >= 0 and t["right"] <= width, t
        assert t["fits"], t
    tab.click()
    page.locator("#p-brief").wait_for(state="visible")
    _view(c)
    assert page.locator("#p-chat").is_hidden()
    visible = page.evaluate(
        "[...document.querySelectorAll('.panel[data-panel]')].filter(p => !p.hidden).length"
    )
    assert visible == 1
    page.wait_for_timeout(200)
    assert len(fake.to("/v1/brief/seen")) == 1
    assert page.locator("#briefBadge").is_hidden()
    assert tab.get_attribute("aria-label") is None  # back to its plain name, "Brief"
    assert page.locator("#briefRefresh").is_visible()
    widths = page.evaluate(
        "[document.documentElement.scrollWidth, document.body.scrollWidth, window.innerWidth]"
    )
    assert widths[0] <= widths[2] and widths[1] <= widths[2], widths
    assert c.errors == []


def test_very_narrow_phone_keeps_every_tab_named(make: Callable[..., Console]) -> None:
    c = make({"width": 340, "height": 720})
    FakeBrief(c.page, today_state())
    c.open()
    names = c.page.evaluate(
        """[...document.querySelectorAll('#dock .dk')].filter(b => b.getClientRects().length)
           .map(b => {
             const r = b.getBoundingClientRect();
             return {w: r.width, name: (b.getAttribute('aria-label') || b.textContent).trim()};
           })"""
    )
    assert len(names) == 8
    assert all(n["w"] >= 40 and n["name"] for n in names), names
    assert c.errors == []


def test_brief_switched_off_is_made_only_on_request(make: Callable[..., Console]) -> None:
    c = make()
    off = settings_view(enabled=False, ai_summary=False, inbox_delivery=False)
    fake = FakeBrief(c.page, today_state(status="none", brief=None, settings=off))
    c.open()
    c.open_panel("brief")
    c.page.locator("#brief", has_text="The morning brief is off.").wait_for()
    c.page.wait_for_timeout(300)
    assert fake.to("/v1/brief/generate") == []  # opening the panel makes nothing while it is off
    assert _pressed(c, "#briefOn") == "false"
    c.page.locator("#briefMake").click()
    _view(c)
    assert [g["body"] for g in fake.to("/v1/brief/generate")] == [{"trigger": "manual"}]
    assert c.errors == []


def test_integrations_lists_the_optional_inbox_permission(make: Callable[..., Console]) -> None:
    c = make()
    google = {
        **LINKED["google"],
        "scopes": [*LINKED["google"]["scopes"], "https://www.googleapis.com/auth/gmail.insert"],
    }
    FakeBrief(c.page, today_state(), integrations={"google": google})
    c.open()
    c.open_panel("integrations")
    scopes = c.page.locator("#integrations .scopes")
    scopes.wait_for()
    words = str(scopes.text_content())
    assert "Gmail: read, draft, send, put the morning brief in your inbox (optional)" in words
    assert "other permission" not in words
    assert c.errors == []


# ---- motion + contrast -------------------------------------------------------------------------
def test_motion_off_keeps_the_brief_still(make: Callable[..., Console]) -> None:
    c = make(store={"jarvis_motion": "off"})
    FakeBrief(c.page, today_state(status="generating", brief=None))
    c.open()
    c.open_panel("brief")
    c.page.locator("#brief .bprep").wait_for()
    running = c.page.evaluate(
        """(() => {
             const panel = document.getElementById('p-brief');
             return document.getAnimations().filter(a => a.playState === 'running'
               && a.effect && a.effect.target && panel.contains(a.effect.target)).length;
           })()"""
    )
    assert running == 0
    # someone else (the 07:00 tick) is making it: the panel checks by itself, so Refresh waits
    assert c.page.locator("#briefRefresh").get_attribute("aria-disabled") == "true"
    assert c.page.locator("#briefMeta").text_content() == "Preparing…"
    assert c.errors == []


# Entrance fades (panel, dialog, brief view) scale opacity while they run: let every finite
# animation on the measured element, its ancestors and its children finish first.
SETTLE_JS = """async (rootSel) => {
  const root = document.querySelector(rootSel);
  const mine = document.getAnimations().filter(a => {
    const t = a.effect && a.effect.target;
    if (!t || a.effect.getComputedTiming().iterations === Infinity) return false;
    return t.contains(root) || root.contains(t);
  });
  await Promise.all(mine.map(a => a.finished.catch(() => null)));
}"""

# Contrast of every visible text node inside `root`: the text colour (with opacity) over the
# backgrounds stacked under it, starting from the opaque panel colour the cards stand on.
CONTRAST_JS = """(rootSel) => {
  const root = document.querySelector(rootSel);
  const probe = document.createElement('div');
  probe.style.background = 'var(--panel-solid)';
  document.body.appendChild(probe);
  const nums = (s, sep) => s.split(sep).filter(Boolean).map(Number);
  const parse = (s) => {
    s = String(s).trim();
    let m = /^rgba?\\(([^)]+)\\)$/.exec(s);
    if (m) {
      const p = nums(m[1], /[\\s,\\/]+/);
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    }
    m = /^color\\(srgb ([^)]+)\\)$/.exec(s);
    if (!m) return null;
    const p = nums(m[1], /[\\s\\/]+/);
    return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1];
  };
  const base = parse(getComputedStyle(probe).backgroundColor);
  probe.remove();
  const over = (t, b, a) => [0, 1, 2].map(i => t[i] * a + b[i] * (1 - a));
  const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  const ratio = (a, b) => {
    const x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };
  const out = [];
  root.querySelectorAll('*').forEach(el => {
    if (!el.getClientRects().length || el.closest('[aria-hidden="true"]')) return;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
    const chain = [];
    for (let n = el; n && n !== root.parentElement; n = n.parentElement) chain.unshift(n);
    let bg = base, alpha = 1;
    chain.forEach(n => {
      const cs = getComputedStyle(n), c = parse(cs.backgroundColor);
      alpha *= parseFloat(cs.opacity);
      if (c && c[3] > 0) bg = over(c, bg, c[3]);
    });
    const fg = parse(getComputedStyle(el).color);
    const text = el.textContent.trim().slice(0, 50);
    out.push({ text, ratio: ratio(over(fg, bg, fg[3] * alpha), bg) });
  });
  return out;
}"""


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("accent", [None, "#FFFF00", "#000080"])
def test_brief_text_meets_aa_contrast(
    make: Callable[..., Console], surface: str, accent: str | None
) -> None:
    store = {"jarvis_surface": surface}
    if accent:
        store["jarvis_accent"] = accent
    c = make(store=store)
    rec = brief_record(
        inbox={"status": "unknown", "at": None, "message_id": None},
        ai_note="One AI call left today.",
        generations_left=0,  # the warn-coloured "No refreshes left today" is measured too
    )
    state = today_state(brief=rec, settings=settings_view(ai_summary=False))
    FakeBrief(c.page, state)
    c.open()
    c.open_panel("brief")
    _view(c)
    c.page.locator("#brief", has_text="Nothing waiting for your approval.").wait_for()
    c.page.evaluate(SETTLE_JS, "#p-brief")
    found = c.page.evaluate(CONTRAST_JS, "#p-brief")  # settings closed: their summary line
    assert any("AI summary off" in f["text"] for f in found)
    low = [f for f in found if f["ratio"] < 4.5]
    assert low == [], low
    _settings(c)  # and every settings row once opened
    c.page.evaluate(SETTLE_JS, "#p-brief")
    found = c.page.evaluate(CONTRAST_JS, "#p-brief")
    assert len(found) > 40  # every section was measured
    low = [f for f in found if f["ratio"] < 4.5]
    assert low == [], low
    # the confirm dialog too
    c.page.locator("#briefAi").click()
    c.page.locator("#briefDialog").wait_for(state="visible")
    c.page.evaluate(SETTLE_JS, "#briefDialog")
    found = c.page.evaluate(CONTRAST_JS, "#briefDialog")
    assert len(found) >= 5
    low = [f for f in found if f["ratio"] < 4.5]
    assert low == [], low
    assert c.errors == []


# ---- review findings: console (fresh-context review, 2026-11-01) --------------------------------
SIGNED_IN = "sessionStorage.setItem('jarvis_token', {})"  # boot() runs at once, no gate to fill


def _wait_calls(c: Console, fake: FakeBrief, path: str, n: int, timeout_ms: int = 5000) -> None:
    for _ in range(timeout_ms // 50):
        if len(fake.to(path)) >= n:
            return
        c.page.wait_for_timeout(50)
    raise AssertionError(f"{path}: {len(fake.to(path))} calls, expected {n}")


def _quiet_errors(c: Console) -> list[str]:
    """Page errors other than the refused/failed requests a test provokes on purpose."""
    return [e for e in c.errors if "status of" not in e and "ERR_FAILED" not in e]


@pytest.mark.parametrize("delay_ms", [0, 800])
def test_a_late_brief_script_still_loads_todays_brief_once(
    make: Callable[..., Console], delay_ms: int
) -> None:
    """M1: console-brief.js arriving after jarvis:ready (one-shot) must still load the brief."""
    c = make()
    fake = FakeBrief(c.page, today_state())
    if delay_ms:

        def late(route: Any) -> None:
            time.sleep(delay_ms / 1000)  # the page keeps running: console.js signs in meanwhile
            route.continue_()

        c.page.route("**/static/console-brief.js", late)
    c.page.add_init_script(SIGNED_IN.format(json.dumps(c.token)))
    c.page.goto(c.url)
    c.page.locator("#welcome").wait_for()
    expect(c.page.locator("#briefMeta")).to_have_text("4 refreshes left today")
    c.page.wait_for_timeout(300)
    assert len(fake.to("/v1/brief/today")) == 1  # on time: the event alone, never twice
    assert c.errors == []


HIDDEN_TAB = """
window.__hidden = true;
Object.defineProperty(Document.prototype, 'hidden', { configurable: true,
  get: () => window.__hidden });
Object.defineProperty(Document.prototype, 'visibilityState', { configurable: true,
  get: () => (window.__hidden ? 'hidden' : 'visible') });
"""
SHOW_TAB = "window.__hidden = false; document.dispatchEvent(new Event('visibilitychange'))"


def test_a_hidden_tab_marks_the_brief_seen_only_once_it_is_shown(
    make: Callable[..., Console],
) -> None:
    """M2: a background tab is not "looked at": no /seen until the tab is visible."""
    c = make()
    c.page.add_init_script(HIDDEN_TAB)
    fake = FakeBrief(c.page, today_state(brief=brief_record(seen_at=None)))
    c.open()
    c.page.locator("#p-brief").wait_for(state="visible")  # it waits there for the owner
    _view(c)
    c.page.wait_for_timeout(500)
    assert fake.to("/v1/brief/seen") == []
    c.page.evaluate(SHOW_TAB)
    _wait_calls(c, fake, "/v1/brief/seen", 1)
    c.page.wait_for_timeout(200)
    assert [s["body"] for s in fake.to("/v1/brief/seen")] == [{"date": TODAY}]
    assert c.page.locator("#briefBadge").is_hidden()
    assert c.errors == []


def test_a_hidden_tab_does_not_make_todays_brief_until_it_is_shown(
    make: Callable[..., Console],
) -> None:
    c = make()
    c.page.add_init_script(HIDDEN_TAB)
    fake = FakeBrief(c.page, today_state(status="none", brief=None))
    c.open()
    c.open_panel("brief")
    c.page.wait_for_timeout(400)
    assert fake.to("/v1/brief/generate") == []
    c.page.evaluate(SHOW_TAB)
    _view(c)
    assert [g["body"] for g in fake.to("/v1/brief/generate")] == [{"trigger": "open"}]
    assert c.errors == []


def test_arrow_keys_on_the_time_picker_save_the_time_they_stop_on(
    make: Callable[..., Console],
) -> None:
    """M3: three ArrowDowns from 07:00 → one PUT of 08:30, and the picker keeps showing it."""
    c = make()
    fake = FakeBrief(c.page, today_state())
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    sel = c.page.locator("#briefTime")
    sel.focus()
    for _ in range(3):
        c.page.keyboard.press("ArrowDown")
    c.page.locator("#briefNote", has_text="Brief time set to 08:30.").wait_for()
    assert [p["body"] for p in fake.to("/v1/brief/settings")] == [{"time": "08:30"}]
    assert sel.input_value() == "08:30"
    assert fake.today["settings"]["time"] == "08:30"
    assert c.page.evaluate("document.activeElement.id") == "briefTime"
    assert c.errors == []


def test_a_time_change_during_a_slow_save_is_sent_after_it(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeBrief(c.page, today_state())
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    fake.holding.add("/v1/brief/settings")
    sel = c.page.locator("#briefTime")
    sel.focus()
    c.page.keyboard.press("ArrowDown")
    _wait_calls(c, fake, "/v1/brief/settings", 1)  # 07:30 is on its way (held by the server)
    c.page.keyboard.press("ArrowDown")
    c.page.keyboard.press("ArrowDown")
    c.page.wait_for_timeout(600)
    assert sel.input_value() == "08:30"  # never snapped back to the saved 07:00 meanwhile
    assert len(fake.to("/v1/brief/settings")) == 1  # one PUT at a time
    fake.release()
    c.page.locator("#briefNote", has_text="Brief time set to 08:30.").wait_for()
    assert [p["body"] for p in fake.to("/v1/brief/settings")] == [
        {"time": "07:30"},
        {"time": "08:30"},
    ]
    assert sel.input_value() == "08:30" and fake.today["settings"]["time"] == "08:30"
    assert c.errors == []


def test_switch_on_confirmed_during_a_save_is_sent_after_it(make: Callable[..., Console]) -> None:
    """M3: "Switch on" while a time save is out used to be dropped without a word."""
    c = make()
    state = today_state(settings=settings_view(ai_summary=False, inbox_delivery=False))
    fake = FakeBrief(c.page, state)
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    fake.holding.add("/v1/brief/settings")
    c.page.locator("#briefTime").focus()
    c.page.keyboard.press("ArrowDown")  # 07:30, saved after a short pause
    c.page.keyboard.press("Tab")  # the AI summary switch is next
    c.page.keyboard.press("Enter")  # its dialog opens before that save starts
    c.page.locator("#briefDialog").wait_for(state="visible")
    _wait_calls(c, fake, "/v1/brief/settings", 1)
    c.page.locator("#briefDialogYes").click()
    c.page.wait_for_timeout(200)
    fake.release()
    c.page.locator('#briefAi[aria-pressed="true"]').wait_for()
    assert [p["body"] for p in fake.to("/v1/brief/settings")] == [
        {"time": "07:30"},
        {"ai_summary": True, "confirm_spend": True},
    ]
    assert c.errors == []


def test_a_401_hands_over_to_the_sign_in_gate_without_an_error_line(
    make: Callable[..., Console],
) -> None:
    """L1: api() gives a 401 its status, so the panel leaves it to the gate."""
    c = make()
    fake = FakeBrief(c.page, today_state())
    fake.holding.add("/v1/brief/today")  # recorded, then answered with a 401 below
    c.open()
    _wait_calls(c, fake, "/v1/brief/today", 1)
    route = fake.held.pop()[0]
    _json(route, 401, {"error": "unauthorized", "detail": "Sign in required."})
    c.page.locator("#gate.show").wait_for()
    c.page.wait_for_timeout(300)
    text = str(c.page.locator("#brief").text_content())
    assert "Couldn't" not in text and "Sign in required" not in text, text
    assert _quiet_errors(c) == []


def test_a_double_click_on_the_inbox_switch_keeps_one_dialog_open(
    make: Callable[..., Console],
) -> None:
    """L2: the second click (address lookup still out) used to close the first dialog."""
    c = make()
    state = today_state(settings=settings_view(ai_summary=False, inbox_delivery=False))
    fake = FakeBrief(c.page, state, integrations=None)
    no_address = {"google": {**LINKED["google"], "email": None}}  # every switch looks it up
    lookups: list[Any] = []
    hold = {"on": False}

    def integrations(route: Any) -> None:
        if hold["on"]:
            lookups.append(route)
        else:
            _json(route, 200, no_address)

    c.page.route("**/v1/integrations", integrations)
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    hold["on"] = True
    c.page.locator("#briefInbox").dblclick()
    c.page.wait_for_timeout(300)
    assert len(lookups) == 1  # one question at a time
    hold["on"] = False
    for r in lookups:
        _json(r, 200, no_address)
    dialog = c.page.locator("#briefDialog")
    dialog.wait_for(state="visible")
    c.page.wait_for_timeout(500)
    assert dialog.is_visible()
    c.page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    assert fake.to("/v1/brief/settings") == []
    assert c.errors == []


def test_a_network_failure_says_jarvis_cannot_be_reached(make: Callable[..., Console]) -> None:
    """L3: not the browser's "Failed to fetch"."""
    c = make()
    FakeBrief(c.page, today_state())
    c.open()
    c.open_panel("brief")
    _view(c)
    c.page.unroute("**/v1/brief/generate")
    c.page.route("**/v1/brief/generate", lambda r: r.abort())
    c.page.locator("#briefRefresh").click()
    note = c.page.locator("#briefNote")
    expect(note).to_have_text("Couldn't make the brief. Can't reach JARVIS. Check your connection.")
    assert "Failed to fetch" not in str(c.page.locator("#p-brief").text_content())
    assert _quiet_errors(c) == []


def test_the_console_transport_calls_only_its_own_paths(make: Callable[..., Console]) -> None:
    """L4: api() refuses anything but a single leading "/" (no other host, no relative path)."""
    c = make()
    FakeBrief(c.page, today_state())
    c.open()
    out = c.page.evaluate(
        """async () => {
          const res = {};
          for (const p of ['https://evil.example/x', '//evil.example/x', '/\\\\evil.example/x',
                           'v1/brains', '', null, '/v1/brains']) {
            try { await window.JarvisConsole.api(p); res[String(p)] = 'called'; }
            catch (e) { res[String(p)] = 'refused'; }
          }
          return res;
        }"""
    )
    assert out.pop("/v1/brains") == "called"
    assert set(out.values()) == {"refused"}, out
    assert c.csp_violations() == []  # refused before any request: nothing for the CSP to block
    assert c.errors == []


def test_inbox_dialog_esc_and_not_now_send_nothing(make: Callable[..., Console]) -> None:
    c = make()
    state = today_state(settings=settings_view(ai_summary=False, inbox_delivery=False))
    fake = FakeBrief(c.page, state)
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    dialog = c.page.locator("#briefDialog")
    c.page.locator("#briefInbox").click()
    dialog.wait_for(state="visible")
    c.page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    assert c.page.evaluate("document.activeElement.id") == "briefInbox"
    c.page.locator("#briefInbox").click()
    dialog.wait_for(state="visible")
    c.page.locator("#briefDialogNo").click()
    dialog.wait_for(state="hidden")
    c.page.wait_for_timeout(200)
    assert fake.to("/v1/brief/settings") == []
    assert _pressed(c, "#briefInbox") == "false"
    assert c.errors == []


def test_enter_in_a_confirm_dialog_means_not_now(make: Callable[..., Console]) -> None:
    c = make()
    state = today_state(settings=settings_view(ai_summary=False, inbox_delivery=False))
    fake = FakeBrief(c.page, state)
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    c.page.locator("#briefAi").click()
    dialog = c.page.locator("#briefDialog")
    dialog.wait_for(state="visible")
    c.page.keyboard.press("Enter")  # focus is on "Not now"
    dialog.wait_for(state="hidden")
    c.page.wait_for_timeout(200)
    assert fake.to("/v1/brief/settings") == []
    assert _pressed(c, "#briefAi") == "false"
    assert c.errors == []


@pytest.mark.parametrize(
    "toggle, status, detail",
    [
        ("#briefAi", 429, "Too many changes just now, Sir. Try again in a minute."),
        ("#briefInbox", 422, "Reconnect Google to allow this."),
    ],
)
def test_a_refused_switch_on_leaves_the_switch_off(
    make: Callable[..., Console], toggle: str, status: int, detail: str
) -> None:
    c = make()
    state = today_state(settings=settings_view(ai_summary=False, inbox_delivery=False))
    fake = FakeBrief(c.page, state, settings=lambda b: (status, {"error": "x", "detail": detail}))
    c.open()
    c.open_panel("brief")
    _view(c)
    _settings(c)
    c.page.locator(toggle).click()
    c.page.locator("#briefDialogYes").click()
    c.page.locator("#briefNote", has_text=detail).wait_for()
    assert len(fake.to("/v1/brief/settings")) == 1
    assert _pressed(c, toggle) == "false"
    assert _quiet_errors(c) == []


def test_refresh_double_click_makes_one_brief(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeBrief(c.page, today_state())
    c.open()
    c.open_panel("brief")
    _view(c)
    fake.holding.add("/v1/brief/generate")
    c.page.locator("#briefRefresh").dblclick()
    c.page.wait_for_timeout(300)
    assert len(fake.to("/v1/brief/generate")) == 1
    assert c.page.locator("#briefRefresh").get_attribute("aria-disabled") == "true"
    fake.release()
    expect(c.page.locator("#briefMeta")).to_have_text("5 refreshes left today")
    assert len(fake.to("/v1/brief/generate")) == 1
    assert c.errors == []


FAST_POLL = (  # the 4 s poll runs every 40 ms; nothing else changes speed
    "const __st = window.setTimeout.bind(window);"
    "window.setTimeout = (f, d, ...a) => __st(f, d === 4000 ? 40 : d, ...a);"
)
STILL = "Still preparing. Press Refresh to check again."


def test_polling_while_someone_else_makes_the_brief_stops_at_the_cap(
    make: Callable[..., Console],
) -> None:
    c = make()
    c.page.add_init_script(FAST_POLL)
    fake = FakeBrief(c.page, today_state(status="generating", brief=None))
    c.open()
    c.open_panel("brief")
    c.page.locator("#brief", has_text=STILL).wait_for()
    assert len(fake.to("/v1/brief/today")) == 1 + 15  # the first look + POLL_MAX
    c.page.wait_for_timeout(600)
    assert len(fake.to("/v1/brief/today")) == 16  # stopped
    refresh = c.page.locator("#briefRefresh")
    assert refresh.get_attribute("aria-disabled") == "false"
    refresh.click()  # someone else is making it: look again (and poll again), never make one
    _wait_calls(c, fake, "/v1/brief/today", 32)
    c.page.wait_for_timeout(600)
    assert len(fake.to("/v1/brief/today")) == 32
    assert fake.to("/v1/brief/generate") == []
    assert c.errors == []


# Every string the server sends, with markup in it: none of it may become an element, an
# attribute, a script, or a change to Object.prototype.
HOSTILE_TEXTS = [
    "<img src=x onerror=window.__pwned=1>",
    "<a href=javascript:window.__pwned=2>open</a>",
    "<script>window.__pwned=3</script>",
]
INERT_JS = """() => {
  const bad = [];
  for (const id of ['p-brief', 'briefDialog']) {
    document.getElementById(id).querySelectorAll('*').forEach(e => {
      for (const a of e.attributes) if (/^on/i.test(a.name)) bad.push(e.tagName + ':' + a.name);
      const tag = e.tagName.toUpperCase();
      if (['IMG', 'A', 'SCRIPT', 'IFRAME', 'OBJECT', 'EMBED', 'FORM', 'STYLE', 'LINK', 'META',
           'BASE', 'TEMPLATE'].includes(tag)) bad.push(tag);
    });
  }
  return { bad, pwned: window.__pwned ?? null, polluted: ({}).polluted ?? null };
}"""


def _hostile_today(h: str) -> dict[str, Any]:
    rec = brief_record(seen_at=None, trigger="__proto__", ai_note=h, error=h)
    data = rec["data"]
    cal = data["calendar"]
    for e in cal["today"]:
        e.update(title=h + e["title"], location=h, overlaps_with=[h])
    cal["free_blocks"] = [{"start": h, "end": h, "minutes": h}, *cal["free_blocks"]]
    cal["tomorrow_first"] = {**cal["tomorrow_first"], "title": h, "location": h, "start": h}
    for m in data["inbox"]["items"]:
        m.update(from_name=h, from_address=h, subject=h, when=h, date=h)
    rec["ai"] = {"lines": [h, "Second " + h], "label": h, "model": h, "cost_usd": 0}
    rec["inbox"] = {"status": "constructor", "at": h, "message_id": h}  # not a status we know
    rec["__proto__"] = {"polluted": "brief"}  # a JSON key, never a prototype
    data["__proto__"] = {"polluted": "data"}
    off = settings_view(ai_summary=False, inbox_delivery=False, time=h)
    state = today_state(brief=rec, tz=h, ai_cost_note=h, settings=off)
    state["__proto__"] = {"polluted": "today"}
    return state


def _inert(c: Console) -> None:
    found = c.page.evaluate(INERT_JS)
    assert found == {"bad": [], "pwned": None, "polluted": None}, found


@pytest.mark.parametrize("h", HOSTILE_TEXTS)
def test_markup_in_every_server_string_stays_text(make: Callable[..., Console], h: str) -> None:
    c = make()
    today = _hostile_today(h)
    failed = today_state(
        status="failed",
        brief=brief_record(status="failed", data=None, ai=None, error=h, seen_at=None),
        tz=h,
    )
    failed["__proto__"] = {"polluted": "generate"}
    made = {"n": 0}

    def generate(body: dict[str, Any]) -> tuple[int, Any]:
        made["n"] += 1
        return (429, {"error": "brief_limit", "detail": h}) if made["n"] == 1 else (200, failed)

    google = {"google": {**LINKED["google"], "email": h}}
    fake = FakeBrief(
        c.page,
        today,
        generate=generate,
        settings=lambda b: (422, {"error": "invalid_settings", "detail": h}),
        integrations=google,
    )
    fake.holding.add("/v1/brief/today")
    c.open()
    _wait_calls(c, fake, "/v1/brief/today", 1)
    _json(fake.held.pop()[0], 500, {"error": "server_error", "detail": h})  # first look fails
    fake.release()
    c.open_panel("brief")
    box = c.page.locator("#brief")
    box.locator("#briefRetry").wait_for()
    assert h in str(box.text_content())
    _inert(c)
    # the whole brief, every field hostile
    box.locator("#briefRetry").click()
    text = str(_view(c).text_content())
    assert h in text and "Second " + h in text
    assert "[object" not in text and "function" not in text  # server words map to ours or nothing
    assert c.page.locator("#brief .bdeliv").count() == 0
    assert h in str(c.page.locator("#briefSettings").text_content())  # the time zone line
    _inert(c)
    _settings(c)
    # the two confirm dialogs: the cost note, then the Google address
    dialog = c.page.locator("#briefDialog")
    c.page.locator("#briefAi").click()
    dialog.wait_for(state="visible")
    assert h in str(dialog.text_content())
    _inert(c)
    c.page.locator("#briefDialogNo").click()
    dialog.wait_for(state="hidden")
    c.page.locator("#briefInbox").click()
    dialog.wait_for(state="visible")
    assert h in str(dialog.text_content())
    _inert(c)
    c.page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    # a 429 detail, a 422 detail, then a failed brief's error
    c.page.locator("#briefRefresh").click()
    c.page.locator("#briefNote", has_text=h).wait_for()
    _inert(c)
    c.page.locator("#briefTime").select_option("08:00")
    _wait_calls(c, fake, "/v1/brief/settings", 1)
    c.page.locator("#briefNote", has_text=h).wait_for()
    _inert(c)
    c.page.locator("#briefRefresh").click()
    box.locator("text=Today's brief didn't finish.").wait_for()
    assert h in str(box.text_content())
    _inert(c)
    assert fake.to("/v1/brief/settings")[0]["body"] == {"time": "08:00"}
    assert c.csp_violations() == []
    assert _quiet_errors(c) == []


# ---- slice 8 (D12): the settings sit behind a remembered "Settings" disclosure -------------------
STORAGE_THROWS = """
Object.defineProperty(window, 'localStorage', { configurable: true,
  get() { throw new DOMException('blocked', 'SecurityError'); } });
"""


def test_brief_settings_start_collapsed_with_a_summary_and_are_remembered(
    make: Callable[..., Console],
) -> None:
    c = make()
    state = today_state(settings=settings_view(time="06:30", ai_summary=True, inbox_delivery=False))
    fake = FakeBrief(c.page, state)
    c.open()
    c.open_panel("brief")
    _view(c)
    page = c.page
    btn, body = page.locator("#briefSetBtn"), page.locator("#briefSetBody")
    assert btn.get_attribute("aria-expanded") == "false"
    assert btn.get_attribute("aria-controls") == "briefSetBody"
    assert body.is_hidden() and page.locator("#briefAi").is_hidden()
    expect(page.locator("#briefSetSum")).to_have_text("06:30 · AI summary on · Inbox copy off")
    assert btn.evaluate("b => b.closest('h3') !== null")  # a heading, for heading navigation
    # keyboard: Enter opens it, the rows show, the summary steps aside
    btn.focus()
    page.keyboard.press("Enter")
    body.wait_for(state="visible")
    assert btn.get_attribute("aria-expanded") == "true"
    assert page.locator("#briefSetSum").is_hidden()
    assert page.evaluate("localStorage.getItem('jarvis_brief_settings_open')") == "1"
    # a change made inside shows in the summary once closed again
    page.locator("#briefInbox").click()
    page.locator("#briefDialogYes").click()
    page.locator('#briefInbox[aria-pressed="true"]').wait_for()
    # remembered on this device: open after a reload
    page.reload()
    page.locator("#welcome").wait_for()
    c.open_panel("brief")
    _view(c)
    assert page.locator("#briefSetBtn").get_attribute("aria-expanded") == "true"
    assert page.locator("#briefTime").is_visible()
    page.locator("#briefSetBtn").click()
    page.locator("#briefSetBody").wait_for(state="hidden")
    expect(page.locator("#briefSetSum")).to_have_text("06:30 · AI summary on · Inbox copy on")
    assert page.evaluate("localStorage.getItem('jarvis_brief_settings_open')") == "0"
    page.reload()
    page.locator("#welcome").wait_for()
    c.open_panel("brief")
    _view(c)
    assert page.locator("#briefSetBtn").get_attribute("aria-expanded") == "false"
    assert [p["body"] for p in fake.to("/v1/brief/settings")] == [
        {"inbox_delivery": True, "confirm_inbox": True}
    ]
    assert c.csp_violations() == []
    assert c.errors == []


def test_brief_summary_says_when_the_brief_is_off(make: Callable[..., Console]) -> None:
    c = make()
    off = settings_view(enabled=False, ai_summary=False, inbox_delivery=False)
    FakeBrief(c.page, today_state(status="none", brief=None, settings=off))
    c.open()
    c.open_panel("brief")
    c.page.locator("#brief", has_text="Switch it on in Settings below").wait_for()
    expect(c.page.locator("#briefSetSum")).to_have_text(
        "Brief off · AI summary off · Inbox copy off"
    )
    assert c.errors == []


def test_brief_settings_work_when_storage_throws(make: Callable[..., Console]) -> None:
    """Private mode / blocked site data: the disclosure still opens and closes, nothing breaks."""
    c = make()
    c.page.add_init_script(STORAGE_THROWS)
    fake = FakeBrief(c.page, today_state(settings=settings_view(ai_summary=False)))
    c.open()
    c.open_panel("brief")
    _view(c)
    btn = c.page.locator("#briefSetBtn")
    assert btn.get_attribute("aria-expanded") == "false"
    btn.click()
    c.page.locator("#briefSetBody").wait_for(state="visible")
    c.page.locator("#briefAi").click()
    c.page.locator("#briefDialogYes").click()
    c.page.locator('#briefAi[aria-pressed="true"]').wait_for()
    btn.click()
    c.page.locator("#briefSetBody").wait_for(state="hidden")
    assert [p["body"] for p in fake.to("/v1/brief/settings")] == [
        {"ai_summary": True, "confirm_spend": True}
    ]
    assert c.errors == []
