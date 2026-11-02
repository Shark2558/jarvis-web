# tests/browser/test_permissions.py — Approvals → Permissions and "Approve with passkey" in a real
# Chromium (slice 10 D + its security review). The passkey ceremony is real end to end: Chromium's
# virtual authenticator (CDP WebAuthn.addVirtualAuthenticator, user verification on) answers
# navigator.credentials, and the real server (permissions_server.py: Google sign-in mode, everything
# real but Google's half of sign-in and the model) verifies with py_webauthn.
# Covers: the collapsed section and its summary, Allow / Ask first / Never (irreversible rows offer
# two), the first passkey needing a re-sign-in (/auth/login?reauth=1 → back with the window open),
# setting it up, an irreversible card approved with it (exactly one send), a 24-hour reset started
# and cancelled with the passkey (banner on and off), a cancelled check left as a plain message on
# the card (nothing sent), "not supported in this browser", and a server without passkeys.
# 0 JS errors and 0 CSP reports throughout.
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import CSP_SPY, DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOKEN = "browser-permissions-token-not-a-secret"
OWNER = "owner@example.com"
AUTHENTICATOR = {
    "protocol": "ctap2",
    "transport": "internal",
    "hasResidentKey": True,
    "hasUserVerification": True,
    "isUserVerified": True,
    "automaticPresenceSimulation": True,
}


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def perm_url() -> Iterator[str]:
    """The real app (Google sign-in mode, scripted model) at http://localhost:<port>."""
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    port = _port()
    url = f"http://localhost:{port}"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "JARVIS_ENV": "dev",
        "JARVIS_LLM_BACKEND": "mock",
        "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_AUTH_MODE": "google",
        "JARVIS_GOOGLE_CLIENT_ID": "browser-test.apps.googleusercontent.com",
        "JARVIS_GOOGLE_CLIENT_SECRET": "browser-test-secret",
        "JARVIS_GOOGLE_TOOLS_ENABLED": "false",  # the dev send_message tool stays registered
        "JARVIS_OWNER_EMAILS": OWNER,
        "JARVIS_SESSION_SECRET": "b" * 40,
        "JARVIS_API_TOKEN": TOKEN,
        "JARVIS_LOG_LEVEL": "WARNING",
        "JARVIS_USD_INR_LIVE": "0",
        # One server serves the module from one IP; the app's 120/min per-IP limit (unit-tested
        # in tests/) would turn a fast CI runner's requests into 429s (as in conftest.py).
        "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
        "JARVIS_PUBLIC_BASE_URL": url,
    }
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "permissions_server.py"), str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 30
    while True:
        if proc.poll() is not None:
            err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            raise RuntimeError(f"permissions server exited early:\n{err}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    break
        except (urllib.error.URLError, OSError):
            if time.monotonic() > deadline:
                proc.kill()
                raise RuntimeError("permissions server did not become healthy") from None
            time.sleep(0.2)
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _get(url: str, path: str) -> Any:
    req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _google_open(c: Console) -> None:
    """Load the console and sign in through the real /auth routes (Google's half is faked)."""
    c.page.goto(c.url + "/")
    c.page.locator("#gBtn, #welcome").first.wait_for()
    if c.page.locator("#gBtn").count():
        c.page.locator("#gBtn").click()
    c.page.locator("#welcome").wait_for()


def _errors(c: Console) -> list[str]:
    """JS errors, minus the signed-out probe of Google mode (GET /auth/me → 401 before sign-in)."""
    return [e for e in c.errors if not ("401" in e and e.endswith("/auth/me"))]


def _with_authenticator(c: Console) -> tuple[Any, str]:
    cdp = c.ctx.new_cdp_session(c.page)
    cdp.send("WebAuthn.enable", {"enableUI": False})
    auth = cdp.send("WebAuthn.addVirtualAuthenticator", {"options": AUTHENTICATOR})
    return cdp, str(auth["authenticatorId"])


def _open_permissions(c: Console) -> None:
    c.open_panel("approvals")
    btn = c.page.locator("#permSetBtn")
    if btn.get_attribute("aria-expanded") != "true":
        btn.click()
    c.page.locator("#permGroups .pgrp").first.wait_for()


def _sent(url: str) -> int:
    entries = _get(url, "/v1/audit?limit=50")["entries"]
    return [e["outcome"] for e in entries if e["tool"] == "send_message"].count("executed")


def test_permissions_rows_passkey_set_up_approve_and_reset(browser: Any, perm_url: str) -> None:
    c = Console(browser, perm_url, TOKEN, DESKTOP)
    try:
        cdp, auth_id = _with_authenticator(c)
        _google_open(c)
        _open_permissions(c)
        page = c.page
        rows = page.locator("#permGroups .pgrp")
        assert rows.count() >= 9
        send = rows.filter(has_text="Send email")
        assert send.locator(".seg-opt").all_text_contents() == ["Ask first", "Never"]
        web = rows.filter(has_text="Search and read the web")
        assert web.locator(".seg-opt").all_text_contents() == ["Allow", "Ask first", "Never"]
        web.get_by_text("Never", exact=True).click()
        page.locator("#permNote", has_text="Search and read the web: Never.").wait_for()
        assert web.locator("input[value=deny]").is_checked()

        # an ordinary sign-in can't set up the first passkey: sign in with Google again
        assert page.locator("#pskAdd").count() == 0
        page.locator("#pskReauth").click()
        page.locator("#permNote", has_text="Signed in again").wait_for()
        page.locator("#pskLabel").fill("Test laptop")
        page.locator("#pskAdd").click()
        page.locator(".pskrow", has_text="Test laptop").wait_for()
        assert page.locator("#pskReq").get_attribute("aria-pressed") == "true"
        page.locator("#permSetBtn").click()  # collapse: the one-line summary says it all
        summary = str(page.locator("#permSum").text_content())
        assert "1 switched off" in summary and "Passkey on (1)" in summary

        # an irreversible card is approved with the passkey: exactly one send
        c.send("send: lunch at one")
        card = page.locator("#approvals .approval").first
        card.wait_for()
        approve = card.locator(".approve")
        assert approve.text_content() == "Approve with passkey"
        approve.click()
        page.locator(".row.jarvis .bubble", has_text="Noted, Sir.").nth(1).wait_for()
        page.locator("#approvals .empty", has_text="Nothing waiting.").wait_for()
        assert _sent(perm_url) == 1

        # lost passkeys: a reset starts (still within the re-sign-in window), shows a banner,
        # changes nothing yet, and any passkey cancels it
        page.locator("#permSetBtn").click()
        page.locator("#pskReset").click()
        page.locator("#pskResetYes").click()
        banner = page.locator("#permBanner")
        banner.wait_for(state="visible")
        assert "every passkey will be removed" in str(banner.text_content())
        page.locator("#pskCancelReset").click()
        page.locator("#permNote", has_text="Reset cancelled").wait_for()
        banner.wait_for(state="hidden")
        assert page.locator(".pskrow").count() == 1

        # the check is cancelled (no passkey on this device any more): plain words, nothing sent
        cdp.send("WebAuthn.clearCredentials", {"authenticatorId": auth_id})
        c.send("send: second message")
        card = page.locator("#approvals .approval").first
        card.wait_for()
        card.locator(".approve").click()
        err = card.locator(".perr")
        err.wait_for(state="visible")
        assert "Nothing was changed" in str(err.text_content())
        assert card.locator(".approve").is_enabled()
        assert _sent(perm_url) == 1
        assert c.csp_violations() == [] and _errors(c) == []
    finally:
        c.close()


def test_without_passkey_support_the_section_says_so(browser: Any, perm_url: str) -> None:
    c = Console(browser, perm_url, TOKEN, PHONE)
    try:
        c.page.add_init_script("delete window.PublicKeyCredential;")
        _google_open(c)
        _open_permissions(c)
        c.page.locator("#pskBox .lerr", has_text="not supported in this browser").wait_for()
        assert c.page.locator("#pskAdd").count() == 0
        # the phone layout keeps 44 px targets and no sideways scroll
        h = c.page.locator("#permGroups .seg-opt").first.bounding_box()
        assert h is not None and h["height"] >= 43
        assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert c.csp_violations() == [] and _errors(c) == []
    finally:
        c.close()


def test_a_server_without_passkeys_explains_why(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.add_init_script(CSP_SPY)
        c.open()
        _open_permissions(c)
        c.page.locator("#pskBox", has_text="JARVIS_PUBLIC_BASE_URL").wait_for()
        assert str(c.page.locator("#permSum").text_content()).endswith("Passkey not available")
        assert c.page.locator("#pskAdd").count() == 0
        assert c.page.locator("#permBanner").is_hidden()
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()
