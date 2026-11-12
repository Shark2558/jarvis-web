# tests/browser/test_r11_1_a_plan.py -- R11.1 Part A (plan D0, D4-D6, D21-A) in headless Chromium:
# the Approvals panel with a 60-event batch card (every event in a scrolling list), a re-plan card
# (two head lines, then 54 "old date -> new date" lines in the same list) and a check-in question
# with Done / Skipped passes the visual gate (ui_checks.DOM_CHECKS_JS and the audit's own probes) at
# 1440x900 and 390x844, Night and Day, with no JS errors or CSP violations; "Skipped" only asks the
# server and reloads Approvals; under a reply, "Undo all" needs two taps and "Retry the N" asks for
# a card; the brief shows the inbox by kind. The card texts are made by the server's own functions.
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from r11_1_fakes_a import weekday_sessions
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean, _open
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

from jarvis.series import cards as plan_cards
from jarvis.series import replan
from jarvis.series.batch_result import create_words, undo_result
from jarvis.series.models import Plan, PlanSession
from jarvis.tools.calendar_cards import batch_card

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 24, 20, 20, tzinfo=IST)  # twenty minutes after session 7 ended
EVENTS = weekday_sessions(60)
BATCH = "b0123456789abcdef"
SID = "sess_plan_test"


def _plan() -> Plan:
    sessions = [
        PlanSession(
            n=i,
            event_id=f"ev{i:05d}",
            title=e["summary"],
            start=datetime.fromisoformat(e["start"]),
            end=datetime.fromisoformat(e["end"]),
            batch=BATCH,
            state="skipped" if i == 7 else "done" if i < 6 else "planned",
        )
        for i, e in enumerate(EVENTS, 1)
    ]
    return Plan(id="p0123456789ab", name="CCA", prefix="CCA", sessions=sessions,
                created_at=NOW, updated_at=NOW)  # fmt: skip


PLAN = _plan()
MOVES = replan.build(PLAN, 7, [], now=NOW, tz=IST, until=NOW + timedelta(weeks=20))
REPLAN = plan_cards.replan_card(PLAN, PLAN.sessions[6], MOVES, IST)
SKIPPED_SAID = (
    f"{plan_cards.marked(PLAN, PLAN.sessions[6])} A new schedule is waiting for your approval. "
    f"{REPLAN.splitlines()[0]}"
)


def _card(cid: str, tool: str, summary: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": cid,
        "tool": tool,
        "summary": summary,
        "arguments": arguments,
        "risk": "irreversible",
        "expires_at": "2026-11-24T15:00:00Z",
        "session_id": SID,
        "tool_risk": "reversible",
        "passkey_required": False,
        "reason": "owner_rule",
        "bulk_ok": True,
    }


BATCH_CARD = _card(
    "card-batch-0001",
    "calendar_create_events",
    batch_card(EVENTS, prefix="CCA", plan="CCA"),
    {"events": EVENTS, "title_prefix": "CCA", "series": {"name": "CCA"}},
)
MOVE_CARD = _card("card-move-0001", "series_reschedule", REPLAN, {"series": PLAN.id, "session": 7})
WAITING = {
    "plan": PLAN.id,
    "session": 6,
    "of": 60,
    "start": PLAN.sessions[5].start.isoformat(),
    "text": plan_cards.waiting_words(PLAN, PLAN.sessions[5], IST),
}
PLAN_ROW = {"id": PLAN.id, "name": "CCA", "sessions": 60, "done": 5, "skipped": 1,
            "replan": plan_cards.skipped_words(PLAN)}  # fmt: skip
