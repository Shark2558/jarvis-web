# tests/browser/test_alerts.py -- R3 D10/D11 in a real browser: Integrations -> Alerts. Quiet hours,
# "Only urgent things ring", per-kind switches, VIP list, names, the photo opt-in with its focus-
# trapped confirm, "This device" (service worker registered with scope /static/push/ and no fetch
# handler; the permission prompt and the push service are stubbed), device list, Test, hostile text
# shown as text, a 390 px phone with no sideways scroll. /v1/notify* and /v1/push* are answered by
# the test (page.route); the console is the real one, with I1's tags and console-sw.js served
# from APP_ASSETS.
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
expect = _pw.expect

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
HOSTILE = '<img src=x onerror="window.__pwned=1">Phone'
KEYS = [
    "home_intruder", "home_hazard", "home_summary", "home_package", "home_offline",
    "home_offline_idle", "home_arm_failed", "approval_waiting", "vault_expiry", "home_greeting",
    "home_online", "offline_on", "offline_off", "brief_ready",
    "book_sealed", "book_seal_failed", "book_session_closed",  # R6
    "disaster_alert", "bill_due", "birthday", "chore_due", "maintenance_due",  # R11 D5
    "weather_warning", "breach_notice", "nudge_standup", "nudge_hydrate", "nudge_activity",
    "nudge_free_time", "nudge_focus", "weather_note",
    "series_checkin", "faces_to_name",  # R11.1 I0
]  # fmt: skip
FIXED = {"home_intruder", "home_hazard", "home_summary"}
LEVEL = {"home_intruder": "urgent", "home_hazard": "urgent", "home_summary": "urgent",
         "home_greeting": "info", "home_online": "info", "offline_on": "info",
         "offline_off": "info", "brief_ready": "info",
         "disaster_alert": "urgent", "weather_note": "info",
         "faces_to_name": "info"}  # fmt: skip
VAPID = "B" + "A" * 86
# a real-looking (but fake) subscription the stubbed push manager returns
SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/stub",
    "keys": {"p256dh": "BAAA", "auth": "AAAA"},
}
INIT = """
window.__perm = 'granted';
Notification.requestPermission = async () => window.__perm;
const fake = {
  toJSON: () => (__SUB__),
  unsubscribe: async () => { window.__unsub = true; return true; },
};
PushManager.prototype.subscribe = async function () {
  window.__subscribed = true;
  return fake;
};
PushManager.prototype.getSubscription = async function () {
  return window.__subscribed ? fake : null;
};
""".replace("__SUB__", json.dumps(SUB))


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Fake:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.settings: dict[str, Any] = {
            "available": True,
            "quiet": {"on": True, "start": "23:00", "end": "06:30"},
            "ring_for": "urgent",
            "kinds": {
                k: {"switch": "feed" if k == "home_greeting" else "on",
                    "level": LEVEL.get(k, "important"), "fixed": k in FIXED}
                for k in KEYS
            },
            "names_in_alerts": False,
            "snapshot": {"on": False},
        }  # fmt: skip
        # review S6: the list carries a hint, never the number or address itself
        self.vip: list[dict[str, str]] = [{"id": "v_00000001", "kind": "phone", "hint": HOSTILE}]
        self.devices: list[dict[str, str]] = []
        self.test_body: dict[str, Any] = {"sent": True, "telegram": True, "browsers": 1}
        self.confirm_seen = False