REPLY_CARD = {
    "kind": "batch",
    "batch": BATCH,
    "total": 60,
    "created": 58,
    "already": 0,
    "failed": 2,
    "first": "2026-11-16",
    "last": "2027-02-05",
    "name": "CCA",
    "words": create_words(60, 58, 0, 2),
    "retry": [
        {
            **EVENTS[i - 1],
            "n": i,
            "description": "",
            "location": "",
            "reminders_minutes": None,
            "why": "Google refused it",
        }  # fmt: skip
        for i in (12, 40)
    ],
}
UNDONE = undo_result(BATCH, [{"n": i, "status": "removed"} for i in range(1, 59)])
DRAW_JS = """([cards]) => {
  const old = document.getElementById('plan-test-row'); if (old) old.remove();
  const row = document.createElement('div');
  row.className = 'row jarvis'; row.id = 'plan-test-row';
  const b = document.createElement('div'); b.className = 'bubble'; b.textContent = 'Done, Sir.';
  row.append(b);
  document.getElementById('log').append(row);
  window.JarvisMedia.cards(row, cards);
  row.scrollIntoView();
  return { cards: row.querySelectorAll('.plan-batch').length, html: row.innerHTML.length };
}"""


class Rig:
    def __init__(self, browser: Any, url: str, token: str) -> None:
        self.browser, self.url, self.token = browser, url, token
        self.pages: dict[tuple[str, str], Console] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.approvals: list[dict[str, Any]] = [BATCH_CARD, MOVE_CARD]
        self.view: dict[str, Any] = {
            "part": "plan", "ready": "ready", "plans": [PLAN_ROW], "waiting": [WAITING]
        }  # fmt: skip
        self.approval_reads = 0

    def _approvals(self, route: Any) -> None:
        self.approval_reads += 1
        route.fulfill(status=200, content_type="application/json", body=json.dumps(self.approvals))

    def _series(self, route: Any) -> None:
        req = route.request
        path = req.url.split("/v1/series", 1)[1]
        body = json.loads(req.post_data) if req.post_data else None
        self.calls.append((req.method, path, body))
        answer: dict[str, Any] = self.view
        if path == "/answer":
            skipped = body["answer"] == "skipped"
            said = (
                SKIPPED_SAID if skipped else "Session 6 of 60 in your CCA plan is marked done, Sir."
            )
            answer = {"pending": skipped, "session_id": SID, "message": said, "refused": False}
            self.view = {**self.view, "waiting": []}
            if skipped:
                self.approvals = [MOVE_CARD]
        elif path == "/replan":
            self.approvals = [MOVE_CARD]
            answer = {"pending": True, "session_id": SID, "message": REPLAN.splitlines()[0]}
        elif path == "/batches/retry":
            said = batch_card(body["events"], there=0).splitlines()[0]
            answer = {"pending": True, "session_id": SID, "message": said}
        elif path.endswith("/undo"):
            answer = {k: UNDONE[k] for k in ("message", "removed", "kept", "failed")}
            answer["unavailable"] = False
        route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))

    def get(self, vp: str, surface: str) -> Console:
        key = (vp, surface)
        if key not in self.pages:
            c = Console(self.browser, self.url, self.token, DESKTOP if vp == "desktop" else PHONE)
            install_mocks(c.page)
            c.page.route("**/v1/series**", self._series)
            c.page.route("**/v1/approvals", self._approvals)
            c.open()
            if surface == "day":
                c.page.locator("#themeBtn").click()
                c.page.locator('label[for="jx-s-day"]').click()
                c.page.keyboard.press("Escape")
            c.page.wait_for_function(
                "() => !!(window.JarvisFixes && window.JarvisFixes.parts.plan)"
            )
            c.page.wait_for_timeout(800)
            self.pages[key] = c
        return self.pages[key]

    def close(self) -> None:
        for c in self.pages.values():
            c.close()


@pytest.fixture(scope="module")
def rig(server_url: str, token: str) -> Iterator[Rig]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        r = Rig(b, server_url, token)
        yield r
        r.close()
        b.close()


def _approvals_panel(c: Console) -> None:
    _open(c, "approvals")
    c.page.locator("#approvals .approval .plan-list").first.wait_for(state="attached", timeout=5000)
    c.page.locator("#planChecks .plan-check").first.wait_for(state="attached", timeout=5000)
    c.page.wait_for_timeout(300)
    c.page.evaluate(FINISH_ANIMATIONS_JS)


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_plan_cards_pass_the_visual_gate(rig: Rig, vp: str, surface: str) -> None:
    c = rig.get(vp, surface)
    _approvals_panel(c)
    page = c.page
    batch = page.locator('#approvals .approval[data-id="card-batch-0001"]')
    lines = batch.locator(".plan-list li").all_text_contents()
    assert len(lines) == 60 and lines[0] == "1. Mon 16 Nov 2026, 19:00-20:00 · Topic 1"
    assert lines[59].startswith("60. Fri 5 Feb 2027, 19:00-20:00")
    assert "Add 60 events to your calendar" in (batch.locator("p").first.text_content() or "")
    move = page.locator('#approvals .approval[data-id="card-move-0001"]')
    moves = move.locator(".plan-list li").all_text_contents()
    assert len(moves) == 54 and moves[0] == "7. Tue 24 Nov 19:00 → Wed 25 Nov 19:00"
    head = move.locator("p").first.text_content() or ""
    assert "60 sessions before, 60 after" in head and "→" not in head
    assert page.locator("#planChecks .plan-q").all_text_contents() == [WAITING["text"]]
    scroll = batch.locator(".plan-list").evaluate(
        "e => [e.scrollHeight > e.clientHeight, e.tabIndex]"
    )
    assert scroll == [True, 0]  # it scrolls, and a keyboard can reach it
    page.evaluate(DRAW_JS, [[REPLY_CARD]])
    page.wait_for_timeout(500)
    page.evaluate(FINISH_ANIMATIONS_JS)  # the new row's own entry animation
    for sel in ("#p-approvals", "#p-chat"):
        if not page.locator(sel).is_visible():  # a phone shows one panel at a time
            continue
        res = page.evaluate(DOM_CHECKS_JS, sel)
        _assert_clean(
            res,
            page.evaluate(NAMELESS_JS, sel),
            page.evaluate(WRAP_JS, sel),
            vp,
            f"plan {sel} {vp} {surface}",
        )
    assert c.errors == [] and c.csp_violations() == []


def test_the_reply_card_passes_the_gate_on_a_phone_too(rig: Rig) -> None:
    c = rig.get("phone", "night")
    _open(c, "chat")
    assert c.page.evaluate(DRAW_JS, [[REPLY_CARD]])["cards"] == 1
    c.page.wait_for_timeout(300)
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, "#p-chat")
    _assert_clean(
        res,
        c.page.evaluate(NAMELESS_JS, "#p-chat"),
        c.page.evaluate(WRAP_JS, "#p-chat"),
        "phone",
        "plan reply card phone night",
    )
    assert c.errors == [] and c.csp_violations() == []


def test_undo_all_needs_two_taps_and_retry_asks_for_a_card(rig: Rig) -> None:
    c = rig.get("desktop", "night")
    page = c.page
    _open(c, "chat")
    assert page.evaluate(DRAW_JS, [[REPLY_CARD]])["cards"] == 1
    card = page.locator("#plan-test-row .plan-batch")
    assert card.locator(".plan-q").text_content() == "58 events added, 2 failed, Sir."
    rig.calls.clear()
    undo = card.get_by_role("button", name="Undo all")
    undo.click()
    page.wait_for_timeout(200)
    assert rig.calls == []  # the first tap only arms it
    card.get_by_role("button", name="Tap again to remove all 58").click()
    card.locator(".plan-said").get_by_text("Removed 58 events, Sir.").wait_for(timeout=5000)
    assert [(m, p) for m, p, _ in rig.calls if m == "POST"] == [("POST", f"/batches/{BATCH}/undo")]
    assert card.get_by_role("button", name="Undo all").is_disabled()
    rig.calls.clear()
    card.get_by_role("button", name="Retry the 2").click()
    card.locator(".plan-said").get_by_text("It is waiting in Approvals.").wait_for(timeout=5000)
    [(method, path, body)] = [x for x in rig.calls if x[0] == "POST"]
    assert (method, path) == ("POST", "/batches/retry")
    assert body["batch"] == BATCH and body["name"] == "CCA"
    assert [e["n"] for e in body["events"]] == [12, 40]
    assert set(body["events"][0]) == {"n", "summary", "start", "end", "why"}  # nothing empty sent
    odd = page.evaluate(DRAW_JS, [[{**REPLY_CARD, "batch": "<img src=x>"}, {"kind": "places"}]])
    assert odd["cards"] == 0
    assert c.errors == [] and c.csp_violations() == []