def _wire(page: Any, fake: Fake) -> None:
    def json_(route: Any, body: Any, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def api(route: Any) -> None:
        req = route.request
        path = req.url.split("/v1/", 1)[1].split("?")[0]
        entry: dict[str, Any] = {
            "method": req.method,
            "path": path,
            "csrf": req.headers.get("x-requested-with"),
        }
        body = req.post_data_json if req.post_data else None
        if body is not None:
            entry["body"] = body
        fake.calls.append(entry)
        s = fake.settings
        if path == "notify/settings" and req.method == "GET":
            return json_(route, s)
        if path == "notify/settings":
            if body.get("snapshot", {}).get("on") and not body["snapshot"].get("confirm"):
                return json_(route, {"error": "confirm_required", "detail": "Confirm."}, 422)
            if "quiet" in body:
                s["quiet"] = {**s["quiet"], **body["quiet"]}
            if "ring_for" in body:
                s["ring_for"] = body["ring_for"]
            if "names_in_alerts" in body:
                s["names_in_alerts"] = body["names_in_alerts"]
            if "snapshot" in body:
                s["snapshot"] = {"on": body["snapshot"]["on"]}
            for k, v in (body.get("kinds") or {}).items():
                s["kinds"][k]["switch"] = v
            return json_(route, s)
        if path == "notify/vip" and req.method == "GET":
            return json_(route, {"available": True, "vip": fake.vip})
        if path == "notify/vip" and req.method == "POST":
            digits = [ch for ch in body["ref"] if ch.isdigit()]
            fake.vip.append(
                {
                    "id": f"v_0000000{len(fake.vip) + 1}",
                    "kind": body["kind"],
                    "hint": "ends in " + "".join(digits[-2:]),
                }
            )
            return json_(route, {"id": fake.vip[-1]["id"], "kind": body["kind"]}, 201)
        if path.startswith("notify/vip/"):
            fake.vip = [v for v in fake.vip if v["id"] != path.rsplit("/", 1)[1]]
            return json_(route, {"removed": True})
        if path == "push/key":
            return json_(route, {"available": True, "key": VAPID})
        if path == "push/devices":
            return json_(route, {"available": True, "devices": fake.devices})
        if path == "push/subscribe" and req.method == "POST":
            fake.devices.append({"id": "w_00000001", "name": body["name"], "added_at": "t"})
            return json_(route, fake.devices[-1], 201)
        if path.startswith("push/subscribe/"):
            fake.devices = []
            return json_(route, {"removed": True})
        if path == "push/test":
            return json_(route, fake.test_body)
        return json_(route, {"error": "nope", "detail": "x"}, 404)

    page.route("**/v1/notify/**", api)
    page.route("**/v1/push/**", api)


def _open(
    browser: Any, server_url: str, token: str, fake: Fake, viewport: dict[str, int]
) -> Console:
    c = Console(browser, server_url, token, viewport)
    c.page.add_init_script(INIT)
    _wire(c.page, fake)
    c.open()
    c.open_panel("integrations")
    c.page.locator("#integrations").wait_for()
    c.page.wait_for_function("window.JarvisAlerts !== undefined")
    c.page.evaluate("window.JarvisAlerts.refresh()")
    c.page.locator("#alertsSet[data-state='ready']").wait_for()
    return c


def _last(fake: Fake, method: str, path: str, page: Any = None, n: int = 1) -> dict[str, Any]:
    """The newest matching call; with `page`, wait (up to 5 s) until there are `n` of them."""
    for _ in range(100):
        found = [x for x in fake.calls if x["method"] == method and x["path"] == path]
        if len(found) >= n or page is None:
            break
        page.wait_for_timeout(50)
    return found[-1]


def test_defaults_show_urgent_only_quiet_hours_and_fixed_kinds(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        assert "Urgent only" in str(c.page.locator("#alertsSet .istate").text_content())
        assert c.page.locator("#alertsOnlyUrgent").get_attribute("aria-pressed") == "true"
        assert c.page.locator("#alertsQuiet").get_attribute("aria-pressed") == "true"
        assert c.page.locator("#alertsFrom").input_value() == "23:00"
        assert c.page.locator("#alertsTo").input_value() == "06:30"
        assert c.page.locator("#alertsKinds select").count() == len(KEYS) - len(FIXED)
        assert c.page.locator("#alertsKind_home_intruder").count() == 0  # no switch: always on
        assert "always on" in str(c.page.locator("#alertsKinds").text_content())
        assert c.page.locator("#alertsKind_home_greeting").input_value() == "feed"
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_laptop_idle_alert_has_its_own_row_in_plain_words(
    browser: Any, server_url: str, token: str
) -> None:
    """R5.1 int-code M1: "laptop stopped answering while the alarm is off" can be switched off."""
    fake = Fake()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        sel = c.page.locator("#alertsKind_home_offline_idle")
        assert sel.count() == 1
        assert sel.get_attribute("aria-label") == "Laptop stopped answering (alarm off)"
        assert "Laptop stopped answering (alarm off)" in str(
            c.page.locator("#alertsKinds").text_content()
        )
        sel.select_option("off")
        c.page.wait_for_timeout(300)
        assert any(
            (call.get("body") or {}).get("kinds") == {"home_offline_idle": "off"}
            for call in fake.calls
        ), fake.calls
    finally:
        c.close()


def test_switches_and_times_are_saved_with_the_csrf_header(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#alertsOnlyUrgent").click()
        c.page.locator("#alertsOnlyUrgent[aria-pressed='false']").wait_for()
        put = _last(fake, "PUT", "notify/settings")
        assert put["body"] == {"ring_for": "important"} and put["csrf"] == "JARVIS"
        c.page.locator("#alertsFrom").fill("22:15")
        c.page.locator("#alertsQuietSave").click()
        assert _last(fake, "PUT", "notify/settings", c.page, 2)["body"] == {
            "quiet": {"start": "22:15", "end": "06:30"}
        }
        c.page.locator("#alertsOnlyUrgent:not([aria-disabled])").wait_for()  # the save has finished
        c.page.locator("#alertsKind_home_package").select_option("off")
        assert _last(fake, "PUT", "notify/settings", c.page, 3)["body"] == {
            "kinds": {"home_package": "off"}
        }
        c.page.locator("#alertsNames").click()
        c.page.locator("#alertsNames[aria-pressed='true']").wait_for()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_photo_opt_in_needs_a_confirm_and_cancel_changes_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#alertsPhoto").click()
        c.page.locator("#alertsDialog[open]").wait_for()
        assert "Telegram keeps chats on its servers" in str(
            c.page.locator("#alertsDialogText").text_content()
        )
        assert c.page.evaluate("document.activeElement.id") == "alertsDialogNo"  # the safe choice
        c.page.keyboard.press("Tab")
        assert c.page.evaluate("document.activeElement.id") == "alertsDialogYes"
        c.page.keyboard.press("Tab")
        assert c.page.evaluate("document.activeElement.id") == "alertsDialogNo"  # the trap
        c.page.keyboard.press("Escape")
        assert not c.page.evaluate("document.getElementById('alertsDialog').open")
        assert not [x for x in fake.calls if x["method"] == "PUT"]
        c.page.locator("#alertsPhoto").click()
        c.page.locator("#alertsDialogYes").click()
        c.page.locator("#alertsPhoto[aria-pressed='true']").wait_for()
        assert _last(fake, "PUT", "notify/settings")["body"] == {
            "snapshot": {"on": True, "confirm": True}
        }
        c.page.locator("#alertsPhoto").click()  # off needs no confirm
        c.page.locator("#alertsPhoto[aria-pressed='false']").wait_for()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_vip_list_adds_removes_and_shows_hostile_text_as_text(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        assert HOSTILE in str(c.page.locator("#alertsVips").text_content())
        assert (
            c.page.evaluate("window.__pwned") is None
            and c.page.locator("#alertsVips img").count() == 0
        )
        c.page.locator("#alertsVipRef").fill("+91 98765 43210")
        c.page.locator("#alertsVipAdd").click()
        c.page.locator("#alertsVips li", has_text="ends in 10").wait_for()
        assert _last(fake, "POST", "notify/vip")["body"] == {
            "kind": "phone",
            "ref": "+91 98765 43210",
        }
        assert "98765" not in str(c.page.locator("#alertsVips").text_content())
        c.page.locator("#alertsVips li", has_text="ends in 10").locator("button").click()
        expect(c.page.locator("#alertsVips li")).to_have_count(1)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_this_device_registers_the_worker_with_the_push_scope_and_subscribes(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#alertsEnable").click()
        c.page.locator("#alertsDevices li").wait_for()
        sub = _last(fake, "POST", "push/subscribe")
        assert sub["csrf"] == "JARVIS" and sub["body"]["endpoint"] == SUB["endpoint"]
        assert sub["body"]["keys"] == SUB["keys"] and "Chrome" in sub["body"]["name"]
        scope = c.page.evaluate(
            "navigator.serviceWorker.getRegistrations().then(r => r.map(x => x.scope))"
        )
        assert any(s.endswith("/static/push/") for s in scope)
        assert c.page.evaluate("window.__subscribed") is True
        # remove: the server forgets it and this browser unsubscribes
        c.page.locator("#alertsDevices li button").click()
        expect(c.page.locator("#alertsDevices li")).to_have_count(0)
        assert c.page.evaluate("window.__unsub") is True
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_denied_permission_explains_and_subscribes_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.evaluate("window.__perm = 'denied'")
        c.page.locator("#alertsEnable").click()
        c.page.locator("#alertsNote.bad").wait_for()
        assert "blocked" in str(c.page.locator("#alertsNote").text_content())
        assert not [x for x in fake.calls if x["path"] == "push/subscribe"]
    finally:
        c.close()


def test_the_service_worker_has_only_push_and_click_handlers_and_no_fetch() -> None:
    src = (STATIC / "console-sw.js").read_text()
    assert "addEventListener('push'" in src and "addEventListener('notificationclick'" in src
    assert "'fetch'" not in src and '"fetch"' not in src and "onfetch" not in src
    assert len(src.splitlines()) <= 80
    assert src.isascii()


def test_the_worker_shows_the_template_text_and_ignores_junk(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.goto(server_url + "/health")
        out = c.page.evaluate(
            """async () => {
              const shown = [];
              const handlers = {};
              const show = (t, o) => { shown.push([t, o]); return Promise.resolve(); };
              const self = {
                addEventListener: (n, f) => { handlers[n] = f; },
                registration: { showNotification: show },
              };
              new Function('self', __SRC__)(self);
              const json = (d) => { if (d === 'bad') throw new Error('x'); return d; };
              const ev = (d) => ({ data: { json: () => json(d) }, waitUntil: (p) => p });
              const good = { kind: 'home_intruder', text: 'Someone at the Gate.', url: '/#home' };
              await handlers.push(ev(good));
              await handlers.push(ev({ kind: 'x', text: 'ok', url: 'https://evil.example/' }));
              await handlers.push(ev('bad'));
              await handlers.push(ev({ kind: 'x', text: 'ok', url: '//evil.example/x' }));
              return shown;
            }""".replace("__SRC__", json.dumps((STATIC / "console-sw.js").read_text()))
        )
        assert out[0][1]["body"] == "Someone at the Gate." and out[0][1]["data"]["url"] == "/#home"
        assert out[1][1]["data"]["url"] == "/"  # a foreign address is never a click target
        assert out[2][1]["body"] == "JARVIS has something for you."
        assert out[3][1]["data"]["url"] == "/"  # a protocol-relative address is not a path
    finally:
        c.close()


def test_test_button_reports_where_it_went_and_says_when_nothing_could(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#alertsTest").click()
        c.page.locator(
            "#alertsNote.inote:not(.bad)", has_text="Test sent to Telegram and this device"
        ).wait_for()
        fake.test_body = {"sent": False, "reason": "No channel could deliver it."}
        c.page.locator("#alertsTest").click()
        c.page.locator("#alertsNote.bad").wait_for()
        assert "No channel" in str(c.page.locator("#alertsNote").text_content())
    finally:
        c.close()


def test_off_server_says_so(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.add_init_script(INIT)
        c.page.route(
            "**/v1/notify/**",
            lambda r: r.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"available": False, "reason": "x"}),
            ),
        )
        c.page.route(
            "**/v1/push/**",
            lambda r: r.fulfill(status=200, content_type="application/json", body="{}"),
        )
        c.open()
        c.open_panel("integrations")
        c.page.wait_for_function("window.JarvisAlerts !== undefined")
        c.page.evaluate("window.JarvisAlerts.refresh()")
        c.page.locator("#alertsSet[data-state='off']").wait_for()
        assert "aren't set up" in str(c.page.locator("#alertsBody").text_content())
    finally:
        c.close()


def test_phone_has_no_sideways_scroll(browser: Any, server_url: str, token: str) -> None:
    fake = Fake()
    c = _open(browser, server_url, token, fake, PHONE)
    try:
        wide = c.page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert wide is False
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