def test_skipped_only_asks_the_server_and_reloads_approvals(rig: Rig) -> None:
    c = rig.get("desktop", "day")
    _approvals_panel(c)
    page = c.page
    rig.calls.clear()
    reads = rig.approval_reads
    page.locator("#planChecks").get_by_role("button", name="Skipped").click()
    page.locator("#planChecks .plan-said").get_by_text("A new schedule is waiting").wait_for(
        timeout=5000
    )
    posts = [x for x in rig.calls if x[0] == "POST"]
    assert [(m, p) for m, p, _ in posts] == [("POST", "/answer")]
    assert posts[0][2]["answer"] == "skipped" and posts[0][2]["series"] == PLAN.id
    assert posts[0][2]["session"] == 6 and "user_id" not in posts[0][2]
    page.wait_for_function("() => document.querySelectorAll('#approvals .approval').length === 1")
    assert rig.approval_reads > reads  # the console reloaded its Approvals list
    assert page.locator("#approvals .approval").count() == 1  # the re-plan card, alone now
    assert page.locator("#planChecks .plan-check").count() == 0  # nothing left to ask
    # without a re-plan card, a skipped session offers "Propose new dates"
    rig.approvals = []
    page.evaluate("() => document.dispatchEvent(new CustomEvent('jarvis:approvals-stale'))")
    page.locator("#planChecks").get_by_role("button", name="Propose new dates").wait_for(
        timeout=5000
    )
    assert page.locator("#approvals .empty").is_hidden()  # no "Nothing waiting." under it
    rig.calls.clear()
    page.locator("#planChecks").get_by_role("button", name="Propose new dates").click()
    page.locator('#approvals .approval[data-id="card-move-0001"]').wait_for(timeout=5000)
    assert [(m, p) for m, p, _ in rig.calls if m == "POST"] == [("POST", "/replan")]
    assert c.errors == [] and c.csp_violations() == []


def test_the_brief_shows_the_inbox_by_kind(rig: Rig) -> None:
    c = rig.get("desktop", "night")
    got = c.page.evaluate(
        """(inbox) => window.JarvisBriefSections.render({ inbox }).map((s) => s.textContent)""",
        {
            "total": 47,
            "items": [],
            "groups": [
                {"key": "people", "label": "People", "unread": 2},
                {"key": "bills", "label": "Bills and orders", "unread": 3},
                {"key": "promotions", "label": "Promotions", "unread": 30},
                {"key": "social", "label": "<b>Social</b>", "unread": 0},
            ],
            "withheld": 2,
            "exact": True,
        },
    )
    assert got == [
        "Inbox by kindPeople · 2 unreadBills and orders · 3 unreadPromotions · 30 unread"
        "2 more look like codes or bank messages: open them in Gmail."
    ]
    none = c.page.evaluate(
        "() => window.JarvisBriefSections.render({ inbox: { total: 3, items: [] } }).length"
    )
    assert none == 0  # a brief without the groups shows no such section
    assert c.errors == [] and c.csp_violations() == []
